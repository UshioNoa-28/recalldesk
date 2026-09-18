"""文档相关 HTTP 路由。"""

from __future__ import annotations

from pathlib import PurePosixPath

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from app.application.services.document.document_service import DocumentService
from app.config import UploadLimits

router = APIRouter(tags=["documents"])


@router.post("/documents")
@inject
async def upload_document(
    service: FromDishka[DocumentService],
    limits: FromDishka[UploadLimits],
    file: UploadFile = File(...),
) -> dict:
    """上传文件：存原文 + PG 元数据 + 出箱任务；分块/embedding/进索引都在后台 worker。"""

    filename = _safe_filename(file.filename or "")
    content = await file.read()
    _validate_upload(filename, content, limits)

    try:
        document = await service.ingest(
            name=filename,
            content=content,
            media_type=file.content_type,
        )
    except UnicodeDecodeError as exc:
        # 注意顺序：UnicodeDecodeError 是 ValueError 的子类，必须先捕获
        raise HTTPException(status_code=400, detail="文件必须是 UTF-8 文本") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"索引失败: {exc}") from exc

    return {
        "document_id": document.id,
        "name": document.name,
        "status": document.status,
    }


@router.get("/documents")
@inject
async def list_documents(
    service: FromDishka[DocumentService],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """分页列出文档。"""

    return await service.list_documents(page=page, page_size=page_size)


@router.get("/documents/{document_id}")
@inject
async def get_document(
    document_id: str,
    service: FromDishka[DocumentService],
) -> dict:
    """查看单个文档。"""

    try:
        return await service.detail(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc


@router.get("/search")
@inject
async def search(
    service: FromDishka[DocumentService],
    q: str = Query(..., min_length=1, description="查询文本"),
    top_k: int | None = Query(None, ge=1, le=50, description="返回数量"),
) -> dict:
    """检索知识库。"""

    hits = await service.search(q, top_k=top_k)
    return {"query": q, "hits": hits}


@router.get("/documents/{document_id}/chunks")
@inject
async def list_document_chunks(
    document_id: str,
    service: FromDishka[DocumentService],
) -> dict:
    """列出文档的全部分块（以向量库为准）。"""

    try:
        return await service.chunks(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc


@router.get("/documents/{document_id}/content")
@inject
async def get_document_content(
    document_id: str,
    service: FromDishka[DocumentService],
    download: bool = Query(False, description="true 时以附件形式下载"),
) -> PlainTextResponse:
    """读取/下载文档原始文本。"""

    try:
        name, text = await service.content(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if download else {}
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8", headers=headers)


@router.post("/documents/{document_id}/reindex")
@inject
async def reindex_document(
    document_id: str,
    service: FromDishka[DocumentService],
) -> dict:
    """重新索引：FAILED 文档救回来、SUCCESS 文档在改分块/嵌入参数后重建。

    后台 worker 按普通索引处理这条新任务（幂等：先清旧向量再写），状态回 PENDING。
    """

    try:
        document = await service.reindex(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "document_id": document.id,
        "name": document.name,
        "status": document.status,
    }


@router.post("/documents/{document_id}/rerun_graph")
@inject
async def rerun_document_graph(
    document_id: str,
    service: FromDishka[DocumentService],
) -> dict:
    """重跑图谱抽取：failed 复位重投、success 再抽一遍（幂等整篇替换）、在途 400。"""

    try:
        return await service.rerun_graph(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
@inject
async def delete_document(
    document_id: str,
    service: FromDishka[DocumentService],
) -> dict:
    """删除文档：PG 元数据、引用题清理与一条索引删除任务同事务提交，本地文件 best-effort。

    索引块由后台 worker 删，所以返回那一刻检索索引里可能还剩一瞬；引用这个
    文档的评测题由删除用例同事务显式 purge（0013 起无 FK 级联可指望）。
    """

    try:
        await service.delete(document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文档不存在") from exc
    return {"document_id": document_id, "deleted": True}


def _safe_filename(filename: str) -> str:
    name = filename.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名无效")
    return name


def _validate_upload(filename: str, content: bytes, limits: UploadLimits) -> None:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in limits.allowed_suffixes:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix}")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > limits.max_bytes:
        raise HTTPException(status_code=413, detail="文件过大")


__all__ = ["router"]

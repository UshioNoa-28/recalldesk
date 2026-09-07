"""评测集 HTTP 路由：建集、加题、列表 / 详情 / 删除，以及跑一次评测。

建集与加题是分开的两个动作：先 POST /eval/testsets 拿一个空集，再 POST
/eval/testsets/{id}/items 一批批往里加题。加题是异步的：返回时条目还是
pending，问题由后台 worker 填，所以要看生成的题目得轮询详情接口。

run 也是异步的：POST .../runs 只登记一次运行就返回，逐题检索在 API 进程后台跑，
进度与指标轮询 GET /eval/runs/{run_id}。
"""

from __future__ import annotations

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.application.services.eval_run_service import EvalRunService
from app.application.services.eval_service import EvalService
from app.domain.eval import ChunkRef

router = APIRouter(tags=["eval"])

# 一次加题最多勾多少块：每题都是一次 LLM 调用，防手滑
MAX_CHUNKS_PER_REQUEST = 200
# 一次 run 的 k 上限：k 越大越接近「整篇文档都塞进上下文」，那就不是检索在答题了
MAX_RUN_TOP_K = 50


class SelectedChunk(BaseModel):
    """出题素材的坐标：某文档的第几块。"""

    document_id: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)


class CreateTestSetRequest(BaseModel):
    """POST /eval/testsets 请求体。"""

    name: str | None = Field(None, max_length=255)


class AddItemsRequest(BaseModel):
    """POST /eval/testsets/{testset_id}/items 请求体。"""

    chunks: list[SelectedChunk] = Field(
        ..., min_length=1, max_length=MAX_CHUNKS_PER_REQUEST
    )


class CreateRunRequest(BaseModel):
    """POST /eval/testsets/{testset_id}/runs 请求体（可以不带）。"""

    top_k: int | None = Field(None, ge=1, le=MAX_RUN_TOP_K)


@router.post("/eval/testsets", status_code=201)
@inject
async def create_testset(
    request: CreateTestSetRequest,
    service: FromDishka[EvalService],
) -> dict:
    """创建一个空的评测集。"""

    return await service.create_testset(name=request.name)


@router.post("/eval/testsets/{testset_id}/items")
@inject
async def add_testset_items(
    testset_id: str,
    request: AddItemsRequest,
    service: FromDishka[EvalService],
) -> dict:
    """往评测集加题：同事务写题目与出题任务，问题由后台 LLM 生成。

    已经在集里的坐标会被跳过，所以重复提交同一批勾选是安全的。
    """

    try:
        return await service.add_items(
            testset_id,
            [
                ChunkRef(document_id=c.document_id, chunk_index=c.chunk_index)
                for c in request.chunks
            ],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/eval/testsets")
@inject
async def list_testsets(service: FromDishka[EvalService]) -> dict:
    """列出评测集（含进度）。"""

    return await service.list_testsets()


@router.get("/eval/testsets/{testset_id}")
@inject
async def get_testset(
    testset_id: str,
    service: FromDishka[EvalService],
) -> dict:
    """评测集详情：元信息 + 全部题目（含 LLM 生成的问题）。"""

    try:
        return await service.get_testset(testset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc


@router.delete("/eval/testsets/{testset_id}")
@inject
async def delete_testset(
    testset_id: str,
    service: FromDishka[EvalService],
) -> dict:
    """删除评测集：题目与未发出的出题任务一起删（级联）。"""

    try:
        await service.delete_testset(testset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc
    return {"testset_id": testset_id, "deleted": True}


@router.post("/eval/testsets/{testset_id}/runs", status_code=202)
@inject
async def start_run(
    testset_id: str,
    service: FromDishka[EvalRunService],
    request: CreateRunRequest = CreateRunRequest(),
) -> dict:
    """开一次检索评测：立即返回 run，逐题在后台跑。

    只测检索：题目自带的 chunk 坐标就是 ground truth，看的是「检索有没有把该
    捞的那块捞回来、排第几」，不看回答质量。进度和指标轮询 /eval/runs/{run_id}。
    """

    try:
        return await service.start_run(testset_id, top_k=request.top_k)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/eval/testsets/{testset_id}/runs")
@inject
async def list_runs(
    testset_id: str,
    service: FromDishka[EvalRunService],
) -> dict:
    """某评测集的历史运行（含指标，不含逐题结果），按时间倒序。"""

    try:
        return await service.list_runs(testset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测集不存在") from exc


@router.get("/eval/runs/{run_id}")
@inject
async def get_run(
    run_id: str,
    service: FromDishka[EvalRunService],
) -> dict:
    """运行详情：状态 + 进度 + 聚合指标 + 逐题结果（题面、命中名次、延迟）。"""

    try:
        return await service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="评测运行不存在") from exc


__all__ = ["router"]

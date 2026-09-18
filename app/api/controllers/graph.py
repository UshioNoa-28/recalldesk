"""知识图谱只读 HTTP 路由：图浏览器（Focus+Expand）的取数端点。

两个端点都无副作用：/graph/entities/search 出候选卡片（点哪个聚焦哪个），
/graph/entities/{name_norm}/neighborhood 出子图切片（nodes/edges，边带
evidence 坐标）——证据原文由前端拿坐标走既有 chunk 接口回查，这里不代答。
"""

from __future__ import annotations

from urllib.parse import unquote

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query

from app.application.services.graph.graph_explorer_service import GraphExplorerService

router = APIRouter(tags=["graph"])


@router.get("/graph/entities/search")
@inject
async def search_entities(
    service: FromDishka[GraphExplorerService],
    q: str = Query(default="", description="实体名/别名/前缀匹配查询词"),
    limit: int = Query(8, ge=1, le=30),
) -> dict:
    """实体名称匹配（精确 > 前缀 > 包含），返回候选实体卡片。"""

    results = await service.search_entities(q.strip(), limit=limit)
    return {"query": q, "results": results}


@router.get("/graph/entities/{name_norm}/neighborhood")
@inject
async def entity_neighborhood(
    service: FromDishka[GraphExplorerService],
    name_norm: str,
    hops: int = Query(1, ge=1, le=3, description="展开跳数（逐跳展开是主玩法）"),
    limit: int = Query(15, ge=1, le=300, description="节点预算：近跳+证据多者优先"),
) -> dict:
    """以该实体为圆心的子图切片；实体不存在 404。"""

    result = await service.neighborhood(unquote(name_norm), hops=hops, limit=limit)
    if not result["nodes"]:
        raise HTTPException(status_code=404, detail=f"实体不存在: {name_norm}")
    return result

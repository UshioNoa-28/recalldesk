"""HTTP API 层。"""

from fastapi import APIRouter

from app.api.controllers import document as document_controller
from app.api.controllers import eval as eval_controller
from app.api.controllers import graph as graph_controller

router = APIRouter()
router.include_router(document_controller.router)
router.include_router(eval_controller.router)
router.include_router(graph_controller.router)

__all__ = ["router"]

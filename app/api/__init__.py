"""HTTP API 层。"""

from fastapi import APIRouter

from app.api.controllers import document_controller, eval_controller

router = APIRouter()
router.include_router(document_controller.router)
router.include_router(eval_controller.router)

__all__ = ["router"]

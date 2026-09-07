"""FastAPI 应用装配测试（不启动 lifespan，不连数据库）。"""

from __future__ import annotations

from unittest import TestCase

from app.api.controllers.document_controller import router as document_router
from app.api.controllers.eval_controller import router as eval_router
from app.main import app, create_app


class AppAssemblyTests(TestCase):
    def test_app_has_health_route(self) -> None:
        paths = {getattr(route, "path", None) for route in app.routes}
        self.assertIn("/health", paths)

    def test_document_controller_registers_expected_paths(self) -> None:
        paths = {getattr(route, "path", None) for route in document_router.routes}
        self.assertIn("/documents", paths)
        self.assertIn("/documents/{document_id}", paths)
        self.assertIn("/search", paths)

    def test_eval_controller_registers_expected_paths(self) -> None:
        routes = {
            (getattr(route, "path", None), frozenset(getattr(route, "methods", set())))
            for route in eval_router.routes
        }
        self.assertIn(("/eval/testsets", frozenset({"POST"})), routes)
        self.assertIn(("/eval/testsets", frozenset({"GET"})), routes)
        self.assertIn(("/eval/testsets/{testset_id}", frozenset({"GET"})), routes)
        self.assertIn(("/eval/testsets/{testset_id}", frozenset({"DELETE"})), routes)
        self.assertIn(("/eval/testsets/{testset_id}/items", frozenset({"POST"})), routes)
        self.assertIn(("/eval/testsets/{testset_id}/runs", frozenset({"POST"})), routes)
        self.assertIn(("/eval/testsets/{testset_id}/runs", frozenset({"GET"})), routes)
        self.assertIn(("/eval/runs/{run_id}", frozenset({"GET"})), routes)

    def test_create_app_returns_fastapi_instance(self) -> None:
        from fastapi import FastAPI

        self.assertIsInstance(create_app(), FastAPI)


if __name__ == "__main__":
    import unittest

    unittest.main()

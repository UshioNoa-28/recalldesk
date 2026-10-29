from __future__ import annotations

from app.config import settings
from app.main import app


def client():
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_health():
    with client() as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_embed_empty_batch_does_not_touch_ollama():
    with client() as test_client:
        response = test_client.post("/embed", json={"texts": []})
    assert response.status_code == 200
    assert response.json() == {"vectors": [], "dim": settings.embedding_dim}


def test_rerank_empty_documents_returns_empty_scores():
    with client() as test_client:
        response = test_client.post("/rerank", json={"query": "q", "documents": []})
    assert response.status_code == 200
    assert response.json() == {"scores": []}


def test_rewrite_unavailable_returns_503(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_model", "")
    with client() as test_client:
        response = test_client.post("/rewrite", json={"query": "q"})
    assert response.status_code == 503
    assert "不可用" in response.json()["detail"]

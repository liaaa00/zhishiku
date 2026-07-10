from __future__ import annotations

import json

from app import main as app_main


class FakeSession:
    def execute(self, _statement) -> None:
        return None

    def close(self) -> None:
        return None


def _response_payload(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def _configure_healthy_dependencies(monkeypatch, *, qdrant_dimension: int = 3) -> None:
    monkeypatch.setattr(app_main, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        app_main,
        "get_embedding_config",
        lambda _db: {
            "provider": "openai-compatible",
            "base_url": "http://ollama:11434/v1",
            "model": "bge-m3",
            "api_key": "ollama",
        },
    )
    monkeypatch.setattr(
        app_main,
        "qdrant_health",
        lambda: {
            "qdrant_enabled": True,
            "qdrant_ready": True,
            "points_count": 78,
            "vector_size": qdrant_dimension,
        },
    )


def test_readiness_checks_database_qdrant_and_embedding(monkeypatch) -> None:
    _configure_healthy_dependencies(monkeypatch)
    calls: list[tuple[list[str], bool, float | None]] = []
    monkeypatch.setattr(
        app_main,
        "embed_texts",
        lambda texts, *, strict, timeout: calls.append((texts, strict, timeout)) or [[0.1, 0.2, 0.3]],
    )

    response = app_main.readiness()
    payload = _response_payload(response)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["components"]["database"]["ok"] is True
    assert payload["components"]["qdrant"]["dimension"] == 3
    assert payload["components"]["embedding"]["dimension"] == 3
    assert calls == [(["readiness probe"], True, 15.0)]


def test_readiness_returns_503_when_embedding_is_unavailable(monkeypatch) -> None:
    _configure_healthy_dependencies(monkeypatch)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(app_main, "embed_texts", unavailable)

    response = app_main.readiness()
    payload = _response_payload(response)

    assert response.status_code == 503
    assert payload["ok"] is False
    assert payload["components"]["database"]["ok"] is True
    assert payload["components"]["qdrant"]["ok"] is True
    assert payload["components"]["embedding"]["ok"] is False


def test_readiness_returns_503_when_vector_dimensions_do_not_match(monkeypatch) -> None:
    _configure_healthy_dependencies(monkeypatch, qdrant_dimension=1024)
    monkeypatch.setattr(app_main, "embed_texts", lambda *_args, **_kwargs: [[0.1, 0.2, 0.3]])

    response = app_main.readiness()
    payload = _response_payload(response)

    assert response.status_code == 503
    assert payload["components"]["qdrant"]["dimension"] == 1024
    assert payload["components"]["embedding"]["ok"] is False
    assert payload["components"]["embedding"]["dimension"] == 3


def test_qdrant_health_reports_collection_dimension(monkeypatch) -> None:
    from app import vector_store

    monkeypatch.setattr(vector_store, "qdrant_enabled", lambda: True)
    monkeypatch.setattr(
        vector_store,
        "_request",
        lambda *_args, **_kwargs: {
            "result": {
                "points_count": 78,
                "config": {"params": {"vectors": {"size": 1024, "distance": "Cosine"}}},
            }
        },
    )

    status = vector_store.qdrant_health()

    assert status["qdrant_ready"] is True
    assert status["points_count"] == 78
    assert status["vector_size"] == 1024

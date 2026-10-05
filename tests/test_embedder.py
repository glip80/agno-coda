"""Tests for the env-driven local embedder factory in :mod:`db.session`.

These tests are fully offline: constructing an ``OpenAILikeEmbedder`` does not
open a client or touch the network.
"""

from db.session import _embedding_base_url, _local_embedder


def test_embedding_base_url_defaults(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    assert _embedding_base_url() == "http://127.0.0.1:8000/v1"


def test_embedding_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8000/v1/")
    assert _embedding_base_url() == "http://127.0.0.1:8000/v1"


def test_embedding_base_url_normalizes_models_endpoint(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8000/v1/models")
    assert _embedding_base_url() == "http://127.0.0.1:8000/v1"


def test_embedding_base_url_normalizes_models_endpoint_with_trailing_slash(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8000/v1/models/")
    assert _embedding_base_url() == "http://127.0.0.1:8000/v1"


def test_local_embedder_defaults(monkeypatch):
    for var in (
        "EMBEDDING_MODEL_ID",
        "EMBEDDING_DIMENSIONS",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    embedder = _local_embedder()
    assert embedder.id == "mlx-community--bge-m3-mlx-fp16"
    assert embedder.dimensions == 1024
    assert embedder.api_key == "not-needed"
    assert embedder.base_url == "http://127.0.0.1:8000/v1"


def test_local_embedder_honors_env_overrides(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL_ID", "custom--embed-model")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("EMBEDDING_API_KEY", "secret-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://localhost:9000/v1/")

    embedder = _local_embedder()
    assert embedder.id == "custom--embed-model"
    assert embedder.dimensions == 768
    assert embedder.api_key == "secret-key"
    assert embedder.base_url == "http://localhost:9000/v1"

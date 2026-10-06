"""Offline tests for the standalone RAG module :mod:`coda.rag.knowledge`.

``get_rag`` is monkeypatched with a fake ``Knowledge`` so these tests never
create a ``PgVector`` instance, connect to Postgres, or hit the network.
"""

import pytest
from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.reader.website_reader import WebsiteReader

from coda.rag import knowledge


class FakeKnowledge:
    """Minimal stand-in for ``agno.knowledge.Knowledge`` that records calls."""

    def __init__(self, docs: list[Document] | None = None, contents: list | None = None) -> None:
        self.insert_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.remove_all_content_calls = 0
        self._docs = docs or []
        self._contents = contents or []

    def insert(self, **kwargs) -> None:
        self.insert_calls.append(kwargs)

    def search(self, query: str, max_results: int | None = None) -> list[Document]:
        self.search_calls.append({"query": query, "max_results": max_results})
        return self._docs

    def get_content(self) -> tuple[list, int]:
        return self._contents, len(self._contents)

    def remove_all_content(self) -> None:
        self.remove_all_content_calls += 1


def _patch_get_rag(monkeypatch, fake: FakeKnowledge) -> FakeKnowledge:
    monkeypatch.setattr(knowledge, "get_rag", lambda: fake)
    return fake


def test_ingest_url_single_page_defaults(monkeypatch):
    fake = _patch_get_rag(monkeypatch, FakeKnowledge())

    knowledge.ingest_url("http://example.com/page")

    assert len(fake.insert_calls) == 1
    call = fake.insert_calls[0]
    assert call["url"] == "http://example.com/page"
    assert call["upsert"] is True

    reader = call["reader"]
    assert isinstance(reader, WebsiteReader)
    assert reader.max_depth == 1
    assert reader.max_links == 1


def test_ingest_url_passes_depth_and_links_through(monkeypatch):
    fake = _patch_get_rag(monkeypatch, FakeKnowledge())

    knowledge.ingest_url("http://example.com/page", max_depth=3, max_links=5)

    assert len(fake.insert_calls) == 1
    reader = fake.insert_calls[0]["reader"]
    assert isinstance(reader, WebsiteReader)
    assert reader.max_depth == 3
    assert reader.max_links == 5


def test_search_maps_documents_to_result_dicts(monkeypatch):
    docs = [
        Document(
            content="first chunk",
            name="Page One",
            meta_data={"url": "http://example.com/a", "similarity_score": 0.91},
        ),
        Document(
            content="second chunk",
            name="Page Two",
            meta_data={"url": "http://example.com/b", "similarity_score": 0.42},
        ),
    ]
    fake = _patch_get_rag(monkeypatch, FakeKnowledge(docs))

    results = knowledge.search("q", k=2)

    assert fake.search_calls == [{"query": "q", "max_results": 2}]
    assert results == [
        {
            "content": "first chunk",
            "name": "Page One",
            "source_url": "http://example.com/a",
            "similarity": 0.91,
        },
        {
            "content": "second chunk",
            "name": "Page Two",
            "source_url": "http://example.com/b",
            "similarity": 0.42,
        },
    ]


def test_search_defaults_k_to_five_and_handles_missing_metadata(monkeypatch):
    fake = _patch_get_rag(monkeypatch, FakeKnowledge([Document(content="c", name="n", meta_data={})]))

    results = knowledge.search("q")

    assert fake.search_calls == [{"query": "q", "max_results": 5}]
    assert results == [{"content": "c", "name": "n", "source_url": None, "similarity": None}]


def test_ingest_url_raises_when_content_failed(monkeypatch):
    url = "http://example.com/broken"
    failed = Content(name=url, status=ContentStatus.FAILED, status_message="host TLS failure")
    fake = _patch_get_rag(monkeypatch, FakeKnowledge(contents=[failed]))

    with pytest.raises(RuntimeError, match="host TLS failure"):
        knowledge.ingest_url(url)


def test_reset_removes_all_content(monkeypatch):
    fake = _patch_get_rag(monkeypatch, FakeKnowledge())

    knowledge.reset()

    assert fake.remove_all_content_calls == 1

"""
Local-oMLX RAG base
===================

A standalone, pgvector-backed knowledge base for Coda. Content ingested here is
chunked, embedded locally by the oMLX-served BGE-M3 model (wired through
``db.create_knowledge``), and stored in the ``ai.coda_rag`` table. Search returns
raw chunks plus their source URLs.

This module is intentionally self-contained: it is NOT wired into the agent team
or any ``coda.agents`` tool. Importing it is side-effect free — the underlying
``Knowledge`` instance (and therefore any Postgres connection) is only created on
first use via :func:`get_rag`.
"""

from functools import lru_cache
from typing import Any

from agno.knowledge import Knowledge
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.content import ContentStatus
from agno.knowledge.reader.website_reader import WebsiteReader

from db import create_knowledge

RAG_NAME = "Coda RAG"
RAG_TABLE = "coda_rag"


@lru_cache(maxsize=1)
def get_rag() -> Knowledge:
    """Return the shared RAG ``Knowledge`` instance, creating it on first call.

    Lazy and memoized so that importing this module never touches Postgres.
    """
    return create_knowledge(RAG_NAME, RAG_TABLE)


def ingest_url(
    url: str,
    *,
    max_depth: int = 1,
    max_links: int = 1,
    chunk_size: int = 5000,
) -> None:
    """Ingest a URL into the RAG knowledge base.

    Defaults read a single page (``max_depth=1``, ``max_links=1``) so a plain URL
    stores just that page; raise both to allow bounded crawling.

    Args:
        url: Page URL to read and index.
        max_depth: Maximum link depth to follow. Defaults to 1 (page only).
        max_links: Maximum number of pages to read. Defaults to 1 (page only).
        chunk_size: Fixed chunk size, in characters, used by the reader.

    Raises:
        RuntimeError: If the fetch/embed fails. agno's ``Knowledge.insert`` does not
            raise on a failed load — it persists a ``Content`` row marked
            ``ContentStatus.FAILED`` and returns. This wrapper reads that stored
            status back and raises so the failure is not silently swallowed.
    """
    reader = WebsiteReader(
        max_depth=max_depth,
        max_links=max_links,
        chunking_strategy=FixedSizeChunking(chunk_size=chunk_size),
    )
    get_rag().insert(name=url, url=url, reader=reader, upsert=True)

    contents, _ = get_rag().get_content()
    failed = next(
        (content for content in contents if content.name == url and content.status == ContentStatus.FAILED),
        None,
    )
    if failed is not None:
        raise RuntimeError(f"Failed to ingest {url}: {failed.status_message or 'unknown error'}")


def search(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Search the RAG knowledge base and return plain result dicts.

    Args:
        query: Natural-language search query.
        k: Maximum number of results to return.

    Returns:
        One dict per matching chunk with ``content``, ``name``, ``source_url``,
        and ``similarity`` keys.
    """
    results: list[dict[str, Any]] = []
    for doc in get_rag().search(query, max_results=k):
        meta = doc.meta_data or {}
        results.append(
            {
                "content": doc.content,
                "name": doc.name,
                "source_url": meta.get("url"),
                "similarity": meta.get("similarity_score"),
            }
        )
    return results


def reset() -> None:
    """Remove all content from the RAG knowledge base."""
    get_rag().remove_all_content()

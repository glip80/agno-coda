"""
Coda RAG
========

Standalone local-oMLX RAG package. See :mod:`coda.rag.knowledge` for the
pgvector-backed knowledge base operations.
"""

from coda.rag.knowledge import (
    RAG_NAME,
    RAG_TABLE,
    get_rag,
    ingest_url,
    reset,
    search,
)

__all__ = [
    "RAG_NAME",
    "RAG_TABLE",
    "get_rag",
    "ingest_url",
    "reset",
    "search",
]

"""
Database Session
================

PostgreSQL database connection for AgentOS.
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder
from agno.vectordb.pgvector import PgVector, SearchType

from db.url import db_url

DB_ID = "coda-db"

DEFAULT_EMBEDDING_MODEL_ID = "mlx-community--bge-m3-mlx-fp16"
DEFAULT_EMBEDDING_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_EMBEDDING_DIMENSIONS = 1024


def _embedding_base_url() -> str:
    """Resolve the local OpenAI-compatible embedding base URL.

    Mirrors ``coda.settings._base_url``: reads ``EMBEDDING_BASE_URL``, strips a
    trailing slash, and normalizes a ``.../v1/models`` endpoint to its API base.

    Returns:
        The API base URL the SDK expects (e.g. ``http://127.0.0.1:8000/v1``).
    """
    url = (getenv("EMBEDDING_BASE_URL") or DEFAULT_EMBEDDING_BASE_URL).rstrip("/")
    return url.removesuffix("/models")


def _local_embedder() -> OpenAILikeEmbedder:
    """Build a local OpenAI-compatible embedder (BGE-M3, 1024 dims).

    Returns:
        OpenAILikeEmbedder pointed at the configured local embedding server.
    """
    return OpenAILikeEmbedder(
        id=getenv("EMBEDDING_MODEL_ID") or DEFAULT_EMBEDDING_MODEL_ID,
        base_url=_embedding_base_url(),
        api_key=getenv("EMBEDDING_API_KEY") or "not-needed",
        dimensions=int(getenv("EMBEDDING_DIMENSIONS") or DEFAULT_EMBEDDING_DIMENSIONS),
    )


def get_postgres_db(contents_table: str | None = None) -> PostgresDb:
    """Create a PostgresDb instance.

    Args:
        contents_table: Optional table name for storing knowledge contents.

    Returns:
        Configured PostgresDb instance.
    """
    if contents_table is not None:
        return PostgresDb(id=DB_ID, db_url=db_url, knowledge_table=contents_table)
    return PostgresDb(id=DB_ID, db_url=db_url)


def create_knowledge(name: str, table_name: str) -> Knowledge:
    """Create a Knowledge instance with PgVector hybrid search.

    Args:
        name: Display name for the knowledge base.
        table_name: PostgreSQL table name for vector storage.

    Returns:
        Configured Knowledge instance.
    """
    return Knowledge(
        name=name,
        vector_db=PgVector(
            db_url=db_url,
            table_name=table_name,
            search_type=SearchType.hybrid,
            embedder=_local_embedder(),
        ),
        contents_db=get_postgres_db(contents_table=f"{table_name}_contents"),
    )

#!/usr/bin/env python
"""Migrate the Coda learnings vector table to the local embedder dimension.

The learnings knowledge base was originally created with OpenAI's
``text-embedding-3-small`` embedder (1536 dimensions). Coda now uses a local
BGE-M3 embedder (1024 dimensions), so the existing ``ai.coda_learnings`` table
must be dropped and recreated at 1024 to match.

This migration is destructive and idempotent: existing learnings vector rows are
lost (owner decision Q2), and re-running always leaves a ``vector(1024)`` table.
It never touches ``coda_rag`` or any AgentOS session/memory/learnings table.

Usage:
    source .venv/bin/activate
    python scripts/migrate_embedding_dim.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/migrate_embedding_dim.py` from the repo root
# (Python puts the script's directory on sys.path, not the current directory).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text

from db import create_knowledge
from db.url import db_url

SCHEMA = "ai"
VECTOR_TABLE = "coda_learnings"
CONTENTS_TABLE = "coda_learnings_contents"
KB_NAME = "Coda Learnings"
EXPECTED_DIM = 1024


def _embedding_column_type(conn) -> str | None:
    """Return the SQL type of ``SCHEMA.VECTOR_TABLE.embedding`` (or None)."""
    return conn.execute(
        text(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class t ON a.attrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = :schema
              AND t.relname = :table
              AND a.attname = 'embedding'
            """
        ),
        {"schema": SCHEMA, "table": VECTOR_TABLE},
    ).scalar()


def main() -> int:
    """Run the destructive, idempotent dimension migration.

    Returns:
        Process exit code: 0 on success, 1 if the post-migration state is wrong.
    """
    engine = create_engine(db_url)

    before = None
    with engine.connect() as conn:
        before = _embedding_column_type(conn)
    print(f"[before] {SCHEMA}.{VECTOR_TABLE}.embedding = {before}")

    # Drop the stale vector table. CASCADE clears its dependent indexes/FKs.
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.{VECTOR_TABLE} CASCADE;"))
    print(f"[drop]   DROP TABLE IF EXISTS {SCHEMA}.{VECTOR_TABLE} CASCADE")

    # Clear the knowledge-contents table only if it exists (guarded).
    if inspect(engine).has_table(CONTENTS_TABLE, schema=SCHEMA):
        with engine.begin() as conn:
            deleted = conn.execute(text(f"DELETE FROM {SCHEMA}.{CONTENTS_TABLE};")).rowcount
        print(f"[clear]  DELETE FROM {SCHEMA}.{CONTENTS_TABLE} -> {deleted} row(s)")
    else:
        print(f"[clear]  {SCHEMA}.{CONTENTS_TABLE} does not exist; skipped")

    # Recreate the KB at the local embedder dimension (1024).
    knowledge = create_knowledge(KB_NAME, VECTOR_TABLE)
    vector_db = knowledge.vector_db
    assert vector_db is not None
    dim = vector_db.dimensions
    print(f"[create] create_knowledge({KB_NAME!r}, {VECTOR_TABLE!r}) -> dimensions={dim}")

    # Read the column type back from the database as evidence.
    after = None
    with engine.connect() as conn:
        after = _embedding_column_type(conn)
    print(f"[after]  {SCHEMA}.{VECTOR_TABLE}.embedding = {after}")

    expected_type = f"vector({EXPECTED_DIM})"
    if after != expected_type:
        print(f"[FAIL] expected {expected_type}, got {after}", file=sys.stderr)
        return 1
    if dim != EXPECTED_DIM:
        print(f"[FAIL] knowledge.vector_db.dimensions={dim}, expected {EXPECTED_DIM}", file=sys.stderr)
        return 1

    print(f"[ok]     migrated {SCHEMA}.{VECTOR_TABLE} to {expected_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

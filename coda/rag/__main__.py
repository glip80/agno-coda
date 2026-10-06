"""Command-line interface for the standalone Coda RAG knowledge base.

Usage::

    python -m coda.rag ingest <url> [--max-depth N] [--max-links N] [--chunk-size N]
    python -m coda.rag search <query> [--k N]
    python -m coda.rag list
    python -m coda.rag reset

A thin stdlib-``argparse`` wrapper over :mod:`coda.rag.knowledge`; no business
logic lives here beyond argument parsing and human-readable output.
"""

import argparse
import sys

from coda.rag.knowledge import (
    RAG_NAME,
    RAG_TABLE,
    get_rag,
    ingest_url,
    reset,
    search,
)

_CONTENT_PREVIEW_CHARS = 500


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Read and index a URL, printing a one-line confirmation."""
    try:
        ingest_url(
            args.url,
            max_depth=args.max_depth,
            max_links=args.max_links,
            chunk_size=args.chunk_size,
        )
    except Exception as exc:  # noqa: BLE001 - surface any fetch/embed failure
        print(f"error: failed to ingest {args.url}: {exc}", file=sys.stderr)
        return 1
    print(f"Ingested {args.url} into '{RAG_NAME}' ({RAG_TABLE})")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    """Search the knowledge base and print each hit with its source."""
    results = search(args.query, args.k)
    if not results:
        print("No results.")
        return 0
    for i, result in enumerate(results, start=1):
        content = result.get("content") or ""
        if len(content) > _CONTENT_PREVIEW_CHARS:
            content = content[:_CONTENT_PREVIEW_CHARS] + "..."
        print(f"#{i} [{result.get('similarity')}] {result.get('source_url')}")
        print(content)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List the contents currently stored in the knowledge base."""
    contents, count = get_rag().get_content()
    print(f"{count} content item(s) in '{RAG_NAME}' ({RAG_TABLE}):")
    for content in contents:
        print(f"- {content.name} (id={content.id}, status={content.status})")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    """Remove all content from the knowledge base."""
    reset()
    print(f"Cleared '{RAG_NAME}' ({RAG_TABLE}).")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m coda.rag",
        description="Manage the standalone Coda RAG knowledge base.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser("ingest", help="Ingest a URL into the RAG base.")
    p_ingest.add_argument("url", help="Page URL to read and index.")
    p_ingest.add_argument("--max-depth", type=int, default=1, help="Maximum link depth to follow.")
    p_ingest.add_argument("--max-links", type=int, default=1, help="Maximum number of pages to read.")
    p_ingest.add_argument("--chunk-size", type=int, default=5000, help="Fixed chunk size in characters.")
    p_ingest.set_defaults(func=_cmd_ingest)

    p_search = subparsers.add_parser("search", help="Search the RAG base.")
    p_search.add_argument("query", help="Natural-language search query.")
    p_search.add_argument("--k", type=int, default=5, help="Maximum number of results to return.")
    p_search.set_defaults(func=_cmd_search)

    p_list = subparsers.add_parser("list", help="List contents in the RAG base.")
    p_list.set_defaults(func=_cmd_list)

    p_reset = subparsers.add_parser("reset", help="Remove all content from the RAG base.")
    p_reset.set_defaults(func=_cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the selected subcommand.

    Args:
        argv: Argument list to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` on success, non-zero on failure).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

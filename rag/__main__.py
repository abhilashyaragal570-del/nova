"""Command line for the document index: python -m rag <command>."""
import argparse
import sys

from rag.embedder import EmbedError, GeminiEmbedder
from rag.index import RagIndexError
from rag.index_factory import create_document_index
from rag.ingest import IngestError, add_file

SNIPPET_CHARS = 200


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rag", description="Manage the documents Nova can search."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add", help="add or replace .txt and .md files")
    p.add_argument("files", nargs="+")
    sub.add_parser("list", help="show the indexed documents")
    p = sub.add_parser("remove", help="remove one document by file name")
    p.add_argument("source")
    sub.add_parser("clear", help="remove every document")
    p = sub.add_parser("search", help="find the passages that best match a question")
    p.add_argument("question", nargs="+")
    p.add_argument("--top", type=int, default=3)
    return parser


def cmd_add(args, index, embedder) -> int:
    if embedder is None:
        embedder = GeminiEmbedder()
    failed = False
    for name in args.files:
        try:
            result = add_file(name, index, embedder)
        except IngestError as e:
            print(f"Skipped {name}: {e}", file=sys.stderr)
            failed = True
            continue
        n = result["chunks"]
        print(f"Added {result['source']} ({n} chunk{'s' if n != 1 else ''})")
    return 1 if failed else 0


def cmd_list(args, index, embedder) -> int:
    docs = index.list_documents()
    if not docs:
        print("The index is empty. Add files with: python -m rag add FILE")
        return 0
    for d in docs:
        print(f"{d['source']}: {d['chunks']} chunks ({d['model']})")
    return 0


def cmd_remove(args, index, embedder) -> int:
    if index.remove_document(args.source):
        print(f"Removed {args.source}")
        return 0
    print(f"Not found: {args.source}", file=sys.stderr)
    return 1


def cmd_clear(args, index, embedder) -> int:
    print(f"Removed {index.clear()} document(s)")
    return 0


def cmd_search(args, index, embedder) -> int:
    if embedder is None:
        embedder = GeminiEmbedder()
    if not index.list_documents():
        print("The index is empty. Add files with: python -m rag add FILE")
        return 0
    vector = embedder.embed_query(" ".join(args.question))
    results = index.search(vector, embedder.signature, args.top)
    for i, r in enumerate(results, 1):
        snippet = " ".join(r["text"].split())[:SNIPPET_CHARS]
        print(f"{i}. {r['source']} (chunk {r['chunk']}, score {r['score']:.2f})")
        print(f"   {snippet}")
    return 0


COMMANDS = {
    "add": cmd_add,
    "list": cmd_list,
    "remove": cmd_remove,
    "clear": cmd_clear,
    "search": cmd_search,
}


def main(argv=None, index=None, embedder=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if index is None:
            index = create_document_index()
        return COMMANDS[args.command](args, index, embedder)
    except (RagIndexError, EmbedError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
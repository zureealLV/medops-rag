"""Export one SQLite table to UTF-8 JSONL for reviewed MedOps ingestion."""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
from pathlib import Path


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"$base64": base64.b64encode(value).decode("ascii")}
    return value


def export_table(
    database: Path,
    table: str,
    output: Path,
    *,
    columns: list[str] | None = None,
    limit: int = 10_000,
) -> int:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        }
        if table not in tables:
            raise ValueError(f"table or view not found: {table}")
        available = [
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote_identifier(table)})")
        ]
        selected = columns or available
        missing = [name for name in selected if name not in available]
        if missing:
            raise ValueError(f"columns not found: {', '.join(missing)}")
        projection = ", ".join(_quote_identifier(name) for name in selected)
        query = f"SELECT {projection} FROM {_quote_identifier(table)} LIMIT ?"
        rows = connection.execute(query, (limit,)).fetchall()
    finally:
        connection.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            payload = {name: _json_value(row[name]) for name in selected}
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("table")
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", nargs="+")
    parser.add_argument("--limit", type=int, default=10_000)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100_000:
        parser.error("--limit must be between 1 and 100000")
    count = export_table(
        args.database,
        args.table,
        args.output,
        columns=args.columns,
        limit=args.limit,
    )
    print(f"exported_rows={count} output={args.output}")
    print("Review and de-identify the JSONL before uploading it to MedOps RAG.")


if __name__ == "__main__":
    main()

"""Read-only SQLite export adapter tests."""

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.export_sqlite_table import export_table


def test_export_sqlite_table_to_ingestible_jsonl(tmp_path: Path):
    database = tmp_path / "external.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE devices (asset_id TEXT, device_type TEXT, status TEXT)")
    connection.execute(
        "INSERT INTO devices VALUES (?, ?, ?)",
        ("DEV-100", "infusion pump", "inspection_due"),
    )
    connection.commit()
    connection.close()

    output = tmp_path / "devices.jsonl"
    count = export_table(database, "devices", output, columns=["asset_id", "status"])

    assert count == 1
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "asset_id": "DEV-100",
        "status": "inspection_due",
    }


def test_export_rejects_unknown_table_and_column(tmp_path: Path):
    database = tmp_path / "external.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE devices (asset_id TEXT)")
    connection.close()

    with pytest.raises(ValueError, match="table or view not found"):
        export_table(database, "missing", tmp_path / "missing.jsonl")
    with pytest.raises(ValueError, match="columns not found"):
        export_table(database, "devices", tmp_path / "missing-column.jsonl", columns=["secret"])

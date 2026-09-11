"""Backup-first V1-to-V2 database upgrade and explicit rollback CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import Settings
from app.migrations import restore_database, upgrade_database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("--backup", type=Path)
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    database = Settings.from_env().database_path

    if args.command == "upgrade":
        backup, digest = upgrade_database(database, args.backup)
        print(f"database={database}")
        print(f"backup={backup if backup else 'not-required-new-database'}")
        print(f"upgraded_sha256={digest}")
        return 0
    digest = restore_database(database, args.backup)
    print(f"database={database}")
    print(f"restored_from={args.backup}")
    print(f"restored_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

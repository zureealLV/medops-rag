# V1 to V2 Migration and Rollback

Status: exact V1 schema fixture upgrade and rollback are covered by
`tests/test_v1_upgrade_rollback.py`.

## What the upgrade does

V2 keeps the original users, knowledge bases, documents, chunks, audit logs and request metrics in place.
Initialization adds document provenance, normalized elements/artifacts, parent/child chunks, job queues,
hashed credentials, pipeline metrics and tenant/actor-scoped agent control checkpoints. Legacy fixed chunks are copied into one parent and one compatible
child so they remain searchable without rewriting their text or embeddings.

Successful initialization records both `PRAGMA user_version = 4` and
`schema_metadata['schema_version'] = '4'`. Schema 3 added the trigger-maintained
FTS5 trigram candidate index; schema 4 adds append-only bounded agent control checkpoints.
SQLite builds without FTS5 still retain the automatic full-scan fallback. The upgrade is idempotent.

## Backup-first upgrade

Stop all writers before migrating. For Compose:

```powershell
docker compose down
$env:DATABASE_URL = "sqlite:///./data/runtime/medops.db"
.\.venv\Scripts\python.exe .\scripts\migrate_database.py upgrade
```

If the database already exists, the command uses SQLite's online backup API to create a timestamped
`medops.db.pre-v2.<UTC>.bak`, validates it with `PRAGMA integrity_check`, applies the additive migration,
checks the upgraded database and prints both paths plus the resulting SHA-256. Supply a controlled path with
`--backup` if required by an operations runbook.

Take an external copy of the backup before restarting production writers. A file beside the live database is
rollback convenience, not a disaster-recovery policy.

## Verify

```powershell
.\.venv\Scripts\python.exe -c "import os,sqlite3; from app.config import Settings; p=Settings.from_env().database_path; c=sqlite3.connect(p); print(c.execute('pragma integrity_check').fetchone(), c.execute('pragma user_version').fetchone())"
.\scripts\run_tests.ps1
```

Then run the normal API/worker smoke against synthetic data. Check legacy document counts, a known legacy
search, queue health and error metrics before admitting writes.

## Roll back

Rollback replaces the complete logical SQLite database with the validated backup. It intentionally removes
all V2 writes made after the backup.

```powershell
docker compose down
$env:DATABASE_URL = "sqlite:///./data/runtime/medops.db"
.\.venv\Scripts\python.exe .\scripts\migrate_database.py rollback `
  --backup .\data\runtime\medops.db.pre-v2.<UTC>.bak
```

The implementation uses SQLite's backup API rather than copying an open WAL database. Still stop API and
worker writers first. After rollback, start the V1 application image/code, verify `integrity_check`, row counts
and a known query, and archive the failed V2 database plus logs for diagnosis.

## Test evidence and limits

The exact V1 schema from commit `dce760b` is populated with a user, knowledge base, document, chunk, audit
event and request metric. The test upgrades it, checks every legacy row, confirms parent/child backfill and
schema version, creates V2-only data, restores the backup, and proves V2 tables/data disappear while the V1
document remains.

This is a single-host SQLite procedure. It does not migrate an external vector database or object store.
Those systems need coordinated snapshots and a separate compatibility plan before changing the selected
deployment profile.

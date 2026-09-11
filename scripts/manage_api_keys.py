"""Create and revoke API keys without exposing an HTTP bootstrap endpoint."""

from __future__ import annotations

import argparse
import sys

from app.config import Settings
from app.db import initialize
from app.repositories.api_credentials import VALID_ROLES, create_credential, revoke_credential
from app.security.tenant import TENANT_PATTERN


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create an API key and print it once")
    create.add_argument("--tenant", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    revoke = subparsers.add_parser("revoke", help="revoke an API key by credential id")
    revoke.add_argument("--tenant", required=True)
    revoke.add_argument("--id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not TENANT_PATTERN.fullmatch(args.tenant):
        print("error: --tenant must match the API tenant identifier format", file=sys.stderr)
        return 2
    settings = Settings.from_env()
    initialize(settings.database_path)
    if args.command == "create":
        identity, token = create_credential(
            settings.database_path,
            tenant_id=args.tenant,
            name=args.name,
            role=args.role,
        )
        print(f"credential_id={identity.credential_id}")
        print(f"api_key={token}")
        print("Store this key now. The plaintext value cannot be recovered.")
        return 0
    revoked = revoke_credential(
        settings.database_path,
        tenant_id=args.tenant,
        credential_id=args.id,
    )
    print("revoked" if revoked else "not_found")
    return 0 if revoked else 1


if __name__ == "__main__":
    raise SystemExit(main())

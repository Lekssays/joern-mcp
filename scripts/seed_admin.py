#!/usr/bin/env python3
"""
CLI script to seed an admin or tenant user in CodeBadger (Phase 8).
Usage:
    python3 scripts/seed_admin.py --username admin --password secret --tenant-id admin --roles admin
"""

import argparse
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.auth_service import AuthService
from src.utils.postgres_db_manager import PostgresDBManager


def main():
    parser = argparse.ArgumentParser(description="Seed CodeBadger admin / tenant user.")
    parser.add_argument("--username", default="admin", help="Username for the account")
    parser.add_argument("--password", default="admin123", help="Password for the account")
    parser.add_argument("--tenant-id", default="admin", help="Tenant ID associated with account")
    parser.add_argument("--roles", default="admin", help="Comma-separated roles, e.g. 'admin' or 'user'")
    parser.add_argument("--db-url", default=None, help="Postgres / SQLite database URL")

    args = parser.parse_args()

    db_url = args.db_url or os.getenv("DATABASE_URL")
    db_mgr = None
    if db_url:
        try:
            db_mgr = PostgresDBManager(db_url)
        except Exception as e:
            print(f"Warning: Failed to connect to DB ({e}), using in-memory mode.", file=sys.stderr)

    auth = AuthService(db=db_mgr)
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    user = auth.seed_user(
        username=args.username,
        password=args.password,
        tenant_id=args.tenant_id,
        roles=roles,
    )
    print(f"Successfully seeded user: {user['username']} (id: {user['id']}, tenant: {user['tenant_id']}, roles: {user['roles']})")


if __name__ == "__main__":
    main()

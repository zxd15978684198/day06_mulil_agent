"""add users.password_hash

Revision ID: 0002_add_password_hash
Revises: 0001_baseline
Create Date: 2026-10-14

薄壳：SQL 本体在 src/migrations/sql/V001__add_users_password_hash.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

# versions/ → migrations/ → src/
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from migrations.sql_runner import run_sql  # noqa: E402

revision = "0002_add_password_hash"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql("V001__add_users_password_hash.sql")


def downgrade() -> None:
    run_sql("V001__add_users_password_hash.down.sql")

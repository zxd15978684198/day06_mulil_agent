"""seed login password hashes（10 个教学账号）

Revision ID: 0003_seed_login_hashes
Revises: 0002_add_password_hash
Create Date: 2026-10-14

薄壳：SQL 本体在 src/migrations/sql/V002__seed_login_password_hashes.sql
"""

from __future__ import annotations

import sys
from pathlib import Path

# versions/ → migrations/ → src/
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from migrations.sql_runner import run_sql  # noqa: E402

revision = "0003_seed_login_hashes"
down_revision = "0002_add_password_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_sql("V002__seed_login_password_hashes.sql")


def downgrade() -> None:
    run_sql("V002__seed_login_password_hashes.down.sql")

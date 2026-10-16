"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

⚠️ 本文件是**薄壳**，不是 SQL 本体。
   真正的 SQL 在 src/migrations/sql/ 下（唯一事实源）。

   把下面 upgrade() / downgrade() 里的 TODO 换成实际文件名，例如：

       def upgrade() -> None:
           run_sql("V001__add_users_password_hash.sql")

       def downgrade() -> None:
           run_sql("V001__add_users_password_hash.down.sql")

   没有回滚方案就把 downgrade 写成 raise NotImplementedError(...)，
   不要留 TODO —— 免得真需要回滚时才发现没写。
"""
from __future__ import annotations

import sys
from pathlib import Path

# versions/ → migrations/ → src/
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from migrations.sql_runner import run_sql  # noqa: E402

${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    run_sql("TODO__V001__change.sql")


def downgrade() -> None:
    run_sql("TODO__V001__change.down.sql")

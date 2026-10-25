"""baseline: day05 schema（V000）

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-10-14

这个版本**故意什么都不做**（upgrade/downgrade 都是 pass）。

它存在的唯一目的：把"库里现在就已经是 day05 结构 + day05 数据"这件事
记进账本，这样后面 V001/V002 才有起点可比。

它不是"从零建库"的脚本 —— 建库脚本是 src/migrations/sql/day05_mysql_setup.sql
（整库快照，包含 CREATE DATABASE / CREATE USER / GRANT，属于管理员级操作，
不归 alembic 管）。

用法（老库，即库已经是 day05 状态）：
    uv run alembic stamp 0001_baseline     # 只写账本，不执行任何 DDL
    uv run alembic upgrade head            # 再跑 V001、V002

⚠️ 不要在这里写 CREATE TABLE —— 表已经存在，会撞
   (1050, "Table 'users' already exists")。
"""

from __future__ import annotations

import sys
from pathlib import Path

# versions/ → migrations/ → src/
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from migrations.sql_runner import run_sql  # noqa: E402, F401  （后续版本会用到）

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """基线的结构就是 day05 脚本建出来的样子，这里无事可做。"""
    pass


def downgrade() -> None:
    """降到基线不需要撤销动作；真要清库请用 day05/day06 脚本重建。"""
    pass

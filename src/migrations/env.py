"""Alembic 运行环境。

入口：仓库根的 alembic.ini（`script_location = %(here)s/src/migrations`）。

三条设计决定，都有理由：

1. **连接串不写在 alembic.ini 里**。从 `.env` / 环境变量读，一是密码不进版本库，
   二是保证迁移和运行期用的是同一个 DSN，不会出现"迁移连了 A 库、应用连了 B 库"。
   优先级：`MIGRATION_DATABASE_URL` > `DATABASE_URL` > 应用模块里的值。
   留这个口子的用途：等哪天应用切回最小权限账号（agent_app 只有 DML），
   可以只把 DDL 权限交给迁移账号，而不用改代码。

2. **必须 import models**。不 import 就没有表进 `Base.metadata`，
   `alembic check` 会把库里所有表都报成"多出来的"。

3. **compare_type 保持默认关闭**。本项目是 SQL-first（手写 SQL + 薄壳），
   `alembic check` 只承担一件事：发现"模型多了/少了列或表"这类**结构性**漂移。
   一旦打开 compare_type，MySQL 会把 Boolean↔TINYINT(1)、JSON、String 长度
   全报成差异，噪声会淹没真信号。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- 先把 src/ 放上 sys.path，再 import 本项目的模块 -------------------------
# alembic.ini 的 prepend_sys_path 做了同样的事；这里再兜一次，
# 以便有人跳过 ini 直接调用，或将来 env.py 被别处 import。
SRC_DIR = Path(__file__).resolve().parent.parent  # → <仓库根>/src
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from personal_assistant.paths import ENV_PATH  # noqa: E402

# 必须在读 DATABASE_URL 之前执行（uv run 自己也会读 .env，这里是幂等的双保险）
load_dotenv(ENV_PATH, override=False)

from personal_assistant.database import Base  # noqa: E402
import personal_assistant.models  # noqa: E402,F401  —— 不 import 就没有表可比

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """本次迁移要连的库。"""
    url = (
        os.getenv("MIGRATION_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()

    if not url:  # 兜底：应用模块自己算出来的值
        from personal_assistant.database import DATABASE_URL as app_url

        url = (app_url or "").strip()

    if not url:
        raise RuntimeError(
            "没有数据库连接串。请确认 .env 里配了 DATABASE_URL"
            f"（期望位置：{ENV_PATH}），或为本次迁移临时设置 MIGRATION_DATABASE_URL。"
        )
    return url


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`：只把 SQL 打到标准输出，不连库。

    用来在真正执行前审 SQL —— 尤其是手写 SQL 的项目，这一步是主要的复核关口。
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """真正连库执行。"""
    section = config.get_section(config.config_ini_section, {})
    # configparser 会把 `%` 当插值转义符；DSN 里带 %（URL 编码过的密码）要还原成 %%。
    section["sqlalchemy.url"] = _database_url().replace("%", "%%")

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

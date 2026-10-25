"""一次性数据库初始化（db-init 服务跑完即退）。做两件事：

**1. 建一个容器网络能用的应用账号**

`src/migrations/sql/day06_mysql_setup.sql` 建的是 `'agent_app'@'127.0.0.1'` ——
只允许本机连。容器里应用是从另一个 IP 连进来的，必须再有一条 `'agent_app'@'%'`。
（MySQL 账号按 host 做最具体匹配，`127.0.0.1` 与 `%` 两条可以共存，互不影响。）

密码不能写死在要提交进 git 的 SQL 文件里，所以放在这里用环境变量拼。

**2. 登记 alembic 账本**

表结构已经由那份 SQL 建好了，但库里还没有 `alembic_version` 表。这时该做的是
`alembic stamp head`（只写账本、不执行任何 DDL）；直接 `upgrade` 会去建已经存在
的表，报 `(1050, "Table 'users' already exists")`。这正是
`src/migrations/README.md` 里「首次：登记基线」那一节说的顺序。

账本已经存在时（第二次以后启动）才走 `upgrade head`，把新加的迁移补上。

需要 DDL 权限，所以本脚本用管理员账号；应用容器只拿到只有 DML 权限的 `agent_app`。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from wait_for_mysql import (
    wait_for_db,  # 同目录，运行本脚本时 sys.path[0] 就是 /app/docker
)

PROJECT_ROOT = Path("/app")
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

# 标识符只允许这些字符：它们要拼进 DDL 字符串（CREATE USER / GRANT 的参数位
# 不支持绑定变量），先挡住引号与反引号，避免把 SQL 拼坏
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")

# 口令里**不能**出现的字符：它们要么会把连接串的语法拆开（@ : / ? #），
# 要么会踩到 src/migrations/env.py:107 那句 `.replace("%", "%%")`
# （百分号被加倍后 SQLAlchemy 解出来的口令就错了，报 Access denied）。
# 详见本文件 _check_url_safe 的说明。
_URL_UNSAFE = set("@:/?#%[] \t\r\n")

DML_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def _env(name: str, default: str | None = None, *, required: bool = True) -> str:
    value = (os.getenv(name) or "").strip() or (default or "")
    if required and not value:
        raise SystemExit(f"[bootstrap] 环境变量 {name} 未设置")
    return value


def _identifier(name: str, var: str) -> str:
    if not _IDENTIFIER.match(name):
        raise SystemExit(f"[bootstrap] {var}={name!r} 只允许字母、数字、下划线")
    return name


def _quote_literal(value: str) -> str:
    """把值转成 MySQL 字符串字面量（DDL 里没法用绑定变量）。"""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _check_url_safe(value: str, var: str) -> str:
    """口令直接拼进连接串，先把会拆坏语法的字符挡掉。

    **为什么不百分号编码**（原本用的是 `quote_plus`）：
    `quote_plus("ChangeMe-Root!")` 会产出 `ChangeMe-Root%21`，而
    `src/migrations/env.py:107` 有一句

        section["sqlalchemy.url"] = _database_url().replace("%", "%%")

    本意是给 configparser 的插值转义，但 `engine_from_config` 是直接读这个 dict 的，
    根本不会再把 `%%` 还原 —— 于是 SQLAlchemy 拿到的口令是 `ChangeMe-Root%%21`，
    报 `Access denied for user 'root'@...`。

    本机口令是纯数字，不含 `%`，这句 replace 是空操作，所以这个坑一直没暴露；
    容器里口令一带 `!` 就必现。与其去改他们的 env.py，不如这边不做编码、
    并明确限制口令字符 —— 反正 `secrets.token_urlsafe()` 产出的就是安全字符集。
    """
    # `<随机口令>` 这种占位符不是空串，compose 的 `${VAR:-默认值}` 只在**空串**时
    # 才兜底，所以照抄 .env.example 不改的话，口令会真的变成字面量 "<随机口令>"。
    # 这与 auth.py 对 JWT_SECRET 的检查是同一个约定（那里的判据是 startswith("<")）。
    if value.startswith("<") and value.endswith(">"):
        raise SystemExit(
            f"[bootstrap] {var} 还是 .env.example 里的占位符 {value!r}，请改成真实口令。"
        )

    bad = sorted(set(value) & _URL_UNSAFE)
    if bad:
        raise SystemExit(
            f"[bootstrap] {var} 含有不能直接放进数据库连接串的字符：{bad}\n"
            "            请改用字母数字组合，例如：\n"
            '              python -c "import secrets; print(secrets.token_urlsafe(24))"\n'
            "            token_urlsafe 只会产生 A-Za-z0-9_- ，一定安全。"
        )
    return value


def _dsn(user: str, password: str, host: str, port: str, database: str | None) -> str:
    auth = f"{user}:{password}"
    tail = f"/{database}" if database else "/"
    return f"mysql+pymysql://{auth}@{host}:{port}{tail}?charset=utf8mb4"


def _grant_app_account(
    server_url: str, database: str, user: str, password: str
) -> None:
    """建/更新 `user`@'%' 并只授予 DML 权限。"""
    engine = create_engine(server_url, isolation_level="AUTOCOMMIT")
    statements = [
        f"CREATE DATABASE IF NOT EXISTS `{database}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
        f"CREATE USER IF NOT EXISTS {_quote_literal(user)}@'%' "
        f"IDENTIFIED BY {_quote_literal(password)}",
        # 卷已存在时账号可能是上一版密码建的 → 对齐到当前配置
        f"ALTER USER {_quote_literal(user)}@'%' "
        f"IDENTIFIED BY {_quote_literal(password)}",
        f"GRANT {DML_PRIVILEGES} ON `{database}`.* TO {_quote_literal(user)}@'%'",
        "FLUSH PRIVILEGES",
    ]
    with engine.connect() as conn:
        for statement in statements:
            conn.execute(text(statement))
    engine.dispose()
    print(
        f"[bootstrap] 已确保账号 {user}@'%' 存在，权限：{DML_PRIVILEGES}（仅 {database}）"
    )


def _table_exists(server_url: str, database: str, table: str) -> bool:
    engine = create_engine(server_url)
    with engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": database, "table": table},
        ).scalar_one()
    engine.dispose()
    return bool(found)


def _run_alembic(*args: str, migration_url: str) -> None:
    """用同一个 venv 里的 alembic 执行迁移命令。"""
    executable = Path(sys.executable).parent / "alembic"
    env = {**os.environ, "MIGRATION_DATABASE_URL": migration_url}
    print(f"[bootstrap] alembic {' '.join(args)}")
    subprocess.run(
        [str(executable), *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
    )


def main() -> int:
    host = _env("MYSQL_HOST", "mysql")
    port = _env("MYSQL_PORT", "3306")
    database = _identifier(_env("MYSQL_DATABASE", "agent_service"), "MYSQL_DATABASE")
    app_user = _identifier(_env("MYSQL_APP_USER", "agent_app"), "MYSQL_APP_USER")
    # 应用口令也要在这里校验：它由 compose 拼进 app 容器的 DATABASE_URL，
    # 同样不能带 @ : / ? # % 这些字符
    app_password = _check_url_safe(_env("MYSQL_APP_PASSWORD"), "MYSQL_APP_PASSWORD")
    root_password = _check_url_safe(_env("MYSQL_ROOT_PASSWORD"), "MYSQL_ROOT_PASSWORD")

    server_url = _dsn("root", root_password, host, port, None)
    app_db_url = _dsn("root", root_password, host, port, database)

    # compose 已经用 service_healthy 挡了一道，这里再兜一次：脚本单独跑也不会翻车
    if not wait_for_db(server_url, timeout=float(os.getenv("DB_WAIT_TIMEOUT", "90"))):
        return 1

    _grant_app_account(server_url, database, app_user, app_password)

    if not _table_exists(server_url, database, "users"):
        # 表结构与种子数据来自 docker-entrypoint-initdb.d 里挂的那份 SQL，
        # 而它**只在数据卷首次初始化时**执行。卷是旧的、或者 SQL 没挂上，就会走到这里。
        print(
            f"[bootstrap] 警告：{database}.users 不存在 —— "
            "建表 SQL（day06_mysql_setup.sql）没有跑过。\n"
            "            数据卷可能是上一版留下的。清掉重来：\n"
            "              docker compose down -v && docker compose up -d",
            file=sys.stderr,
        )
        return 1

    if os.getenv("RUN_MIGRATIONS", "1") != "1":
        print("[bootstrap] RUN_MIGRATIONS != 1，跳过 alembic")
        return 0

    if not ALEMBIC_INI.exists():
        raise SystemExit(f"[bootstrap] 找不到 {ALEMBIC_INI}")

    if _table_exists(server_url, database, "alembic_version"):
        # 账本已在 → 把新加的迁移补上
        _run_alembic("upgrade", "head", migration_url=app_db_url)
    else:
        # 表已经由建表 SQL 建好 → 只记账，绝不执行 DDL（见模块文档）
        _run_alembic("stamp", "head", migration_url=app_db_url)

    print("[bootstrap] 数据库初始化完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

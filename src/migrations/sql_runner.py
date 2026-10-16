"""把手写 SQL 交给 alembic 执行的最小运行器。

分工（这套方案的核心）：

    src/migrations/sql/*.sql       ← **唯一事实源**：人写的 SQL，原样保存
    src/migrations/versions/*.py   ← 薄壳：只声明版本号 + 指向哪个 SQL 文件
    库里的 alembic_version 表       ← 账本：哪个版本跑过了

SQL 与账本分开，好处是 SQL 可以单独复制、给 DBA 审、离线执行，
而"跑没跑过 / 跑的什么顺序 / 怎么回滚"由 alembic 保证。

为什么不把整个 .sql 一次性丢给 execute()：
    pymysql 默认**不允许一次执行多条语句**（没开 CLIENT.MULTI_STATEMENTS），
    所以 "ALTER ...; ALTER ...;" 会直接报语法错 —— 必须按 ';' 拆开逐条下发。

为什么不支持 DELIMITER：
    存储过程 / 触发器 / 复合语句体需要客户端层的 DELIMITER 处理，
    这里不做（做了也容易在引号、注释、嵌套分号上出错）。
    这类改动请单独用 mysql 客户端执行，再用 `alembic stamp` 记账。
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parent / "sql"  # → src/migrations/sql

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def split_statements(sql: str) -> list[str]:
    """按分号拆语句，跳过注释与字符串字面量里的分号。"""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)

    statements: list[str] = []
    buf: list[str] = []
    quote: str | None = None

    for ch in sql:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            continue

        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


def run_sql(filename: str) -> None:
    """执行 src/migrations/sql/<filename>，按分号逐条下发。

    `filename` 只接受**文件名**，不接受路径 —— 防止薄壳里写错路径跑到 sql/ 之外。
    """
    if filename.startswith("TODO"):
        raise RuntimeError(
            f"这条迁移还是模板状态（{filename}）："
            f"请把它改成 {SQL_DIR} 下真实的 SQL 文件名。"
        )

    if Path(filename).name != filename:
        raise ValueError(
            f"只接受文件名，不接受路径：{filename!r}（SQL 一律放在 {SQL_DIR} 下）"
        )

    sql_file = SQL_DIR / filename
    if not sql_file.is_file():
        raise FileNotFoundError(
            f"找不到 SQL 文件：{sql_file}\n"
            f"（要么薄壳里引用的文件名写错了，要么文件还没复制进 {SQL_DIR}）"
        )

    statements = split_statements(sql_file.read_text(encoding="utf-8"))
    if not statements:
        raise RuntimeError(f"{sql_file} 里没有可执行的语句。")

    bind = op.get_bind()
    for index, statement in enumerate(statements, start=1):
        try:
            # exec_driver_sql：把语句原样下发给驱动。
            # ⚠️ 不要改用 sa.text() 或裸字符串 —— 裸字符串会被 alembic 转成 text()，
            #    于是 SQL 里的 ':' 会被当成绑定参数（DEFAULT 'a:b'、JSON 路径都会炸）。
            bind.exec_driver_sql(statement)
        except Exception as exc:  # noqa: BLE001 —— 包装成"第几条语句失败"再抛出
            raise RuntimeError(
                f"执行 {filename} 失败：第 {index}/{len(statements)} 条语句出错。\n"
                f"语句：{statement}\n"
                f"原始错误：{exc}"
            ) from exc

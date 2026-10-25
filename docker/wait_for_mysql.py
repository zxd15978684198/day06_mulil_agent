"""等 MySQL 能接受连接。app 容器与 db-init 容器共用。

连接参数从 `DATABASE_URL` 里取（交给 SQLAlchemy 的 make_url 解析），
所以这里不用重复拼 host/port/账号密码 —— 换个部署方式也不会漏改。

注意连的是 **server 而不是某个库**（`url.set(database=None)`）：
数据卷首次初始化时目标库可能还不存在，连库会直接失败。
"""

from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def wait_for_db(
    url: str,
    *,
    timeout: float = 90.0,
    interval: float = 2.0,
    label: str = "wait-for-db",
) -> bool:
    """反复尝试连到 MySQL server，成功返回 True，超时返回 False。"""
    target = make_url(url)
    # 目标库可能尚未创建 → 只连 server；AUTOCOMMIT 避免留下长事务
    engine = create_engine(
        target.set(database=None),
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )

    display = target.render_as_string(hide_password=True)
    deadline = time.monotonic() + timeout
    attempt = 0
    try:
        while True:
            attempt += 1
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001 —— 任何连不上的原因都算「还没起来」
                if time.monotonic() >= deadline:
                    print(
                        f"[{label}] {timeout:.0f}s 内连不上 {display}："
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    return False
                time.sleep(interval)
                continue

            print(f"[{label}] MySQL 就绪（第 {attempt} 次尝试，{display}）")
            return True
    finally:
        engine.dispose()


def main() -> int:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        print("[wait-for-db] 环境变量 DATABASE_URL 未设置", file=sys.stderr)
        return 1

    ok = wait_for_db(
        raw,
        timeout=float(os.getenv("DB_WAIT_TIMEOUT", "90")),
        interval=float(os.getenv("DB_WAIT_INTERVAL", "2")),
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

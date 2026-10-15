"""SQLAlchemy Engine、ORM 声明式基类与 Session 工厂。

与课件 §4.1 的**三处刻意差异**（本项目是 src 布局，见 `paths.py` 的决策 D4）：

1. **不自己用 `__file__` 拼路径**：`.env` 的唯一来源是 `paths.ENV_PATH`。
   旧版本写的是 `Path(__file__).resolve().parents[3]` —— 在 `src/personal_assistant/`
   下这个层级数正好多一层，指向 `E:\\projects\\.env`（不存在）。
   `load_dotenv` 对不存在的文件**不报错、只是什么都不加载**，于是表现为
   「请在 .env 中配置 DATABASE_URL」，而你去看 `.env` 明明写好了。
2. **配置错误抛 `RuntimeError`，不抛 `HTTPException`**：这个模块在 import 期执行，
   那时还没有请求上下文；抛 HTTP 异常会伪装成一个 400 响应。
3. **`Base` 定义在这里**（课件 §4.1 的形态），`models.py` 从本模块导入 ——
   避免两个文件各定义一个同名 `Base`（旧版本正是这样：`models.py` 自己定义了一个）。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .paths import ENV_PATH

# override=False：已存在的环境变量优先，CI / 容器注入的值不会被 .env 覆盖。
load_dotenv(ENV_PATH, override=False)

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        f"请在 {ENV_PATH} 中配置 DATABASE_URL"
        "（形如 mysql+pymysql://agent_app:<密码>@127.0.0.1:3306/agent_service?charset=utf8mb4）。"
        "库与账号由 scripts/day05_mysql_setup.sql 一次性初始化。"
    )


class Base(DeclarativeBase):
    """所有 ORM 模型继承的声明式基类。"""


# Engine 管理方言与连接池；pool_pre_ping 让取出的连接先探活再交付。
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session 工厂（注意：这不是一个全局 Session，每次用 SessionLocal() 取一个）。
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    # 提交后不让对象属性失效：转 dict 时不用再回库查一次。
    expire_on_commit=False,
)

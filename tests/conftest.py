"""pytest 全局配置。

测试默认关闭 OpenTelemetry：`agent_api` 在模块级初始化 telemetry，如果开发机
的 `.env` 配了 OTLP 端点，跑测试会向本地 Collector 发数据并被其它用例观察到。
需要验证导出的测试用 subprocess 或显式覆盖这个变量。
"""

import os

# 测试默认关闭 OpenTelemetry；需要验证导出的用例自己用 subprocess 覆盖。
os.environ["OTEL_SDK_DISABLED"] = "true"

# 干净 CI 环境没有 .env：database.py 在 import 期就要求 DATABASE_URL，
# auth.py 签发/校验 token 时需要 JWT_SECRET。这里给单元测试用的 dummy 值，
# 不会真的连接 MySQL，也不会调用模型。
os.environ.setdefault(
    "DATABASE_URL",
    "mysql+pymysql://ci:ci@127.0.0.1:3306/agent_service?charset=utf8mb4",
)
os.environ.setdefault("JWT_SECRET", "ci-only-secret-that-is-at-least-32-bytes-long")

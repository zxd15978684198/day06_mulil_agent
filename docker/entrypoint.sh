#!/bin/sh
# =============================================================================
# 应用容器入口。
#
#   等 MySQL → 索引缺失时补建 → exec 目标命令（默认 uvicorn）
#
# 最后一步用 `exec` 把 shell 换成目标进程，SIGTERM 才能直达 uvicorn ——
# 否则 `docker compose stop` 会白等 10 秒再 SIGKILL。
#
# 可用的环境变量开关：
#   SKIP_DB_WAIT=1            跳过等库（只在明确知道库已就绪时用）
#   DB_WAIT_TIMEOUT=90        等库的最长秒数
#   BUILD_INDEX_IF_MISSING=0  索引缺失时不自动重建，直接让服务按原样报错
# =============================================================================
set -e

if [ "${SKIP_DB_WAIT:-0}" != "1" ]; then
    echo "[entrypoint] 等待数据库 ..."
    python /app/docker/wait_for_mysql.py
fi

# 与 paths.VECTOR_STORE_DIR 一致；容器里项目根固定是 /app
VECTOR_STORE_DIR="${VECTOR_STORE_DIR:-/app/src/vector_store}"
MANIFEST="$VECTOR_STORE_DIR/index_manifest.json"

if [ ! -f "$MANIFEST" ] && [ "${BUILD_INDEX_IF_MISSING:-1}" = "1" ]; then
    echo "[entrypoint] 未找到 $MANIFEST，开始构建向量索引（首次要跑 OCR/多模态，较慢）..."
    python -m personal_assistant.build_index
fi

if [ ! -f "$MANIFEST" ]; then
    # agent_api 的 lifespan 会为这件事直接失败并打印可操作提示，这里只是把
    # 「为什么马上要挂」提前说清楚
    echo "[entrypoint] 警告：向量索引仍不存在，服务启动时会失败。" >&2
    echo "[entrypoint] 请先运行：docker compose run --rm app python -m personal_assistant.build_index" >&2
fi

exec "$@"

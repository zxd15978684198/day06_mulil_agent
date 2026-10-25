#!/usr/bin/env bash
# =============================================================================
# 在 Ubuntu 上构建并启动（练习用：源码就在这台机器上）
#
#   bash deploy/03-deploy.sh              # 增量构建 + 启动
#   bash deploy/03-deploy.sh --no-cache   # 全量重建（改了基础镜像/依赖时用）
#   bash deploy/03-deploy.sh --keep-down  # 先停掉旧容器再构建，省内存
#
# 退出码：0 成功；1 构建或启动失败；2 启动了但健康检查没通过
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
cd "${ROOT}" || exit 1

NO_CACHE=0
KEEP_DOWN=0
for arg in "$@"; do
    case "${arg}" in
        --no-cache) NO_CACHE=1 ;;
        --keep-down) KEEP_DOWN=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "未知参数：${arg}" >&2; exit 2 ;;
    esac
done

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }

if ! docker compose version >/dev/null 2>&1; then
    red "缺少 docker compose v2。先跑：sudo bash deploy/01-install-docker.sh"
    exit 1
fi
if [ ! -f .env ]; then
    red "缺少 .env。先跑：cp deploy/env.vm.example .env  然后填 API_KEY"
    exit 1
fi

# 构建前把旧容器停掉，可以省 1-2 GB 内存（虚拟机内存紧的时候很有用）
if [ "${KEEP_DOWN}" -eq 1 ]; then
    echo "==> 停掉旧容器，释放内存"
    docker compose down --remove-orphans
fi

echo
echo "==> 开始构建镜像（首次 10-20 分钟：装 torch、下 458MB 权重）"
echo "    这一阶段最容易卡在网络；卡住就看 deploy/README.md 的排错表"
BUILD_ARGS=()
if [ "${NO_CACHE}" -eq 1 ]; then
    BUILD_ARGS+=(--no-cache)
fi

START_TS=$(date +%s)
if ! docker compose build "${BUILD_ARGS[@]}"; then
    red "构建失败。常见原因："
    echo "  · registry-1.docker.io EOF      → .env 里配 DOCKER_MIRROR"
    echo "  · ghcr.io 超时                  → .env 里配 UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:latest"
    echo "  · 装包超时                      → .env 里配 UV_INDEX_URL（清华源）"
    echo "  · no space left on device       → df -h，清 docker builder prune"
    echo "  · 被 OOM killed                 → dmesg | tail，关掉别的负载或加内存"
    exit 1
fi
BUILD_SEC=$(( $(date +%s) - START_TS ))
green "构建完成，用时 $((BUILD_SEC/60)) 分 $((BUILD_SEC%60)) 秒"

echo
echo "==> 启动（mysql → db-init → app，有依赖顺序，别手动跳步）"
if ! docker compose up -d; then
    red "启动失败，最近日志："
    docker compose logs --tail=60
    exit 1
fi

echo
echo "==> 等 app 健康（最多 5 分钟；首次要建向量索引就慢）"
DEADLINE=$(( $(date +%s) + 300 ))
STATUS="unknown"
while [ "$(date +%s)" -lt "${DEADLINE}" ]; do
    STATUS="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' mutil-agent-app 2>/dev/null || echo missing)"
    case "${STATUS}" in
        healthy) break ;;
        missing) STATUS="容器不存在" ;;
    esac
    sleep 5
done

echo
if [ "${STATUS}" = "healthy" ]; then
    IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    green "服务已就绪"
    echo
    echo "  浏览器打开： http://${IP}:8000/"
    echo "  本机自查：   curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/"
    echo "  教学账号：   zhang_wei / 123456"
    echo
    echo "  查看状态：   docker compose ps"
    echo "  跟踪日志：   docker compose logs -f app"
    echo "  停止：       docker compose stop"
    echo "  连数据库：   docker compose exec mysql mysql -uroot -p\"\$MYSQL_ROOT_PASSWORD\" agent_service"
    exit 0
else
    red "健康检查未通过（当前状态：${STATUS}）"
    echo
    echo "--- app 最近 80 行 ---"
    docker compose logs --tail=80 app
    echo
    echo "--- 常见成因 ---"
    echo "  · 索引缺失：日志里出现「未找到 index_manifest.json」→ 等它建完，或手工跑："
    echo "      docker compose run --rm app python -m personal_assistant.build_index"
    echo "  · 连不上库：db-init 没跑完 → docker compose logs db-init"
    echo "  · 权限问题：/app/runtime 写不进去 → 别把命名卷改成 bind mount"
    exit 2
fi

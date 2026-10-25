#!/usr/bin/env bash
# =============================================================================
# 构建前的体检。不动任何东西，只报告 —— 目的是在你花 15 分钟构建之前，
# 先把「必然会失败」的原因找出来。
#
#   bash deploy/02-preflight.sh
#
# 检查四类：
#   1. Docker 本身（版本、compose v2、daemon 权限）
#   2. 机器资源（磁盘、内存 —— 这个项目构建期峰值吃 2-3 GB）
#   3. 五个下载源的连通性（构建期全部要访问，缺一个就会失败在半路）
#   4. 配置文件（.env 是否存在、密码是否还是默认值）
# =============================================================================
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
FAIL=0
WARN=0

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }

ok()   { green   "  [OK]   $*"; }
bad()  { red     "  [FAIL] $*"; FAIL=$((FAIL+1)); }
warn() { yellow  "  [WARN] $*"; WARN=$((WARN+1)); }

echo "==================== 1. Docker ===================="
if command -v docker >/dev/null 2>&1; then
    ok "docker 存在：$(docker --version 2>/dev/null | head -n1)"
else
    bad "没有 docker 命令。先跑：sudo bash deploy/01-install-docker.sh"
fi

if docker info >/dev/null 2>&1; then
    ok "docker daemon 可用（当前用户有权限）"
else
    bad "docker info 失败：要么 daemon 没起，要么当前用户不在 docker 组（重新登录 / newgrp docker）"
fi

if docker compose version >/dev/null 2>&1; then
    CV="$(docker compose version --short 2>/dev/null || docker compose version 2>/dev/null | head -n1)"
    ok "compose v2 可用：${CV}"
else
    bad "docker compose（v2 插件）不可用。apt 的 docker-compose 是 v1，本仓库用不了"
fi

echo
echo "==================== 2. 资源 ===================="
# 磁盘：镜像 2-3 GB + 构建中间层 + mysql 数据，留 25 GB 才从容
AVAIL_GB="$(df -Pk "${ROOT}" | awk 'NR==2 {printf "%d", $4/1024/1024}')"
if [ "${AVAIL_GB}" -ge 25 ]; then
    ok "磁盘可用 ${AVAIL_GB} GB"
elif [ "${AVAIL_GB}" -ge 12 ]; then
    warn "磁盘只剩 ${AVAIL_GB} GB（建议 ≥25 GB：镜像本身 2-3 GB，构建中间层还要翻倍）"
else
    bad "磁盘只剩 ${AVAIL_GB} GB，构建会在装 torch 时 no space left on device"
fi

MEM_MB="$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)"
if [ "${MEM_MB}" -ge 7000 ]; then
    ok "内存 ${MEM_MB} MB"
elif [ "${MEM_MB}" -ge 3500 ]; then
    warn "内存 ${MEM_MB} MB：能构建但会比较慢，建议先关掉别的负载（swap 打开也行）"
else
    bad "内存 ${MEM_MB} MB：装 torch/sentence-transformers 时大概率被 OOM killer 杀掉"
fi

echo
echo "==================== 3. 下载源连通性 ===================="
# 构建期按顺序会访问这些地方，任一不通都会让构建停在中途
probe() {
    local name="$1" url="$2" hint="$3"
    if curl -sS -o /dev/null -m 12 -I "${url}" 2>/dev/null; then
        ok "${name}"
    else
        bad "${name} 不可达  →  ${hint}"
    fi
}
probe "Docker Hub (基础镜像)"      "https://registry-1.docker.io/v2/"   "在 .env 里设 DOCKER_MIRROR=docker.m.daocloud.io/library/"
probe "ghcr.io (uv 二进制)"        "https://ghcr.io/v2/"                "在 .env 里设 UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:latest"
probe "PyPI (Python 依赖)"         "https://pypi.org/simple/"           "在 .env 里设 UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
probe "hf-mirror (Embedding 权重)" "https://hf-mirror.com"              "换 HF_ENDPOINT，或把权重提前放进 src 之外的构建上下文"
probe "PyTorch CPU 源"             "https://download.pytorch.org/whl/cpu/" "设 UV_TORCH_BACKEND 走别的源，或预置 wheel"

echo
echo "==================== 4. 配置 ===================="
if [ -f .env ]; then
    ok ".env 存在"

    # 只用 grep 读值，不 source。原因：.env 里的密码由 `openssl rand -base64 24`
    # 生成时可能含 $ / ` / \ 等字符，source 会被 shell 二次解释；空格也会炸。
    getenv() { grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }

    if grep -q $'\r' .env 2>/dev/null; then
        bad ".env 是 CRLF 换行（在 Windows 记事本里存过）。转成 LF：sed -i 's/\r$//' .env"
    fi

    if [ "$(getenv MYSQL_ROOT_PASSWORD)" = "ChangeMe-Root!" ]; then
        warn "MYSQL_ROOT_PASSWORD 还是默认值 ChangeMe-Root!（择机改掉）"
    else
        ok "MYSQL_ROOT_PASSWORD 已自定义"
    fi
    if [ "$(getenv MYSQL_APP_PASSWORD)" = "ChangeMe-App!" ]; then
        warn "MYSQL_APP_PASSWORD 还是默认值 ChangeMe-App!"
    else
        ok "MYSQL_APP_PASSWORD 已自定义"
    fi
    if [ -z "$(getenv API_KEY)" ]; then
        bad "API_KEY 为空：服务能起来，但一调模型就报错"
    else
        ok "API_KEY 已配置"
    fi
    if [ -z "$(getenv JWT_SECRET)" ]; then
        bad "JWT_SECRET 为空：登录会失败"
    else
        ok "JWT_SECRET 已配置"
    fi
else
    bad "没有 .env。先复制模板：cp deploy/env.vm.example .env ，再填 API_KEY"
fi

for f in Dockerfile docker-compose.yml .dockerignore; do
    [ -f "${f}" ] && ok "存在 ${f}" || bad "缺少 ${f}（这三个文件如果还没提交进 git，服务器上就没有）"
done

echo
echo "==================== 结论 ===================="
if [ "${FAIL}" -eq 0 ]; then
    green "通过（${WARN} 条警告）。可以构建了：bash deploy/03-deploy.sh"
    exit 0
else
    red "有 ${FAIL} 项阻塞、${WARN} 条警告。先解决上面的 [FAIL] 再构建。"
    exit 1
fi

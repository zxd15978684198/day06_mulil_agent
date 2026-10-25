#!/usr/bin/env bash
# =============================================================================
# Ubuntu 22.04 上装 Docker Engine + compose v2
#
#   sudo bash deploy/01-install-docker.sh
#
# 为什么不用 `apt install docker.io docker-compose`：
#   - Ubuntu 22.04 源的 docker.io 是 20.10，没有 buildx 的 cache mount 特性，
#     Dockerfile 里的 `RUN --mount=type=cache` 会直接报错；
#   - 源的 docker-compose 是 1.29（v1），不认本仓库 compose 里的
#     `name:` / `env_file.path` / `service_completed_successfully`。
#
# 本脚本装的是官方 docker-ce + docker-compose-plugin（v2），走阿里云镜像源。
# =============================================================================
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 sudo 运行：sudo bash $0" >&2
    exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
if [ "${ID}" != "ubuntu" ]; then
    echo "这个脚本只针对 Ubuntu，当前是 ${ID}。请按官方文档手工安装。" >&2
    exit 1
fi
if [ "${VERSION_ID}" != "22.04" ]; then
    echo "警告：脚本按 22.04 写的，当前是 ${VERSION_ID}，继续但可能要微调。" >&2
fi

echo "==> 1/6 装基础包"
apt-get update
apt-get install -y ca-certificates curl gnupg

echo "==> 2/6 信任 Docker 的 GPG key"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo "==> 3/6 添加 apt 源"
cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.aliyun.com/docker-ce/linux/ubuntu ${VERSION_CODENAME} stable
EOF

echo "==> 4/6 安装 docker-ce 与 compose 插件"
apt-get update
apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

echo "==> 5/6 写 daemon.json（日志轮转 + 镜像加速）"
mkdir -p /etc/docker
if [ -f /etc/docker/daemon.json ]; then
    cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s)"
    echo "    原有 daemon.json 已备份"
fi
# registry-mirrors 是「兜底加速」，不是必需：
#   某些镜像站偶尔失效，docker pull 会 fallback 到官方源；
#   如果这台机器能直连 Docker Hub，删掉 registry-mirrors 这一段更干净。
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  },
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
EOF

echo "==> 6/6 启动 + 授权"
systemctl enable docker
systemctl restart docker

if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    usermod -aG docker "${SUDO_USER}"
    echo "    已把 ${SUDO_USER} 加入 docker 组。"
    echo "    ⚠ 组关系不会对当前 shell 生效，要么重新登录，要么先跑：newgrp docker"
fi

echo
docker --version
docker compose version
echo
echo "完成。下一步（用普通用户，不要 sudo）："
echo "    bash deploy/02-preflight.sh"

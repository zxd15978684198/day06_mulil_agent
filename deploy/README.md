# 部署到 Ubuntu 22.04 虚拟机（练习版）

> 目标：把源码放到虚拟机上，**在虚拟机里构建镜像**，然后本机浏览器访问。
> 不需要域名、不需要 HTTPS、不需要镜像仓库 —— 练习阶段这些全是负债。

## 0. 先回答三个问题

**「1. 先练习部署到虚拟机上」**
那就走「源码上机 + 服务器构建」这条路。下面 `01/02/03` 三个脚本就是为它写的。

**「2. 域名 + HTTPS 是什么意思」**
现在你的服务地址是 `http://192.168.1.50:8000`（IP + 端口 + 明文）。加域名就是把地址变成 `http://demo.example.com`；加 HTTPS 就是变成 `https://demo.example.com`，浏览器地址栏没有「不安全」警告，传输加密。**练习阶段完全不需要**，等要给老师或外部的人看时再考虑，那时再加一层 Caddy 反向代理即可（见 §7）。

**「3. 不能先写好配置、再在 Ubuntu 上构建吗」**
能，这就是本文档的做法。代价只有一个：**虚拟机必须能访问 5 个下载源**（Docker Hub、ghcr.io、PyPI、hf-mirror、PyTorch）。所以先跑体检脚本，别盲构建。

## 1. 虚拟机准备

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 系统 | Ubuntu Server 22.04 LTS，x86_64 | 镜像本身按 amd64 构建 |
| CPU | 2 核起 | 编译 opencv/onnxruntime 的阶段用不到编译，但装包解包吃 CPU |
| 内存 | **4 GB 起，8 GB 舒服** | 构建峰值 2–3 GB（torch 解包），运行期 1.5–2 GB |
| 磁盘 | **40 GB**（最低 25 GB） | 镜像 2–3 GB + 构建中间层 + MySQL 数据 + 日志 |
| 网络 | NAT 或桥接，能出网 | 桥接的话记下 IP，宿主机要能 ping 通 |
| 快照 | **装完 Docker 先打一个** | 练习会反复 `down -v`、改配置，坏了能回滚 |

装完系统先做一件事，避免后面全是 `permission denied`：

```bash
sudo apt update && sudo apt install -y openssh-server
ip -4 addr show | grep inet        # 记下虚拟机 IP
```

宿主机（Windows）能 `ssh 用户名@虚拟机IP` 登进去，再往下做。

## 2. 把代码送进虚拟机

三个 Docker 文件（`Dockerfile` / `docker-compose.yml` / `.dockerignore`）**目前还没提交进 git**，远端仓库是拿不到的。两条路：

**路线 A：提交后克隆（推荐，后面改代码也方便）**

```powershell
# 在 Windows 本机、项目根目录
git add Dockerfile docker-compose.yml .dockerignore deploy/
git commit -m "chore: 容器化部署文件 + Ubuntu 22.04 部署脚本"
git push
```

```bash
# 在虚拟机里
sudo apt install -y git
git clone git@github.com:zxd15978684198/day06_mulil_agent.git
cd day06_mulil_agent
```

> 虚拟机里用 SSH 克隆需要配 key；嫌麻烦就临时改成 HTTPS + personal access token。

**路线 B：直接 scp 打包（不想动 git 时用）**

```powershell
# 在 Windows 本机
scp -r Dockerfile docker-compose.yml .dockerignore deploy src frontend alembic.ini main.py build_index.py pyproject.toml uv.lock 用户名@虚拟机IP:~/app/
```

`.env` 单独传，别和代码混在一起：

```powershell
scp .env 用户名@虚拟机IP:~/app/.env
```

## 3. 三步部署

```bash
# ① 装 Docker（只需一次，需要 sudo）
sudo bash deploy/01-install-docker.sh
newgrp docker          # 或退出重登，让 docker 组生效

# ② 体检（不装任何东西，只报告）
bash deploy/02-preflight.sh

# ③ 构建 + 启动（首次 10-20 分钟）
bash deploy/03-deploy.sh
```

第 ③ 步成功会打印访问地址。验证：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/   # 期望 200
docker compose ps                                                  # 三个服务，app 应为 healthy
docker compose logs --tail=30 app
```

浏览器打开 `http://虚拟机IP:8000/`，用 `zhang_wei / 123456` 登录。

## 4. 这套 compose 会做什么

```
mysql (8.4)          首次启动执行 day06_mysql_setup.sql（建表 + 27 个员工 + 19 条申请）
   │ healthcheck 通过
   ▼
db-init (一次性)      建 agent_app 账号（只有增删改查权限）+ 登记 alembic 账本，跑完退出
   │ service_completed_successfully
   ▼
app (FastAPI)         uvicorn 起在 8000；检查点 SQLite 在 app-runtime 卷，向量库在 app-vector-store 卷
```

两个命名卷的意义：容器删了重建，**对话历史和向量索引都不丢**。`docker compose down -v` 才会连卷一起删 —— 这条命令是练习时最容易手滑的。

## 5. 排错表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Head "https://registry-1.docker.io/v2/...": EOF` | Docker Hub 不可达 | `.env` 加 `DOCKER_MIRROR=docker.m.daocloud.io/library/`（结尾斜杠别丢） |
| `failed to resolve source metadata for ghcr.io/...` / TLS timeout | ghcr.io 不可达 | `.env` 加 `UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:latest` |
| `uv sync` 卡住 / `ReadTimeout` | PyPI 慢 | `.env` 加 `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` |
| 下 embedding 权重卡住 | hf-mirror 慢或断 | 换 `HF_ENDPOINT`；或本地先 `docker save` 带过去 |
| `Killed` / 构建到一半退出 | OOM | `dmesg \| tail`；先 `docker compose down` 腾内存，或加内存/开 swap |
| `no space left on device` | 磁盘满 | `docker builder prune -af`；扩容 |
| `permission denied while trying to connect to the Docker daemon` | 不在 docker 组 | `newgrp docker` 或重登 |
| app 一直 `unhealthy` | 索引缺失或连不上库 | `docker compose logs app`；`docker compose logs db-init` |
| 页面能开、登录 500 | `/app/runtime` 写不进去 | 确认卷是**命名卷**，别改成 `./runtime` bind mount |
| 中文显示成 `å¼ ä¼Ÿ` | MySQL 客户端按 latin1 解析 | 确认 compose 里 `LANG: C.UTF-8` 还在 |
| 端口通了但外网访问不了 | 虚拟机 NAT 或防火墙 | 桥接模式；`sudo ufw allow 8000/tcp` |

## 6. 日常操作

```bash
docker compose ps                     # 状态
docker compose logs -f app            # 跟日志
docker compose restart app            # 重启应用（不动数据库）
bash deploy/03-deploy.sh              # 改完代码重新构建并上线
docker compose stop                   # 停机，数据保留
docker compose down -v                # 连数据一起删（危险）
```

备份（练习阶段至少知道命令长什么样）：

```bash
docker compose exec mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" agent_service' > backup_$(date +%F).sql
docker run --rm -v mutil-agent_app-runtime:/data -v "$PWD":/out alpine tar czf /out/runtime_$(date +%F).tgz -C /data .
```

## 7. 以后要加域名 + HTTPS 时

现在不用做。要做的时候只需要三步，不用改应用：

1. `.env` 里把 `APP_BIND` 改成 `127.0.0.1`（应用只让反代进来）
2. 起一个 Caddy 容器，`Caddyfile` 一行：`demo.example.com { reverse_proxy app:8000 }`
3. 域名 A 记录指向服务器，放行 80/443

Caddy 会自动申请并续期证书 —— 这是它比 nginx 省事的地方。

## 8. 这些脚本没做的事

- 没有 CI，没有镜像仓库，没有版本 tag 管理（练习够用，正式流程要补 `IMAGE_TAG` + 回滚）
- 没有监控和告警，`docker compose ps` 就是你的监控
- 没有资源配额（compose 里留了注释掉的内存限制块，等要和生产服务挤一台机器时再开）

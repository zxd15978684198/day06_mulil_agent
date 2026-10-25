# =============================================================================
# 多 Agent 员工助手 —— 镜像定义
#
# 两阶段：
#   1) frontend —— Node 构建 Vite/React 前端，产物落在 /build/src/static
#   2) runtime  —— Python 3.13 + uv（按 uv.lock 精确装依赖）+ 前端产物 + 向量索引
#
# 四个不显然、但别随手改的取舍：
#
#   1. 用 `uv sync --frozen` 而不是 `pip install -r requirements.txt`：
#      依赖的真源是 uv.lock。根目录那份 requirements.txt 是 Day06 留下的旧清单，
#      缺 fastapi / sqlalchemy / pymysql / pyjwt / alembic，照着装起不来。
#
#   2. **不安装项目本身**（--no-install-project），改用 PYTHONPATH=/app/src：
#      personal_assistant/paths.py 用 __file__ 反推 PROJECT_ROOT，一旦被装进
#      site-packages，SRC_ROOT 就变成 site-packages，_assert_layout() 会在
#      import 期直接抛「找不到 data/、knowledge/」。
#
#   3. torch 单独换成 CPU 轮子：uv.lock 里 torch 来自 PyPI，在 linux 上会拖进
#      43 个 nvidia/cuda-* 包 + triton（数 GB），而本项目只用 CPU 跑 embedding。
#
#   4. Embedding 权重烘进镜像：冷启动加载要 22.97s（本机实测），烘进去以后
#      容器启动不再依赖 Hugging Face 可达。
#
# 换服务器部署时唯一需要调的是下面的 REGISTRY（见 docker-compose.yml 的
# DOCKER_MIRROR）：
# =============================================================================

# 基础镜像的 registry 前缀。默认空 = 走 Docker Hub。
#
# 国内服务器基本直连不通 registry-1.docker.io（现象是构建第一步就
# `Head "https://registry-1.docker.io/v2/...": EOF`），这时把 DOCKER_MIRROR
# 设成镜像站即可，不用改这个文件：
#     DOCKER_MIRROR=docker.m.daocloud.io/library/     # 注意结尾的斜杠
# compose 会把它传进来。
#
ARG REGISTRY=""

# uv 二进制从哪个镜像取。
#
# 注意 ghcr.io 和 Docker Hub 的连通性是两回事：Docker Hub 挂镜像站能救，
# ghcr.io 在国内机房时通时不通（本机实测可连，虚拟机上经常卡在
# "TLS handshake timeout" 或 "EOF"）。所以这里留一个可覆盖的入口：
#
#   换 DaoCloud 的 ghcr 代理：
#     --build-arg UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:latest
#
#   想固定版本就把 digest 抄进来（构建可重现）：
#     docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest
#     → ARG UV_IMAGE=ghcr.io/astral-sh/uv@sha256:...
#
#   两者都不行时的兜底见 deploy/README.md「排错表」第 2 条。
ARG UV_IMAGE=ghcr.io/astral-sh/uv:latest


# ---------- 阶段 1：前端 ------------------------------------------------------
FROM ${REGISTRY}node:22-alpine AS frontend

WORKDIR /build

# 先只拷依赖清单：改前端源码不会让 npm ci 这一层失效
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY frontend/ ./frontend/
# vite.config.ts 的 outDir 是 '../src/static'（相对 frontend/），
# 所以 frontend/ 这一层目录必须保留，产物落在 /build/src/static
RUN cd frontend && npm run build


# ---------- 阶段 2：运行时 ----------------------------------------------------
FROM ${REGISTRY}python:3.13-slim-bookworm

# 只从 uv 官方镜像里取二进制，基础镜像仍用 python:3.13-slim-bookworm，
# 免得 uv 的 python-* 变体tag变动把构建带崩。
# 重新声明一次 ARG：全局 ARG 不会自动带进 stage，COPY --from 要能替换到它。
ARG UV_IMAGE
COPY --from=${UV_IMAGE} /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    HF_HOME=/opt/hf-cache

# rapidocr-onnxruntime 拉进来的是 opencv + onnxruntime，slim 镜像里缺这几个 .so
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- 依赖层 ----------------------------------------------------------------
# 只依赖 pyproject.toml / uv.lock：改业务代码不会让这几百 MB 重装。
#
# uv.lock 是按 linux 平台解析的，torch 在那里挂着**整条 CUDA 栈**
# （nvidia-* / cuda-* / triton，20 个包、好几 GB），而本项目只用 CPU 跑 embedding。
#
# 只写 `--no-install-package torch` 是不够的：torch 本身被排除了，它那些依赖
# 仍会照常装上（实测会去下 nvidia-cuda-runtime）。所以按 uv.lock 里的实际包名
# 把整组一起排除，再从 PyTorch 的 CPU 源把 torch 本体装回来。
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    EXCLUDES="$(grep -E '^name = "(torch|triton|nvidia-|cuda-)' uv.lock | cut -d'"' -f2 | sort -u)"; \
    echo "排除 CUDA 相关包："; echo "$EXCLUDES"; \
    set --; \
    for pkg in $EXCLUDES; do set -- "$@" --no-install-package "$pkg"; done; \
    uv sync --frozen --no-install-project --no-dev "$@"; \
    TORCH_VERSION="$(grep -A1 '^name = "torch"$' uv.lock | grep '^version = ' | head -n1 | cut -d'"' -f2)"; \
    test -n "$TORCH_VERSION"; \
    echo "改从 PyTorch CPU 源装 torch==$TORCH_VERSION"; \
    uv pip install --python /opt/venv --torch-backend=cpu "torch==$TORCH_VERSION"

# --- 预下载 Embedding 权重 ---------------------------------------------------
# 与 knowledge_base.DEFAULT_EMBEDDING_MODEL 一致。换 EMBEDDING_MODEL 时运行期
# 会照常从 HF_ENDPOINT 下载，只是首次会慢。
#
# **位置很重要**：这一层只依赖上面的依赖层，故意放在 COPY 源码**之前**。
# 实测从 hf-mirror 拉这 458MB 要 6 分钟；放在 COPY 之后的话，改一行 docker/ 下
# 的脚本都会让它整层失效重下。
# 默认走镜像站：本机 huggingface.co 不可达（见 .env 的 HF_ENDPOINT）。
ARG HF_ENDPOINT=https://hf-mirror.com
ENV HF_ENDPOINT=${HF_ENDPOINT}
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); \
print('embedding 权重已缓存到', __import__('os').environ['HF_HOME'])"

# --- 业务代码、数据与已建好的向量索引 ----------------------------------------
COPY src/ ./src/
COPY alembic.ini main.py build_index.py ./
COPY docker/ ./docker/

# 前端产物覆盖 src/static 里那份：仓库里那份是提交进 git 的历史产物，
# 未必跟得上 frontend/src 的最新改动
COPY --from=frontend /build/src/static ./src/static

# --- 运行身份 ----------------------------------------------------------------
# 不用 root：运行期只需要写 ./runtime（检查点）和 src/vector_store（重建索引），
# 这两个都从宿主机挂进来
# 先把 /app/runtime 建出来，再连同 /app 一起交给 app 用户。
# compose 里 /app/runtime 与 /app/src/vector_store 挂的是**命名卷**：Docker 首次
# 创建卷时会照抄镜像里这个目录的**属主**，所以这两句决定了容器里的 app（uid 1000）
# 能不能写检查点与向量库。
#
# 用 bind mount 就没这个保障 —— Linux 上 Docker 会把不存在的宿主目录建成 root 所有，
# uid 1000 写不进去，现象是「服务起得来、一登录就 500」。这也是本仓库原本用
# `./runtime:/app/runtime` 时换服务器会踩的坑。
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/runtime \
 && chown -R app:app /app /opt/hf-cache
USER app

EXPOSE 8000

# 用 /bin/sh 显式执行，不依赖构建上下文里 entrypoint.sh 的可执行位
# （Windows 上构建时，文件模式不一定能带过来）
ENTRYPOINT ["/bin/sh", "/app/docker/entrypoint.sh"]
# --proxy-headers / --forwarded-allow-ips：容器前面挂 nginx/Caddy 时，
# 让 uvicorn 认 X-Forwarded-Proto / X-Forwarded-For，否则 request.url.scheme
# 永远是 http、client.host 永远是反代的 172.x 内网地址。
# 只信任内网来源：这里写成 * 是因为容器端口只在 compose 网络/回环上，
# 真要暴露到公网时，把 * 换成反代容器的固定网段更稳。
# 不加 --workers：检查点是 SQLite，多进程并发写会撞 database is locked。
CMD ["uvicorn", "personal_assistant.agent_api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

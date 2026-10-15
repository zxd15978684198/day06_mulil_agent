"""项目路径解析（src 布局下所有路径的唯一来源）。

目录归属（决策 D4，已按用户要求把数据目录收进 `src/`）：

```
<仓库根>/                     ← PROJECT_ROOT：pyproject.toml、.env、入口薄壳
├── src/                      ← SRC_ROOT
│   ├── personal_assistant/   ← 可安装的代码包（PACKAGE_DIR）
│   ├── data/                 ← 业务 JSON（含唯一可写文件 day05_device_requests.json）
│   ├── knowledge/            ← 知识文件 + 权限清单
│   ├── static/               ← WebAPI 联调页（GET / 返回的 HTML）
│   └── vector_store/         ← Chroma 索引
└── ...
```

⚠️ **为什么 `data/` 与 `vector_store/` 在 `src/` 下、却不在包目录里**：
`data/day05_device_requests.json` 是程序运行时**唯一会被写入**的文件，`vector_store/`
也是生成物。包目录是**安装产物** —— 一旦本项目被非可编辑方式装进 site-packages，
写进去的就是 `.venv/Lib/site-packages/...`，业务数据会被写进环境目录。所以数据放在
`src/` 下、但**在包外**。

⚠️ **为什么包内模块不许自己拼路径**：课件 §7.1 的 `build_model()` 用
`os.path.dirname(os.path.abspath(__file__))` 定位 `.env`。搬进 `src/<包>/` 之后
`__file__` 指向包目录，`.env` 会被找成 `src/<包>/.env` —— **文件不存在，
`load_dotenv` 不报错、只是什么都不加载**，于是报「请在 .env 中配置
MODEL_PROVIDER 和 MODEL_NAME」，而你去检查 `.env` 发现明明写好了。
这是本计划 §5.2 记录的静默失效点。
"""

from __future__ import annotations

import os
from pathlib import Path

# src/personal_assistant/paths.py
PACKAGE_DIR = Path(__file__).resolve().parent  # → src/personal_assistant
SRC_ROOT = PACKAGE_DIR.parent  # → src
PROJECT_ROOT = SRC_ROOT.parent  # → 仓库根（pyproject.toml、.env 所在）

DATA_DIR = SRC_ROOT / "data"
KNOWLEDGE_DIR = SRC_ROOT / "knowledge"
VECTOR_STORE_DIR = SRC_ROOT / "vector_store"
STATIC_DIR = SRC_ROOT / "static"
ENV_PATH = PROJECT_ROOT / ".env"

# 运行期产物目录（LangGraph 会话检查点 SQLite）。不入库：见 .gitignore 的 `runtime/`。
# 放在**仓库根**而不是 `src/` 下：它不是业务数据，而是「进程状态的落盘」——
# 换机器或要清状态时整目录删掉即可，不牵动任何业务数据。
RUNTIME_DIR = PROJECT_ROOT / "runtime"
CHECKPOINT_DB_DEFAULT = "runtime/checkpoints.sqlite3"


def checkpoint_path() -> Path:
    """把 `CHECKPOINT_DB` 解析成不依赖启动目录的绝对路径，并确保父目录存在。

    为什么不能用 CWD 相对路径（课件 §7.1 的要点）：从别的目录启动 uvicorn 时
    会在那儿新建一个**空的**检查点库，现象是「重启后历史全没了」，而文件确实存在，
    极难排查。所以相对路径一律按 `PROJECT_ROOT` 解析。

    这里顺带 `load_dotenv(ENV_PATH, override=False)`：让本函数单独被调用时也读得到
    `.env`（幂等，且不覆盖已存在的环境变量）。
    """
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=False)
    raw = (os.getenv("CHECKPOINT_DB") or CHECKPOINT_DB_DEFAULT).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _assert_layout() -> None:
    """层级数错或非可编辑安装时，此处 fail fast 而不是去别处找文件。

    数据目录在 `src/` 下是**本项目的约定**；若本项目被当成普通 wheel 装进
    site-packages，上面的相对层级会指向 `Lib/site-packages` 附近 ——
    此时必须**报错**，否则会变成更难查的静默错误。
    """
    missing = [path.name for path in (DATA_DIR, KNOWLEDGE_DIR) if not path.is_dir()]
    if missing:
        raise RuntimeError(
            f"项目路径解析错误：{SRC_ROOT} 下找不到 {missing}。"
            "本项目按 src 布局运行（数据在 src/ 下、包外），"
            "须以可编辑方式安装（uv sync）并从仓库内运行。"
        )


_assert_layout()

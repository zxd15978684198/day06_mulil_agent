"""项目路径解析（src 布局下所有路径的唯一来源）。

目录归属（决策 D4，已按用户要求把数据目录收进 `src/`）：

```
<仓库根>/                     ← PROJECT_ROOT：pyproject.toml、.env、入口薄壳
├── src/                      ← SRC_ROOT
│   ├── personal_assistant/   ← 可安装的代码包（PACKAGE_DIR）
│   ├── data/                 ← 业务 JSON（含唯一可写文件 day05_device_requests.json）
│   ├── knowledge/            ← 知识文件 + 权限清单
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

from pathlib import Path

# src/personal_assistant/paths.py
PACKAGE_DIR = Path(__file__).resolve().parent  # → src/personal_assistant
SRC_ROOT = PACKAGE_DIR.parent  # → src
PROJECT_ROOT = SRC_ROOT.parent  # → 仓库根（pyproject.toml、.env 所在）

DATA_DIR = SRC_ROOT / "data"
KNOWLEDGE_DIR = SRC_ROOT / "knowledge"
VECTOR_STORE_DIR = SRC_ROOT / "vector_store"
ENV_PATH = PROJECT_ROOT / ".env"


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

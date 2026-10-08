"""支持 `python -m personal_assistant` / `uv run python -m personal_assistant`。

这是计划 §8 第 20 条的验收入口：从**仓库外的任意目录**运行
`uv run --project E:\\projects\\mutil_agent python -m personal_assistant`，
仍应能找到 `data/` / `knowledge/` / `.env`（验证 `paths.py` 基于 `__file__`
而非当前工作目录）。

行为与根目录 `main.py` 薄壳一致：转到 CLI 入口。CLI 本身属于阶段 5 的产出。
"""

from __future__ import annotations

from personal_assistant.main import main

if __name__ == "__main__":
    main()

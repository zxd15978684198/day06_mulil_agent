"""命令行入口（计划 P8 / 阶段 5 的产出）。

现在只是占位：阶段 5 才实现登录循环、`/logout`、`/quit`、中断交互与路由证据打印。
本文件先存在，是为了让 `src` 布局与根目录薄壳的入口在阶段 1–2 就位、可被 import 检查。
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "main.py（CLI 入口）属于阶段 5 的产出，尚未实现。\n"
        "当前已完成：阶段 1（RunContext / ROLE_PERMISSIONS）、阶段 2（知识库建库）。\n"
        "要构建向量库请运行：uv run python build_index.py"
    )


if __name__ == "__main__":
    main()

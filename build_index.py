"""根目录入口薄壳：保留计划里写的 `uv run python build_index.py`。

真正的实现在 `src/personal_assistant/build_index.py`。
"""

from personal_assistant.build_index import main

if __name__ == "__main__":
    main()

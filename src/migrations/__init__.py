"""Alembic 迁移环境（工具链，不是应用包的一部分）。

存在这个文件只是让 `import migrations.sql_runner` 成为**确定**的常规包导入，
而不是依赖 PEP 420 隐式命名空间包。它不会被 `pyproject.toml:40-41`
（`packages = ["src/personal_assistant"]`）打进 wheel。

注意：`versions/` 下**不要**放 `__init__.py` —— alembic 要把那里的 .py 当迁移脚本
按文件路径加载，且无法导入 env.py 的初始化顺序。
"""

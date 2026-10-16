# src/migrations —— Alembic 迁移环境

```
src/migrations/
├── env.py            ← 连库 + target_metadata（从 .env 读 DATABASE_URL）
├── script.py.mako    ← `alembic revision` 生成薄壳用的模板
├── sql_runner.py     ← 薄壳调用的 run_sql()：按分号拆语句逐条下发
├── sql/              ← 手写 SQL（唯一事实源），见 sql/README.md
└── versions/         ← 薄壳迁移，每个文件对应 sql/ 下的一个 SQL
```

`alembic.ini` 在仓库根（`script_location = %(here)s/src/migrations`）。
为什么迁移放在 `src/` 下、却不在包目录里：见 [sql/README.md](sql/README.md) 开头和
`src/personal_assistant/paths.py:16-20`（决策 D4）—— 迁移是工具链，不是安装产物。

## 首次：登记基线

库里已经有 Day05 建好的表，所以第一步是**把现状记成版本 0**，不是让 alembic 去建表：

```bash
# 1) 生成空壳，upgrade/downgrade 里写 pass（不要 --autogenerate）
uv run alembic revision -m "baseline: day05 schema"

# 2) 只写账本，不执行任何 DDL
uv run alembic stamp head
```

⚠️ 顺序不能反：如果先 `upgrade`，那条基线迁移会试图 CREATE 已存在的表，
报 `(1050, "Table 'users' already exists")`。

## 每次改库

```bash
# 1. 把 SQL 复制进 sql/，命名 V00N__描述.sql（回滚另存 .down.sql）
# 2. 生成薄壳
uv run alembic revision -m "add users.password_hash"
# 3. 打开 src/migrations/versions/<新文件>.py，把两个 TODO 换成真实文件名
# 4. 只读预演：审 SQL，不碰库
uv run alembic upgrade head --sql
# 5. 执行
uv run alembic upgrade head
# 6. 同步 src/personal_assistant/models.py，然后查漂移（必须无输出）
uv run alembic check
# 7. 对账
uv run alembic current
uv run alembic history --verbose
```

## 纪律（会真的咬人的那几条）

| 坑 | 对策 |
| --- | --- |
| MySQL 8.0 **没有** `ADD COLUMN IF NOT EXISTS`（那是 MariaDB） | 幂等靠 alembic 账本，不要靠 `IF NOT EXISTS` |
| 迁移里既有 DDL 又有数据 UPDATE | MySQL DDL 隐式提交、没有事务，中途失败留半迁移 → 回填单独写一个版本 |
| 改了**已执行过**的 SQL / 迁移 | 别的环境不会重跑 → 只能加新版本，永不改旧版本 |
| 同时用 `--autogenerate` 和手写 SQL 改同一批对象 | 二选一。本项目是 SQL-first：SQL 是真源，`alembic check` 兜底 |
| `DELIMITER` / 存储过程 / 触发器 | `sql_runner` 不支持 → 用 mysql 客户端单独执行，再 `alembic stamp` |
| 连接串写进 alembic.ini | 不要：密码会进版本库。env.py 已经从 `.env` 读 |

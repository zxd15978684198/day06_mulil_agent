# src/migrations/sql —— 手写 SQL 的唯一事实源

## 为什么在这里

位置与 `src/data/`、`src/knowledge/`、`src/vector_store/` 同级，遵循本项目
**决策 D4**（依据见 `src/personal_assistant/paths.py:16-20`）：**放在 `src/` 下、
但在包外**。理由和那些数据目录完全一样 —— `src/personal_assistant/` 是**安装产物**
（`pyproject.toml:40-41`：`packages = ["src/personal_assistant"]`），而迁移是工具链，
不是运行时代码，不该跟着 wheel 进 `site-packages`。

配套：alembic 环境在 `src/migrations/{env.py, script.py.mako, versions/}`，
`alembic.ini` 在仓库根，其中 `script_location = %(here)s/src/migrations`
（`%(here)s` = ini 文件所在目录，因此从任何工作目录调用都不会跑偏）。

这个目录存放**按版本编号的 SQL 文件**。每个 `.sql` 由 `src/migrations/versions/`
下同名的「薄壳」迁移读取并执行；版本账本由 alembic 维护
（库里 `agent_service.alembic_version` 单行表）。

## 命名约定

```
V001__add_users_password_hash.sql        升级
V001__add_users_password_hash.down.sql   回滚（可选，但强烈建议写）
```

- `V<三位序号>__<snake_case 描述>.sql`，序号与描述之间是**两个**下划线。
- 序号只增不减。**已经执行过的文件永不修改** —— 要改就加一个新版本。
- 文件名里的 `V00N` 只是给你看的排序提示；alembic 真正的顺序由迁移壳里的
  `down_revision` 链决定。

## 纪律

1. 一个版本 = 一个文件 = 一个语义变更。别把 5 个不相关改动塞进一个文件，
   否则失败时无法只回滚其中一半。
2. 这个目录**会被提交**：不要写进密码、API key、真实用户数据。需要的话用占位符，
   并在运行时替换。
3. 文件里的语句按 `;` 拆开逐条执行。**不支持 `DELIMITER`**（存储过程、触发器、
   多语句复合体）—— 这类请单独用 `mysql` 客户端执行，再 `alembic stamp` 记账。
4. MySQL 8.0 **没有** `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（那是 MariaDB 的扩展）。
   幂等性由 alembic 的版本账本保证，**不要**靠 `IF NOT EXISTS`。
5. MySQL 的 DDL 是**隐式提交**、没有事务：一条迁移里既有 DDL 又有数据 UPDATE 时，
   中途失败会留下半迁移状态。要回填数据就单独写一个版本。
6. 改完 SQL 后同步 `src/personal_assistant/models.py`，然后跑 `uv run alembic check`，
   必须没有任何输出（这是 SQL-first 方案唯一的自动漂移检测）。

## 基线

`scripts/day05_mysql_setup.sql` 是 Day05 原样的**建库脚本**，不放进这个目录。
它对应 `V000` 基线：用 `uv run alembic stamp head` 记账，不要把它改造成迁移文件。

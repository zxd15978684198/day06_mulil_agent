-- V002 · 给 10 个教学账号写入 Argon2 密码摘要
-- ============================================================================
-- 这是 day06_mysql_setup.sql 相对 day05_mysql_setup.sql 的**唯一 DML 增量**
-- （day06_mysql_setup.sql:160-174，原文一模一样）。
--
-- 为什么不和 V001 合成一版：
--     MySQL 的 DDL 是**隐式提交**的 —— 没有回滚点。DDL 和 DML 混在同一条迁移里，
--     一旦 DML 中途失败，DDL 已经生效且撤不回来，你就得到一个"改了结构但没改数据"
--     的半迁移状态。分开两版，失败时账本停在 V001，重跑 V002 即可。
--
-- 摘要内容：口令 123456 的 Argon2id 摘要（m=65536, t=3, p=4）。
--     仅用于本地课堂演示；真实项目禁止把弱口令摘要提交进版本库。
--
-- login_enabled = TRUE 与 day05 的播种一致（那 10 行本来就是 1），
-- 写在这里是为了和 day06 脚本逐字对齐，不是为了修正数据。
-- ============================================================================
UPDATE users
SET login_enabled = TRUE,
    password_hash = '$argon2id$v=19$m=65536,t=3,p=4$/C9U4bldU4SH20clZ5F9rw$GQUIerwsCdUNroeFWCJEtcnjVnquj5DUEn1/iUHHHtI'
WHERE username IN (
  'zhang_wei',
  'li_na',
  'wang_fang',
  'chen_hao',
  'liu_yang',
  'zhao_min',
  'zhou_jie',
  'sun_yue',
  'wu_ting',
  'zheng_kai'
);

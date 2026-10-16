-- V002 回滚 · 清空这 10 个账号的密码摘要
-- ============================================================================
-- 只清 password_hash，**不动 login_enabled**：
-- day05 里这 10 行的 login_enabled 本来就是 1，把它改成 0 是"回滚引入了新差异"，
-- 会让库回到一个既不是 V001 也不是 day05 的第三种状态。
--
-- ⚠️ 真实账号已经自己设过密码之后，这条回滚会**不可逆地清掉那些密码**。
--    演练请只在本地教学库做。
-- ============================================================================
UPDATE users
SET password_hash = NULL
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

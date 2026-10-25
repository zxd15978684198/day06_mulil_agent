-- Week16 Day05：本地教学数据库一次性初始化脚本
-- 使用 MySQL 管理员账号执行。脚本不会删除已有数据库或覆盖同主键业务数据。
-- 如果本机已有同名正式数据，请先备份并改用其他数据库名。

CREATE DATABASE IF NOT EXISTS agent_service
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'agent_app'@'127.0.0.1'
  IDENTIFIED BY 'ChangeMe-Day05!';
ALTER USER 'agent_app'@'127.0.0.1'
  IDENTIFIED BY 'ChangeMe-Day05!';

-- 运行账号只有业务读写权限；建库建表由管理员在本脚本中完成。
GRANT SELECT, INSERT, UPDATE, DELETE
  ON agent_service.* TO 'agent_app'@'127.0.0.1';
FLUSH PRIVILEGES;

USE agent_service;

CREATE TABLE IF NOT EXISTS departments (
  department_id VARCHAR(30) PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  responsibilities JSON NOT NULL,
  office_location VARCHAR(200) NOT NULL,
  public_contact VARCHAR(200) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
  user_id VARCHAR(30) PRIMARY KEY,
  username VARCHAR(50) NULL,
  display_name VARCHAR(100) NOT NULL,
  role VARCHAR(30) NULL,
  login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  account_status VARCHAR(30) NULL,
  department_id VARCHAR(30) NOT NULL,
  job_title VARCHAR(100) NULL,
  expertise JSON NOT NULL,
  office_location VARCHAR(200) NULL,
  office_contact VARCHAR(200) NULL,
  is_public BOOLEAN NOT NULL DEFAULT FALSE,
  CONSTRAINT ck_users_role CHECK (role IS NULL OR role IN ('employee', 'hr')),
  CONSTRAINT ck_users_status CHECK (
    account_status IS NULL OR account_status IN ('active', 'disabled')
  ),
  CONSTRAINT fk_users_department
    FOREIGN KEY (department_id) REFERENCES departments(department_id),
  UNIQUE INDEX ix_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS devices (
  device_id VARCHAR(40) PRIMARY KEY,
  name VARCHAR(100) NOT NULL UNIQUE,
  category VARCHAR(50) NOT NULL,
  description TEXT NOT NULL,
  eligible_roles JSON NOT NULL,
  eligible_department_ids JSON NOT NULL,
  max_quantity_per_request INT NOT NULL,
  request_requirements TEXT NOT NULL,
  is_requestable BOOLEAN NOT NULL DEFAULT TRUE,
  CONSTRAINT ck_devices_max_quantity CHECK (max_quantity_per_request >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS device_requests (
  request_id VARCHAR(40) PRIMARY KEY,
  applicant_user_id VARCHAR(30) NOT NULL,
  device_id VARCHAR(40) NOT NULL,
  quantity INT NOT NULL,
  reason TEXT NOT NULL,
  status VARCHAR(30) NOT NULL,
  requested_at DATETIME NOT NULL,
  reviewer_user_id VARCHAR(30) NULL,
  reviewed_at DATETIME NULL,
  review_comment TEXT NULL,
  CONSTRAINT ck_device_requests_quantity CHECK (quantity > 0),
  CONSTRAINT ck_device_requests_status CHECK (
    status IN ('pending', 'approved', 'rejected')
  ),
  CONSTRAINT fk_requests_applicant
    FOREIGN KEY (applicant_user_id) REFERENCES users(user_id),
  CONSTRAINT fk_requests_device
    FOREIGN KEY (device_id) REFERENCES devices(device_id),
  CONSTRAINT fk_requests_reviewer
    FOREIGN KEY (reviewer_user_id) REFERENCES users(user_id),
  INDEX ix_device_requests_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_threads (
  thread_id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(30) NOT NULL,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_agent_threads_user
    FOREIGN KEY (user_id) REFERENCES users(user_id),
  INDEX ix_agent_threads_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

START TRANSACTION;

INSERT IGNORE INTO departments (department_id, name, responsibilities, office_location, public_contact) VALUES
  ('DEPT-HR', '人力资源部', '["招聘","劳动合同","员工证明","员工异动","设备申请审批"]', '北京总部 8 层', 'hr-service@example.com'),
  ('DEPT-FINANCE', '财务部', '["费用报销","发票审核","付款进度","差旅费用"]', '北京总部 9 层', 'finance-service@example.com'),
  ('DEPT-IT', '信息技术部', '["软件账号","公司邮箱","VPN","办公网络","设备技术支持"]', '北京总部 10 层', 'it-service@example.com'),
  ('DEPT-PRODUCT', '产品部', '["产品规划","用户调研","需求分析","产品设计"]', '北京总部 10 层', 'product@example.com'),
  ('DEPT-SALES', '销售部', '["客户沟通","商务报价","合同跟进","销售支持"]', '上海研发中心 5 层', 'sales@example.com'),
  ('DEPT-RND', '研发部', '["软件开发","系统架构","质量测试","技术评审"]', '上海研发中心 6 层', 'rnd@example.com'),
  ('DEPT-MARKETING', '市场部', '["品牌宣传","市场活动","内容运营","媒体合作"]', '北京总部 9 层', 'marketing@example.com'),
  ('DEPT-CS', '客户成功部', '["客户培训","产品使用咨询","续约跟进","客户反馈"]', '上海研发中心 5 层', 'customer-success@example.com'),
  ('DEPT-LEGAL', '法务部', '["合同审核","合规咨询","知识产权","法律风险"]', '北京总部 8 层', 'legal@example.com'),
  ('DEPT-ADMIN', '行政部', '["门禁卡","会议室","办公用品","工位与公共设施"]', '北京总部 8 层', 'admin@example.com');

INSERT IGNORE INTO users (user_id, username, display_name, role, login_enabled, account_status, department_id, job_title, expertise, office_location, office_contact, is_public) VALUES
  ('USR-001', 'zhang_wei', '张伟', 'employee', 1, 'active', 'DEPT-PRODUCT', '产品助理', '["需求整理","用户反馈"]', '北京总部 10 层', 'zhang.wei@example.com', 1),
  ('USR-002', 'li_na', '李娜', 'employee', 1, 'active', 'DEPT-SALES', '销售助理', '["客户资料","销售支持"]', '上海研发中心 5 层', 'li.na@example.com', 1),
  ('USR-003', 'wang_fang', '王芳', 'hr', 1, 'active', 'DEPT-HR', 'HR 专员', '["招聘流程","设备申请审批"]', '北京总部 8 层', 'wang.fang@example.com', 1),
  ('USR-004', 'chen_hao', '陈浩', 'employee', 1, 'active', 'DEPT-IT', 'IT 服务工程师', '["软件账号","公司邮箱","VPN"]', '北京总部 10 层', 'chen.hao@example.com', 1),
  ('USR-005', 'liu_yang', '刘洋', 'employee', 1, 'active', 'DEPT-FINANCE', '财务助理', '["报销材料","发票整理"]', '北京总部 9 层', 'liu.yang@example.com', 1),
  ('USR-006', 'zhao_min', '赵敏', 'employee', 1, 'active', 'DEPT-RND', '后端开发工程师', '["Python","接口开发"]', '上海研发中心 6 层', 'zhao.min@example.com', 1),
  ('USR-007', 'zhou_jie', '周杰', 'employee', 1, 'active', 'DEPT-MARKETING', '内容运营专员', '["内容发布","活动文案"]', '北京总部 9 层', 'zhou.jie@example.com', 1),
  ('USR-008', 'sun_yue', '孙悦', 'employee', 1, 'active', 'DEPT-CS', '客户成功顾问', '["客户培训","产品使用咨询"]', '上海研发中心 5 层', 'sun.yue@example.com', 1),
  ('USR-009', 'wu_ting', '吴婷', 'employee', 1, 'active', 'DEPT-LEGAL', '法务助理', '["合同归档","合规材料"]', '北京总部 8 层', 'wu.ting@example.com', 1),
  ('USR-010', 'zheng_kai', '郑凯', 'hr', 1, 'active', 'DEPT-HR', 'HR 主管', '["员工异动","审批管理"]', '北京总部 8 层', 'zheng.kai@example.com', 1),
  ('EMP-011', NULL, '何静', NULL, 0, NULL, 'DEPT-HR', '员工服务专员', '["劳动合同","员工证明"]', '北京总部 8 层', 'he.jing@example.com', 1),
  ('EMP-012', NULL, '林峰', NULL, 0, NULL, 'DEPT-IT', '账号管理员', '["账号开通","权限申请","密码重置"]', '北京总部 10 层', 'lin.feng@example.com', 1),
  ('EMP-013', NULL, '郭强', NULL, 0, NULL, 'DEPT-IT', '网络工程师', '["办公网络","VPN","无线网络"]', '北京总部 10 层', 'guo.qiang@example.com', 1),
  ('EMP-014', NULL, '唐雪', NULL, 0, NULL, 'DEPT-FINANCE', '费用审核专员', '["费用报销","差旅费用","发票审核"]', '北京总部 9 层', 'tang.xue@example.com', 1),
  ('EMP-015', NULL, '许晨', NULL, 0, NULL, 'DEPT-FINANCE', '付款专员', '["付款进度","供应商付款"]', '北京总部 9 层', 'xu.chen@example.com', 1),
  ('EMP-016', NULL, '高远', NULL, 0, NULL, 'DEPT-PRODUCT', '产品经理', '["产品规划","需求评审"]', '北京总部 10 层', 'gao.yuan@example.com', 1),
  ('EMP-017', NULL, '罗兰', NULL, 0, NULL, 'DEPT-PRODUCT', '交互设计师', '["交互原型","设计规范"]', '北京总部 10 层', 'luo.lan@example.com', 1),
  ('EMP-018', NULL, '曹宇', NULL, 0, NULL, 'DEPT-SALES', '销售运营专员', '["商务报价","销售数据"]', '上海研发中心 5 层', 'cao.yu@example.com', 1),
  ('EMP-019', NULL, '马莉', NULL, 0, NULL, 'DEPT-SALES', '商务经理', '["合同跟进","客户沟通"]', '上海研发中心 5 层', 'ma.li@example.com', 1),
  ('EMP-020', NULL, '杜鹏', NULL, 0, NULL, 'DEPT-RND', '技术负责人', '["系统架构","技术评审"]', '上海研发中心 6 层', 'du.peng@example.com', 1),
  ('EMP-021', NULL, '叶青', NULL, 0, NULL, 'DEPT-RND', '测试工程师', '["质量测试","缺陷管理"]', '上海研发中心 6 层', 'ye.qing@example.com', 1),
  ('EMP-022', NULL, '程晨', NULL, 0, NULL, 'DEPT-MARKETING', '品牌经理', '["品牌宣传","媒体合作"]', '北京总部 9 层', 'cheng.chen@example.com', 1),
  ('EMP-023', NULL, '袁欣', NULL, 0, NULL, 'DEPT-CS', '客户成功经理', '["客户反馈","续约跟进"]', '上海研发中心 5 层', 'yuan.xin@example.com', 1),
  ('EMP-024', NULL, '潘宁', NULL, 0, NULL, 'DEPT-LEGAL', '法务经理', '["合同审核","知识产权"]', '北京总部 8 层', 'pan.ning@example.com', 1),
  ('EMP-025', NULL, '秦涛', NULL, 0, NULL, 'DEPT-ADMIN', '行政专员', '["门禁卡","工位","办公用品"]', '北京总部 8 层', 'qin.tao@example.com', 1),
  ('EMP-026', NULL, '宋妍', NULL, 0, NULL, 'DEPT-HR', '员工关系经理', '["员工关系","内部调查"]', '北京总部 8 层', NULL, 0),
  ('EMP-027', NULL, '魏然', NULL, 0, NULL, 'DEPT-LEGAL', '合规专员', '["内部合规","法律风险"]', '北京总部 8 层', NULL, 0);

INSERT IGNORE INTO devices (device_id, name, category, description, eligible_roles, eligible_department_ids, max_quantity_per_request, request_requirements, is_requestable) VALUES
  ('DEV-LAPTOP-STD', '标准办公笔记本', '电脑', '适用于日常办公、文档处理和在线会议。', '["employee","hr"]', '[]', 1, '填写主要工作用途。', 1),
  ('DEV-LAPTOP-PRO', '高性能开发笔记本', '电脑', '适用于软件开发、数据处理和复杂设计任务。', '["employee"]', '["DEPT-RND","DEPT-IT","DEPT-PRODUCT"]', 1, '说明岗位、开发工具或性能需求。', 1),
  ('DEV-MONITOR-24', '24 英寸显示器', '显示设备', '适用于需要双屏办公的岗位。', '["employee","hr"]', '[]', 2, '说明双屏办公场景。', 1),
  ('DEV-MONITOR-27', '27 英寸高分辨率显示器', '显示设备', '适用于设计、研发和内容制作。', '["employee"]', '["DEPT-PRODUCT","DEPT-RND","DEPT-MARKETING"]', 1, '说明设计、研发或内容制作需求。', 1),
  ('DEV-HEADSET', '办公耳机', '会议设备', '适用于线上会议和客户沟通。', '["employee","hr"]', '[]', 1, '说明会议或客户沟通用途。', 1),
  ('DEV-KEYBOARD-MOUSE', '键盘鼠标套装', '办公外设', '适用于固定工位的日常办公。', '["employee","hr"]', '[]', 1, '说明新员工配发或原设备故障情况。', 1),
  ('DEV-WEBCAM', '高清摄像头', '会议设备', '适用于远程培训、客户演示和线上会议。', '["employee","hr"]', '[]', 1, '说明远程会议或演示频率。', 1),
  ('DEV-DRAWING-TABLET', '绘图板', '设计设备', '适用于交互设计、视觉设计和内容制作。', '["employee"]', '["DEPT-PRODUCT","DEPT-MARKETING"]', 1, '说明具体设计任务。', 1),
  ('DEV-MOBILE-TEST', '移动测试设备', '测试设备', '适用于移动端产品开发和兼容性测试。', '["employee"]', '["DEPT-RND","DEPT-PRODUCT"]', 2, '填写测试项目和预计使用周期。', 1),
  ('DEV-DOCK', '笔记本扩展坞', '办公外设', '用于连接显示器、网线和多种外设。', '["employee","hr"]', '[]', 1, '说明需要连接的设备。', 1),
  ('DEV-DESK-STAND', '升降桌', '办公家具', '当前教学目录中暂不开放个人申请。', '[]', '[]', 0, '不可申请。', 0),
  ('DEV-ERGONOMIC-CHAIR', '人体工学椅', '办公家具', '由行政部统一配置，不接受个人设备申请。', '[]', '[]', 0, '不可申请。', 0);

INSERT IGNORE INTO device_requests (request_id, applicant_user_id, device_id, quantity, reason, status, requested_at, reviewer_user_id, reviewed_at, review_comment) VALUES
  ('REQ-2026-0001', 'USR-001', 'DEV-MONITOR-24', 1, '产品设计评审时需要双屏查看原型和需求文档。', 'pending', '2026-09-15 01:30:00', NULL, NULL, NULL),
  ('REQ-2026-0002', 'USR-002', 'DEV-LAPTOP-STD', 1, '希望额外申请一台笔记本在家中备用。', 'rejected', '2026-09-12 06:10:00', 'USR-003', '2026-09-13 02:20:00', '请补充现有设备无法满足工作的具体原因。'),
  ('REQ-2026-0003', 'USR-001', 'DEV-HEADSET', 1, '日常需要参加远程产品评审会议。', 'approved', '2026-09-10 03:00:00', 'USR-003', '2026-09-10 08:40:00', '申请用途符合办公需要，同意申请。'),
  ('REQ-2026-0004', 'USR-004', 'DEV-LAPTOP-PRO', 1, '需要运行本地开发环境和虚拟机进行账号系统维护。', 'approved', '2026-09-08 02:15:00', 'USR-010', '2026-09-08 07:30:00', '岗位和性能需求符合申请条件。'),
  ('REQ-2026-0005', 'USR-005', 'DEV-MONITOR-24', 1, '需要同时核对报销系统和电子发票。', 'approved', '2026-09-07 01:40:00', 'USR-003', '2026-09-07 06:00:00', '符合双屏办公需求。'),
  ('REQ-2026-0006', 'USR-006', 'DEV-LAPTOP-PRO', 1, '需要运行容器、数据库和本地调试环境。', 'pending', '2026-09-16 02:05:00', NULL, NULL, NULL),
  ('REQ-2026-0007', 'USR-007', 'DEV-WEBCAM', 1, '每周需要录制产品介绍和参加线上活动。', 'pending', '2026-09-16 05:20:00', NULL, NULL, NULL),
  ('REQ-2026-0008', 'USR-008', 'DEV-HEADSET', 1, '需要与客户进行远程沟通。', 'rejected', '2026-09-05 03:30:00', 'USR-010', '2026-09-05 08:10:00', '员工已有可用耳机，请说明更换原因。'),
  ('REQ-2026-0009', 'USR-009', 'DEV-MONITOR-24', 1, '需要同时查看合同正文和修改意见。', 'approved', '2026-09-04 01:20:00', 'USR-003', '2026-09-04 05:45:00', '符合合同审核工作需要。'),
  ('REQ-2026-0010', 'USR-004', 'DEV-DOCK', 1, '需要连接显示器、网线和测试设备。', 'pending', '2026-09-16 08:00:00', NULL, NULL, NULL),
  ('REQ-2026-0011', 'USR-005', 'DEV-KEYBOARD-MOUSE', 1, '新员工固定工位需要基础办公外设。', 'approved', '2026-09-03 02:00:00', 'USR-010', '2026-09-03 03:20:00', '属于新员工基础办公配置。'),
  ('REQ-2026-0012', 'USR-007', 'DEV-MONITOR-27', 1, '用于日常文档编辑。', 'rejected', '2026-09-02 06:40:00', 'USR-003', '2026-09-02 09:10:00', '请补充内容制作或设计工作的具体需求。'),
  ('REQ-2026-0013', 'USR-002', 'DEV-HEADSET', 1, '需要频繁参加客户线上会议。', 'approved', '2026-09-01 01:50:00', 'USR-010', '2026-09-01 05:15:00', '符合客户沟通需求。'),
  ('REQ-2026-0014', 'USR-006', 'DEV-MOBILE-TEST', 2, '用于移动端功能和兼容性测试，预计使用三个月。', 'approved', '2026-08-29 02:30:00', 'USR-003', '2026-08-29 08:00:00', '测试项目和使用周期说明完整。'),
  ('REQ-2026-0015', 'USR-001', 'DEV-WEBCAM', 1, '用于远程用户访谈和产品评审。', 'pending', '2026-09-17 01:10:00', NULL, NULL, NULL),
  ('REQ-2026-0016', 'USR-008', 'DEV-LAPTOP-STD', 1, '新员工入职需要标准办公电脑。', 'approved', '2026-08-28 01:00:00', 'USR-010', '2026-08-28 02:30:00', '属于新员工标准设备。'),
  ('REQ-2026-0017', 'USR-009', 'DEV-KEYBOARD-MOUSE', 1, '固定工位缺少键盘鼠标套装。', 'pending', '2026-09-17 02:25:00', NULL, NULL, NULL),
  ('REQ-2026-0018', 'USR-002', 'DEV-DOCK', 1, '希望在家中连接个人显示器。', 'rejected', '2026-08-27 07:00:00', 'USR-003', '2026-08-28 01:20:00', '当前理由不属于公司工位的办公需求。');

COMMIT;

-- 执行完成后直接返回四组基础数据数量，便于确认初始化结果。
SELECT 'departments' AS table_name, COUNT(*) AS row_count FROM departments
UNION ALL
SELECT 'users', COUNT(*) FROM users
UNION ALL
SELECT 'devices', COUNT(*) FROM devices
UNION ALL
SELECT 'device_requests', COUNT(*) FROM device_requests;


-- ============================================================================
-- 以下为【本项目本地增量】，不属于 Week16 Day05 课件原文。
-- 依据：docs/plans/状态持久化升级计划.md 决策 D1 —— 项目 src/data/day05_device_requests.json
--       实有 19 条申请，而课件 SQL 只灌 18 条；多出的 REQ-2026-0019 是真实业务数据
--       （非测试残留），补插不丢。
-- 时间口径：JSON 存本地时间（+08:00），入库统一转 UTC，与课件的 18 条保持一致
--       （已用两组数据核对：2026-08-27T15:00:00+08:00 -> 2026-08-27 07:00:00；
--         2026-10-09T17:49:28+08:00 -> 2026-10-09 09:49:28）。
-- 幂等：INSERT IGNORE —— 重复执行不会覆盖同主键数据。
-- ============================================================================

INSERT IGNORE INTO device_requests
  (request_id, applicant_user_id, device_id, quantity, reason, status,
   requested_at, reviewer_user_id, reviewed_at, review_comment)
VALUES
  ('REQ-2026-0019', 'USR-001', 'DEV-MONITOR-24', 1,
   '开发时需要一边进行开发工作，一边查看资料/文档，用于双屏办公。',
   'approved', '2026-10-09 09:49:28', 'USR-003', '2026-10-09 09:52:39', '同意');

-- 复算：期望 departments 10 / users 27 / devices 12 / device_requests 19
--       （课件 18 + 本项目本地 1）
SELECT 'departments' AS table_name, COUNT(*) AS row_count FROM departments
UNION ALL
SELECT 'users', COUNT(*) FROM users
UNION ALL
SELECT 'devices', COUNT(*) FROM devices
UNION ALL
SELECT 'device_requests', COUNT(*) FROM device_requests;

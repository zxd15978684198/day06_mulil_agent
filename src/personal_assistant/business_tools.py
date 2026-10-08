"""教学登录、可信运行上下文与业务 Tool。

本模块是项目的业务权限闸门，全部身份判断都在这里执行：

- ``RunContext`` 由 ``login_as()`` 从 ``data/day05_users.json`` 构造，应用注入；
- ``ROLE_PERMISSIONS`` 是课件 Day05 §2.3 的角色权限矩阵；
- 七个业务 Tool 一律先取 ``runtime.context``，再判断权限。

进度：
* **P0 已完成**：``RunContext`` 与 ``ROLE_PERMISSIONS``；
* **P4 已完成**：检索 Tool —— 实现放在 ``knowledge_base``（K8 的检索逻辑与
  Chroma 都在那边），这里按 §4.2 的要求把名字 ``search_company_knowledge``
  导出，使 ``multi_agent`` 的 import 块（9 个名字）成立；
* **P5 待做**：``login_as()`` 与其余 6 个业务 Tool。
"""

from __future__ import annotations

from dataclasses import dataclass

# §4.2 硬约束：multi_agent.py 从本模块导入 9 个名字。检索 Tool 的实现与
# Chroma 访问都在 knowledge_base，这里只做名字导出（工具名已由
# @tool("search_company_knowledge") 固定，函数名保持 knowledge_base.search_knowledge）。
from personal_assistant.knowledge_base import search_knowledge as search_company_knowledge

__all__ = [
    "RunContext",
    "ROLE_PERMISSIONS",
    "search_company_knowledge",
]


@dataclass(frozen=True)
class RunContext:
    """由教学登录创建、由应用注入的可信运行上下文。"""

    user_id: str
    username: str
    display_name: str
    role: str
    department_id: str


# 课件 Day05 §2.3 的权限矩阵。用户记录只保存 role，不为每个用户重复保存权限列表。
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "employee": {
        "read_public_knowledge",  # 检索公司内公开知识文档
        "read_public_directory",  # 查询部门和公开员工目录
        "read_device_catalog",  # 查询可申请的设备
        "create_device_request",  # 创建设备申请
        "read_own_device_requests",  # 查看本人提交的申请
    },
    "hr": {
        "read_public_knowledge",  # 检索公司内公开知识文档
        "read_hr_knowledge",  # 检索 HR 专属文档
        "read_public_directory",  # 查询部门和公开员工目录
        "read_device_catalog",  # 查询设备目录
        "read_all_device_requests",  # 查看全部申请，其中也包括 HR 本人的申请
        "review_device_requests",  # 批准或拒绝设备申请
    },
}

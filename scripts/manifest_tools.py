"""`release/agent_versions.json` 的共享工具。

被 `validate_version_manifest.py` 与 `update_manifest_hashes.py` 共同使用，
保证「算摘要」和「校验摘要」用的是同一套算法 —— 两边各写一份迟早会漂移。

设计要点（对应 docs/Day01_可复现工程与CI.md §7）：

* 只读文件、不导入业务模块：`multi_agent.py` 导入期会连接数据库配置，
  校验器不能为了取一段 Prompt 文本而把整个应用启动起来，所以用 AST；
* 清单里的相对路径一律做越界检查（§7.5），不信任清单内容；
* Prompt 摘要取的是**恰好那段常量文本**，不是整个 `.py` 文件 ——
  否则改一行无关代码也会让 Prompt 证据失效。
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

BLOCK_SIZE = 64 * 1024


class ManifestToolError(ValueError):
    """清单或其引用的文件不满足约束。"""


def sha256_file(path: Path) -> str:
    """分块读取，避免大文件一次性进入内存（Day01 §7.4）。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def prompt_digest(text: str) -> str:
    """Prompt 常量文本的摘要；固定 UTF-8，跨平台可复现。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_join(project_root: Path, relative: str) -> Path:
    """把清单中的相对路径解析到项目内；`../` 越界直接报错。"""

    if not isinstance(relative, str) or not relative.strip():
        raise ManifestToolError("路径字段必须是非空字符串")
    candidate = (project_root / relative).resolve()
    root = project_root.resolve()
    if not candidate.is_relative_to(root):
        raise ManifestToolError(f"路径越过项目根目录：{relative}")
    return candidate


def extract_prompt_constants(source: Path, names: list[str]) -> dict[str, str]:
    """从源码里按名字取出模块级字符串常量，**不导入模块**。

    只认 `NAME = "..."` 这种单目标赋值；相邻字符串字面量会由 Python 的
    解析器自动折叠成一个常量，所以多行书写的 Prompt 不影响结果。
    """

    tree = ast.parse(source.read_text(encoding="utf-8"))
    wanted = set(names)
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in wanted:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str):
            values[target.id] = value

    missing = wanted - values.keys()
    if missing:
        raise ManifestToolError(
            f"{source} 中找不到 Prompt 常量：{', '.join(sorted(missing))}"
        )
    return values


def aggregate_knowledge_digest(root: Path) -> tuple[str, int]:
    """知识库内容摘要：按相对路径排序后聚合每个文件的 SHA-256。

    算法固定为「相对路径 + NUL + 文件摘要 + 换行」，路径用 `/` 分隔，
    使 Windows 与 Linux 得到同一个结果。返回值是 `(摘要, 文件数)`。
    注意它只覆盖知识文件本身；向量索引另有自己的摘要。
    """

    digest = hashlib.sha256()
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

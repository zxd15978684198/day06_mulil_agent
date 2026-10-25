#!/usr/bin/env python3
"""校验 `release/agent_versions.json`（Day01 §8.8 的自定义门禁）。

它检查的不是“JSON 语法对不对”，而是**发布证据是否还成立**：

1. 清单能解析，顶层字段与九类 Agent 组件齐全；
2. 清单中的相对路径都位于项目根目录内，且文件存在；
3. Prompt 常量文本、锁文件、知识库、索引、评测集的摘要与清单一致；
4. 派生字段（知识文档数、索引 chunk 数、embedding 模型）与源文件一致。

发现摘要不一致时**不要直接跑更新脚本**：先审查改动、确认评测通过，
再更新组件版本并重算摘要（Day01 §7.3）。

用法：
    uv run python scripts/validate_version_manifest.py
    uv run python scripts/validate_version_manifest.py --manifest release/agent_versions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from manifest_tools import (
    ManifestToolError,
    aggregate_knowledge_digest,
    extract_prompt_constants,
    load_json,
    prompt_digest,
    safe_join,
    sha256_file,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_ROOT / "release" / "agent_versions.json"

SCHEMA_VERSION = "1.0"

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "service",
    "runtime",
    "agent",
    "embedding",
    "knowledge",
    "index",
    "evaluation",
)

# 九类 Agent 组件：Prompt、模型、Tool、Skill、Harness、Embedding、知识库、索引、评测集。
REQUIRED_AGENT_COMPONENTS = ("prompt", "chat_model", "tools", "skills", "harness")

VALID_TOOL_LAYERS = {"business", "delegation"}
VALID_TOOL_RISKS = {"read-only", "write"}


# ---------------------------------------------------------------------------
# 基础检查
# ---------------------------------------------------------------------------


def _require_object(
    parent: dict[str, Any], key: str, where: str, errors: list[str]
) -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        errors.append(f"{where}.{key} 缺失或不是对象")
        return {}
    return value


def _require_fields(
    obj: dict, fields: tuple[str, ...], where: str, errors: list[str]
) -> None:
    for field in fields:
        value = obj.get(field)
        if value is None or value == "" or value == []:
            errors.append(f"{where}.{field} 缺失或为空")


def _check_path(
    project_root: Path,
    relative: Any,
    where: str,
    errors: list[str],
) -> Path | None:
    """越界/不存在都记为错误；返回可继续检查摘要的路径。"""

    try:
        path = safe_join(project_root, relative)
    except ManifestToolError as exc:
        errors.append(f"{where}: {exc}")
        return None
    if not path.is_file():
        errors.append(f"{where}: 文件不存在：{relative}")
        return None
    return path


def _check_hash(
    path: Path,
    expected: Any,
    where: str,
    errors: list[str],
) -> bool:
    if not isinstance(expected, str) or not expected:
        errors.append(f"{where} 缺少摘要")
        return False
    actual = sha256_file(path)
    if actual != expected:
        errors.append(
            f"{where}: 摘要不一致（清单 {expected[:12]}…，实际 {actual[:12]}…）"
        )
        return False
    return True


# ---------------------------------------------------------------------------
# 各组件检查
# ---------------------------------------------------------------------------


def _check_prompt(project_root: Path, agent: dict, errors: list[str]) -> None:
    prompt = _require_object(agent, "prompt", "agent", errors)
    if not prompt:
        return
    _require_fields(prompt, ("version", "source", "items"), "agent.prompt", errors)

    source_path = _check_path(
        project_root, prompt.get("source"), "agent.prompt.source", errors
    )
    items = prompt.get("items")
    if not isinstance(items, list) or not items:
        errors.append("agent.prompt.items 必须是非空列表")
        return

    names: list[str] = []
    for index, item in enumerate(items):
        where = f"agent.prompt.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} 必须是对象")
            continue
        _require_fields(item, ("name", "constant", "sha256"), where, errors)
        constant = item.get("constant")
        if isinstance(constant, str):
            names.append(constant)

    if source_path is None or not names:
        return

    try:
        constants = extract_prompt_constants(source_path, names)
    except (ManifestToolError, SyntaxError, OSError) as exc:
        errors.append(f"无法从 {prompt.get('source')} 读取 Prompt 常量：{exc}")
        return

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        constant = item.get("constant")
        expected = item.get("sha256")
        if not isinstance(constant, str) or constant not in constants:
            continue
        if not isinstance(expected, str) or not expected:
            continue
        actual = prompt_digest(constants[constant])
        if actual != expected:
            errors.append(
                f"agent.prompt.items[{index}]（{constant}）: 摘要不一致"
                f"（清单 {expected[:12]}…，实际 {actual[:12]}…）"
            )


def _check_tools(agent: dict, errors: list[str]) -> None:
    tools = _require_object(agent, "tools", "agent", errors)
    if not tools:
        return
    _require_fields(tools, ("version", "items"), "agent.tools", errors)

    items = tools.get("items")
    if not isinstance(items, list) or not items:
        errors.append("agent.tools.items 必须是非空列表")
        return

    names: set[str] = set()
    for index, item in enumerate(items):
        where = f"agent.tools.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} 必须是对象")
            continue
        _require_fields(item, ("name", "layer", "risk"), where, errors)
        name = item.get("name")
        if isinstance(name, str):
            if name in names:
                errors.append(f"{where}: Tool 名称重复：{name}")
            names.add(name)
        if item.get("layer") not in VALID_TOOL_LAYERS:
            errors.append(f"{where}.layer 必须是 {sorted(VALID_TOOL_LAYERS)} 之一")
        if item.get("risk") not in VALID_TOOL_RISKS:
            errors.append(f"{where}.risk 必须是 {sorted(VALID_TOOL_RISKS)} 之一")
        if (
            item.get("risk") == "write"
            and item.get("confirmation_required") is not True
        ):
            errors.append(f"{where}: 写操作必须声明 confirmation_required=true")


def _check_skills(agent: dict, errors: list[str]) -> None:
    skills = _require_object(agent, "skills", "agent", errors)
    if not skills:
        return
    _require_fields(skills, ("version",), "agent.skills", errors)
    if not isinstance(skills.get("items"), list):
        errors.append("agent.skills.items 必须是列表（没有 Skill 时写 []）")


def _check_harness(agent: dict, errors: list[str]) -> None:
    harness = _require_object(agent, "harness", "agent", errors)
    if not harness:
        return
    _require_fields(
        harness,
        ("version", "stop_policy", "confirmation_policy"),
        "agent.harness",
        errors,
    )


def _check_embedding(manifest: dict, errors: list[str]) -> None:
    embedding = _require_object(manifest, "embedding", "顶层", errors)
    if not embedding:
        return
    _require_fields(
        embedding,
        ("version", "model_id", "provider"),
        "embedding",
        errors,
    )


def _check_knowledge(project_root: Path, manifest: dict, errors: list[str]) -> None:
    knowledge = _require_object(manifest, "knowledge", "顶层", errors)
    if not knowledge:
        return
    _require_fields(
        knowledge,
        ("version", "manifest", "manifest_sha256", "content_sha256", "document_count"),
        "knowledge",
        errors,
    )

    manifest_path = _check_path(
        project_root, knowledge.get("manifest"), "knowledge.manifest", errors
    )
    if manifest_path is None:
        return
    _check_hash(
        manifest_path,
        knowledge.get("manifest_sha256"),
        "knowledge.manifest_sha256",
        errors,
    )

    try:
        data = load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"knowledge.manifest 无法解析：{exc}")
        return

    documents = data.get("documents")
    if not isinstance(documents, list):
        errors.append("knowledge.manifest 中缺少 documents 列表")
        return

    expected_count = knowledge.get("document_count")
    if expected_count != len(documents):
        errors.append(
            f"knowledge.document_count 与源清单不一致"
            f"（清单 {expected_count!r}，实际 {len(documents)}）"
        )

    actual_digest, file_count = aggregate_knowledge_digest(manifest_path.parent)
    if knowledge.get("content_sha256") != actual_digest:
        errors.append(
            "knowledge.content_sha256: 知识库内容摘要不一致"
            f"（清单 {str(knowledge.get('content_sha256'))[:12]}…，实际 {actual_digest[:12]}…）"
        )
    if "file_count" in knowledge and knowledge.get("file_count") != file_count:
        errors.append(
            f"knowledge.file_count 不一致（清单 {knowledge.get('file_count')!r}，实际 {file_count}）"
        )


def _check_index(project_root: Path, manifest: dict, errors: list[str]) -> None:
    index = _require_object(manifest, "index", "顶层", errors)
    if not index:
        return
    _require_fields(
        index,
        ("version", "path", "sha256", "collection_name", "chunk_count"),
        "index",
        errors,
    )

    index_path = _check_path(project_root, index.get("path"), "index.path", errors)
    if index_path is None:
        return
    _check_hash(index_path, index.get("sha256"), "index.sha256", errors)

    try:
        data = load_json(index_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"index.path 无法解析：{exc}")
        return

    comparisons = (
        ("collection_name", data.get("collection_name")),
        ("chunk_count", data.get("chunk_count")),
        ("embedding_model", data.get("embedding_model")),
        ("chunk_size", (data.get("chunking") or {}).get("chunk_size")),
        ("chunk_overlap", (data.get("chunking") or {}).get("chunk_overlap")),
        ("built_at", data.get("built_at")),
    )
    for key, actual in comparisons:
        if key in index and actual is not None and index.get(key) != actual:
            errors.append(
                f"index.{key} 与 index_manifest.json 不一致"
                f"（清单 {index.get(key)!r}，实际 {actual!r}）"
            )

    embedding = manifest.get("embedding")
    if isinstance(embedding, dict) and data.get("embedding_model"):
        if embedding.get("model_id") != data.get("embedding_model"):
            errors.append(
                "embedding.model_id 与索引构建时使用的模型不一致："
                f"{embedding.get('model_id')!r} != {data.get('embedding_model')!r}"
            )


def _check_evaluation(project_root: Path, manifest: dict, errors: list[str]) -> None:
    evaluation = _require_object(manifest, "evaluation", "顶层", errors)
    if not evaluation:
        return
    _require_fields(evaluation, ("version", "path", "sha256"), "evaluation", errors)

    eval_path = _check_path(
        project_root, evaluation.get("path"), "evaluation.path", errors
    )
    if eval_path is not None:
        _check_hash(eval_path, evaluation.get("sha256"), "evaluation.sha256", errors)

    if "spec" in evaluation:
        spec_path = _check_path(
            project_root, evaluation.get("spec"), "evaluation.spec", errors
        )
        if spec_path is not None:
            _check_hash(
                spec_path,
                evaluation.get("spec_sha256"),
                "evaluation.spec_sha256",
                errors,
            )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def validate_manifest(project_root: Path, manifest_path: Path) -> list[str]:
    """返回全部错误；空列表表示通过。"""

    errors: list[str] = []

    try:
        manifest = load_json(manifest_path)
    except FileNotFoundError:
        return [f"清单不存在：{manifest_path}"]
    except json.JSONDecodeError as exc:
        return [f"清单不是合法 JSON：{exc}"]
    except OSError as exc:
        return [f"清单无法读取：{exc}"]

    if not isinstance(manifest, dict):
        return ["清单顶层必须是 JSON 对象"]

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version 必须是 {SCHEMA_VERSION!r}，实际 {manifest.get('schema_version')!r}"
        )

    for key in REQUIRED_TOP_LEVEL:
        if key not in manifest:
            errors.append(f"缺少顶层字段：{key}")

    service = _require_object(manifest, "service", "顶层", errors)
    _require_fields(service, ("name", "version", "git_commit"), "service", errors)

    runtime = _require_object(manifest, "runtime", "顶层", errors)
    _require_fields(
        runtime, ("python", "uv", "lockfile", "lockfile_sha256"), "runtime", errors
    )
    lockfile = _check_path(
        project_root, runtime.get("lockfile"), "runtime.lockfile", errors
    )
    if lockfile is not None:
        _check_hash(
            lockfile, runtime.get("lockfile_sha256"), "runtime.lockfile_sha256", errors
        )

    agent = _require_object(manifest, "agent", "顶层", errors)
    for component in REQUIRED_AGENT_COMPONENTS:
        if component not in agent:
            errors.append(f"缺少 Agent 组件：agent.{component}")

    if agent:
        _check_prompt(project_root, agent, errors)
        chat_model = _require_object(agent, "chat_model", "agent", errors)
        _require_fields(
            chat_model, ("provider", "model_id"), "agent.chat_model", errors
        )
        _check_tools(agent, errors)
        _check_skills(agent, errors)
        _check_harness(agent, errors)

    _check_embedding(manifest, errors)
    _check_knowledge(project_root, manifest, errors)
    _check_index(project_root, manifest, errors)
    _check_evaluation(project_root, manifest, errors)

    return errors


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp936，中文提示会变成乱码；显式按 UTF-8 输出。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="校验 Agent 版本清单")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="清单路径（默认 release/agent_versions.json）",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录（默认脚本上一级）",
    )
    args = parser.parse_args(argv)

    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = args.project_root / manifest_path

    errors = validate_manifest(args.project_root.resolve(), manifest_path)
    if errors:
        print(f"版本清单校验失败：{len(errors)} 项问题")
        for error in errors:
            print(f"  [FAIL] {error}")
        print(
            "\n先审查改动；确认后再更新组件版本并运行 scripts/update_manifest_hashes.py。"
        )
        return 1

    manifest = load_json(manifest_path)
    service = manifest.get("service", {})
    knowledge = manifest.get("knowledge", {})
    index = manifest.get("index", {})
    print("[OK] 版本清单校验通过")
    print(
        f"     服务：{service.get('name')} {service.get('version')} "
        f"@ {str(service.get('git_commit'))[:12]}"
    )
    print(
        f"     知识：{knowledge.get('document_count')} 个文档 / "
        f"{index.get('chunk_count')} 个 chunk / {index.get('collection_name')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

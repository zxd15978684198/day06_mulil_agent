#!/usr/bin/env python3
"""按当前仓库内容重算 `release/agent_versions.json` 的摘要字段。

它**只更新可计算的事实**：文件摘要、Prompt 文本摘要、知识库聚合摘要、
索引/知识文档数、Python/uv/锁文件与 Git Commit。

它**不修改**需要人判断的字段：组件 `version`、聊天模型、Tool 清单、
Harness 策略。这些字段必须由人在审查改动后手动更新（Day01 §7.3）——
先跑本脚本再补版本号，等于把未审核的改动“合法化”。

用法：
    uv run python scripts/update_manifest_hashes.py
    uv run python scripts/update_manifest_hashes.py --dry-run   # 只看会改什么
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from manifest_tools import (
    aggregate_knowledge_digest,
    extract_prompt_constants,
    load_json,
    prompt_digest,
    safe_join,
    sha256_file,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = PROJECT_ROOT / "release" / "agent_versions.json"


def _git_commit(project_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _uv_version() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    return parts[1] if len(parts) >= 2 else None


def _set(target: dict, key: str, value, changes: list[str], where: str) -> None:
    if target.get(key) != value:
        changes.append(f"{where}.{key}: {target.get(key)!r} -> {value!r}")
        target[key] = value


def update_manifest(project_root: Path, manifest_path: Path) -> list[str]:
    """原地更新清单并返回变更列表；调用方决定是否写回。"""

    manifest = load_json(manifest_path)
    changes: list[str] = []

    commit = _git_commit(project_root)
    if commit:
        _set(
            manifest.setdefault("service", {}), "git_commit", commit, changes, "service"
        )

    runtime = manifest.setdefault("runtime", {})
    _set(runtime, "python", platform.python_version(), changes, "runtime")
    uv_version = _uv_version()
    if uv_version:
        _set(runtime, "uv", uv_version, changes, "runtime")
    version_file = project_root / ".python-version"
    if version_file.is_file():
        _set(
            runtime,
            "python_version_file",
            version_file.read_text(encoding="utf-8").strip(),
            changes,
            "runtime",
        )

    lockfile = runtime.get("lockfile")
    if lockfile:
        _set(
            runtime,
            "lockfile_sha256",
            sha256_file(safe_join(project_root, lockfile)),
            changes,
            "runtime",
        )

    prompt = manifest.get("agent", {}).get("prompt", {})
    if prompt.get("source") and prompt.get("items"):
        source = safe_join(project_root, prompt["source"])
        names = [item["constant"] for item in prompt["items"]]
        constants = extract_prompt_constants(source, names)
        for index, item in enumerate(prompt["items"]):
            _set(
                item,
                "sha256",
                prompt_digest(constants[item["constant"]]),
                changes,
                f"agent.prompt.items[{index}]",
            )

    knowledge = manifest.get("knowledge", {})
    if knowledge.get("manifest"):
        manifest_path_obj = safe_join(project_root, knowledge["manifest"])
        _set(
            knowledge,
            "manifest_sha256",
            sha256_file(manifest_path_obj),
            changes,
            "knowledge",
        )
        source_data = load_json(manifest_path_obj)
        documents = source_data.get("documents")
        if isinstance(documents, list):
            _set(knowledge, "document_count", len(documents), changes, "knowledge")
        content_digest, file_count = aggregate_knowledge_digest(
            manifest_path_obj.parent
        )
        _set(knowledge, "content_sha256", content_digest, changes, "knowledge")
        if "file_count" in knowledge:
            _set(knowledge, "file_count", file_count, changes, "knowledge")

    index = manifest.get("index", {})
    if index.get("path"):
        index_path = safe_join(project_root, index["path"])
        _set(index, "sha256", sha256_file(index_path), changes, "index")
        index_data = load_json(index_path)
        for key in ("collection_name", "chunk_count", "embedding_model", "built_at"):
            if index_data.get(key) is not None:
                _set(index, key, index_data[key], changes, "index")
        chunking = index_data.get("chunking") or {}
        for key in ("chunk_size", "chunk_overlap"):
            if chunking.get(key) is not None and key in index:
                _set(index, key, chunking[key], changes, "index")

    evaluation = manifest.get("evaluation", {})
    if evaluation.get("path"):
        _set(
            evaluation,
            "sha256",
            sha256_file(safe_join(project_root, evaluation["path"])),
            changes,
            "evaluation",
        )
    if evaluation.get("spec"):
        _set(
            evaluation,
            "spec_sha256",
            sha256_file(safe_join(project_root, evaluation["spec"])),
            changes,
            "evaluation",
        )

    # 只有确实要改内容时才刷新生成时间，否则每次运行都不幂等。
    if changes:
        manifest["generated_at"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )

    manifest["_changes"] = changes  # 临时携带，写回前删除
    return manifest


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp936，中文提示会变成乱码；显式按 UTF-8 输出。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="更新 Agent 版本清单的摘要字段")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写文件")
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path

    manifest = update_manifest(project_root, manifest_path)
    changes = manifest.pop("_changes", [])

    if not changes:
        print("清单已是最新，无需更新。")
        return 0

    if args.dry_run:
        print(f"将更新 {len(changes)} 个字段（dry-run，未写文件）：")
        for change in changes:
            print(f"  - {change}")
        return 0

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"已更新 {manifest_path.relative_to(project_root)}（{len(changes)} 个字段）："
    )
    for change in changes:
        print(f"  - {change}")
    print("\n下一步：审查 git diff；若组件语义已变，同步更新对应 version 字段。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

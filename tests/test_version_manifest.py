"""版本清单校验器的行为测试（对应 Day01 §8.7 要求的八类用例）。

这里不启动 Agent、不连数据库：校验器只读文件，**不应该**为了一段 Prompt
文本把整个应用导入起来。测试直接加载 `scripts/` 下的两个模块。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
MANIFEST_PATH = PROJECT_ROOT / "release" / "agent_versions.json"
INDEX_MANIFEST_PATH = PROJECT_ROOT / "src" / "vector_store" / "index_manifest.json"

sys.path.insert(0, str(SCRIPTS_DIR))

import validate_version_manifest as validator  # noqa: E402


@pytest.fixture
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _validate(
    tmp_path: Path, data: dict, *, allow_missing_index: bool = False
) -> list[str]:
    path = tmp_path / "agent_versions.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return validator.validate_manifest(
        PROJECT_ROOT, path, allow_missing_index=allow_missing_index
    )


@pytest.mark.skipif(
    not INDEX_MANIFEST_PATH.is_file(),
    reason="向量索引未构建；index_manifest.json 由 build_index.py 生成且不入库",
)
def test_current_manifest_passes() -> None:
    assert validator.validate_manifest(PROJECT_ROOT, MANIFEST_PATH) == []


def test_missing_index_manifest_can_be_allowed(tmp_path: Path, manifest: dict) -> None:
    manifest["index"]["path"] = "src/vector_store/missing_index_manifest.json"

    errors = _validate(tmp_path, manifest, allow_missing_index=True)

    assert not any("index.path" in error for error in errors)


def test_broken_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "agent_versions.json"
    path.write_text("{ not json", encoding="utf-8")

    errors = validator.validate_manifest(PROJECT_ROOT, path)

    assert any("不是合法 JSON" in error for error in errors)


def test_missing_top_level_field_is_reported(tmp_path: Path, manifest: dict) -> None:
    del manifest["agent"]

    errors = _validate(tmp_path, manifest)

    assert any("缺少顶层字段：agent" in error for error in errors)


def test_missing_agent_component_is_reported(tmp_path: Path, manifest: dict) -> None:
    del manifest["agent"]["harness"]

    errors = _validate(tmp_path, manifest)

    assert any("agent.harness" in error for error in errors)


def test_missing_file_is_reported(tmp_path: Path, manifest: dict) -> None:
    manifest["knowledge"]["manifest"] = "src/knowledge/does_not_exist.json"

    errors = _validate(tmp_path, manifest)

    assert any("文件不存在" in error for error in errors)


def test_path_escape_is_rejected(tmp_path: Path, manifest: dict) -> None:
    manifest["evaluation"]["path"] = "../../outside.py"

    errors = _validate(tmp_path, manifest)

    assert any("越过项目根目录" in error for error in errors)


def test_file_hash_mismatch_is_reported(tmp_path: Path, manifest: dict) -> None:
    manifest["evaluation"]["sha256"] = "0" * 64

    errors = _validate(tmp_path, manifest)

    assert any(
        "evaluation.sha256" in error and "摘要不一致" in error for error in errors
    )


def test_prompt_hash_mismatch_is_reported(tmp_path: Path, manifest: dict) -> None:
    manifest["agent"]["prompt"]["items"][0]["sha256"] = "0" * 64

    errors = _validate(tmp_path, manifest)

    assert any(
        "SUPERVISOR_PROMPT" in error and "摘要不一致" in error for error in errors
    )


def test_missing_prompt_constant_is_reported(tmp_path: Path, manifest: dict) -> None:
    manifest["agent"]["prompt"]["items"][0]["constant"] = "NOT_A_PROMPT"

    errors = _validate(tmp_path, manifest)

    assert any("找不到 Prompt 常量" in error for error in errors)


def test_knowledge_content_digest_mismatch_is_reported(
    tmp_path: Path, manifest: dict
) -> None:
    manifest["knowledge"]["content_sha256"] = "0" * 64

    errors = _validate(tmp_path, manifest)

    assert any("knowledge.content_sha256" in error for error in errors)


def test_write_tool_requires_confirmation(tmp_path: Path, manifest: dict) -> None:
    item = next(
        tool
        for tool in manifest["agent"]["tools"]["items"]
        if tool["name"] == "create_device_request"
    )
    item.pop("confirmation_required")

    errors = _validate(tmp_path, manifest)

    assert any("confirmation_required" in error for error in errors)

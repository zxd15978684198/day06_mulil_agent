"""knowledge_base 的纯函数测试（不加载 embedding / 不查 Chroma）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from personal_assistant import knowledge_base as kb


def test_new_session_id_shape() -> None:
    value = kb.new_session_id()
    assert value.startswith("day06-")
    assert len(value) == len("day06-") + 16


def test_join_line_cjk_and_space() -> None:
    assert kb._join_line([(0.0, 1.0, "年假"), (2.0, 3.0, "制度")]) == "年假制度"
    assert kb._join_line([(0.0, 1.0, "A"), (2.0, 3.0, "B")]) == "A B"


def test_split_blocks_keeps_tables_whole() -> None:
    splitter = kb._make_splitter()
    blocks = [
        kb.Block(text="第一段。第二段。", kind="prose"),
        kb.Block(text="| 列1 | 列2 |", kind="table"),
    ]

    chunks = kb._split_blocks(blocks, splitter)

    assert "| 列1 | 列2 |" in chunks
    assert all(chunk.strip() == chunk for chunk in chunks)


def test_chunk_metadata_inherits_document_fields_and_roles() -> None:
    entry = {
        "document_id": "KB-PUB-001",
        "title": "公司介绍",
        "path": "public/company.md",
        "version": "v1",
        "status": "active",
        "parser_mode": "text",
        "access_scope": "public",
    }
    parsed = kb.ParsedDocument(
        blocks=[kb.Block(text="x")],
        parser_mode_actual="text",
        is_machine_extracted=False,
    )

    metadata = kb._chunk_metadata(entry, parsed, 2, ["employee", "hr"])

    assert metadata["document_id"] == "KB-PUB-001"
    assert metadata["chunk_id"] == "KB-PUB-001#002"
    assert metadata["allow_employee"] is True
    assert metadata["allow_hr"] is True


def test_evidence_of_uses_metadata_and_score() -> None:
    hit = Document(
        page_content="正文",
        metadata={
            "document_id": "KB-PUB-001",
            "title": "公司介绍",
            "path": "public/company.md",
            "chunk_id": "KB-PUB-001#001",
            "access_scope": "public",
        },
    )

    evidence = kb._evidence_of(hit, 0.123456, 1)

    assert evidence["rank"] == 1
    assert evidence["document_id"] == "KB-PUB-001"
    assert evidence["score"] == 0.1235
    assert evidence["content"] == "正文"


def test_manifest_chunk_count_reads_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "index_manifest.json"
    manifest.write_text(json.dumps({"chunk_count": 35}), encoding="utf-8")
    monkeypatch.setattr(kb, "INDEX_MANIFEST_PATH", manifest)
    assert kb._manifest_chunk_count() == 35

    manifest.write_text("not-json", encoding="utf-8")
    assert kb._manifest_chunk_count() is None


def test_extra_headers_for_opencode_and_custom_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXTRA_HEADERS_JSON", raising=False)
    headers = kb._extra_headers_for("https://opencode.ai/v1", "session-1")
    assert headers["x-opencode-session"] == "session-1"
    assert "user-agent" in headers

    monkeypatch.setenv("EXTRA_HEADERS_JSON", '{"X-Test": "1"}')
    headers = kb._extra_headers_for("https://example.com", None)
    assert headers == {"X-Test": "1"}

    monkeypatch.setenv("EXTRA_HEADERS_JSON", "[]")
    with pytest.raises(ValueError):
        kb._extra_headers_for("https://example.com", None)


def test_resolve_model_config_chat_vision_fallback_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_NAME", "chat-model")
    assert kb.resolve_model_config() == ("openai", "chat-model", "chat")

    monkeypatch.delenv("VISION_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("VISION_MODEL_NAME", raising=False)
    assert kb.resolve_model_config("VISION_") == (
        "openai",
        "chat-model",
        "vision_fallback",
    )

    monkeypatch.setenv("VISION_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("VISION_MODEL_NAME", "vision-model")
    assert kb.resolve_model_config("VISION_") == (
        "openai",
        "vision-model",
        "vision",
    )

    monkeypatch.delenv("MODEL_PROVIDER")
    monkeypatch.delenv("MODEL_NAME")
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER"):
        kb.resolve_model_config()


def test_writable_probe(tmp_path: Path) -> None:
    assert kb._probe_writable(tmp_path) is None
    assert kb._is_writable_dir(tmp_path) is True

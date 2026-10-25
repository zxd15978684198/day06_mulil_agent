"""两个入口脚本的测试。"""

from __future__ import annotations

import runpy

from personal_assistant import build_index


def test_build_index_main_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(build_index, "ensure_writable_tempdir", lambda: None)
    monkeypatch.setattr(
        build_index,
        "build_vector_store",
        lambda: {
            "document_count": 1,
            "chunk_count": 2,
            "vector_store_path": "src/vector_store",
            "embedding_model": "test-model",
            "documents": [
                {
                    "document_id": "KB-PUB-001",
                    "parser_mode_actual": "text",
                    "chunk_count": 2,
                    "is_machine_extracted": False,
                    "provenance": {"model_name": "vision", "config_source": "vision"},
                }
            ],
            "failures": [
                {
                    "path": "bad.pdf",
                    "error_type": "ValueError",
                    "error_message": "empty",
                }
            ],
        },
    )

    build_index.main()

    output = capsys.readouterr().out
    assert "向量库构建完成" in output
    assert "KB-PUB-001" in output
    assert "解析失败：1 份" in output


def test_package_main_delegates_to_cli(monkeypatch) -> None:
    called: list[bool] = []
    import personal_assistant.main as cli

    monkeypatch.setattr(cli, "main", lambda: called.append(True))

    runpy.run_module("personal_assistant.__main__", run_name="__main__")

    assert called == [True]

"""路径解析测试：不依赖当前工作目录。"""

from __future__ import annotations

from pathlib import Path

import pytest

from personal_assistant import paths


def test_checkpoint_path_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "nested" / "checkpoints.sqlite3"
    monkeypatch.setenv("CHECKPOINT_DB", str(target))

    resolved = paths.checkpoint_path()

    assert resolved == target
    assert resolved.parent.is_dir()


def test_checkpoint_path_relative_to_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHECKPOINT_DB", "runtime/test-checkpoints.sqlite3")

    resolved = paths.checkpoint_path()

    assert resolved.is_absolute()
    assert resolved.parent == paths.PROJECT_ROOT / "runtime"

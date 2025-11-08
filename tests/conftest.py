from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUntypedFunctionDecorator=false

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest  # type: ignore[import-not-found]
from pytest import MonkeyPatch  # type: ignore[import-not-found]
from typing import Generator


@dataclass
class TestEnvironment:
    config: ModuleType
    save_root: Path
    backup_root: Path
    prefs_path: Path


_MODULES_TO_RESET = (
    "zomboid_saver.config",
    "zomboid_saver.cli",
    "zomboid_saver.backend",
    "zomboid_saver",
    "zomboid_saver_ui",
)


@pytest.fixture
def test_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> Generator[TestEnvironment, None, None]:
    base = tmp_path / "sandbox"
    save_root = base / "saves"
    backup_root = base / "backups"
    prefs_path = base / "prefs" / "preferences.json"

    monkeypatch.setenv("ZAS_GAME_SAVE_ROOT", str(save_root))
    monkeypatch.setenv("ZAS_BACKUP_SAVE_PATH", str(backup_root))
    monkeypatch.setenv("ZAS_PREFERENCES_PATH", str(prefs_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    for name in _MODULES_TO_RESET:
        sys.modules.pop(name, None)

    config = importlib.import_module("zomboid_saver.config")

    save_root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)

    yield TestEnvironment(
        config=config,
        save_root=save_root,
        backup_root=backup_root,
        prefs_path=prefs_path,
    )

    for name in _MODULES_TO_RESET:
        sys.modules.pop(name, None)

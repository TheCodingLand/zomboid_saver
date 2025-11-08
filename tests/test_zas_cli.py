from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false, reportUntypedFunctionDecorator=false

import importlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Tuple
from unittest import mock
from types import ModuleType

import pytest  # type: ignore[import-not-found]
from pytest import MonkeyPatch  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from .conftest import TestEnvironment
    from zomboid_saver.cli import ZAS


ModulePair = Tuple["ZAS", ModuleType]


def _create_zas() -> ModulePair:
    module = importlib.import_module("zomboid_saver.cli")
    return module.ZAS(), module


def _prepare_save(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "world.dat").write_bytes(b"data")


def test_archive_saves_creates_zip_when_compress_enabled(test_env: "TestEnvironment") -> None:
    config = test_env.config
    config.settings.compress_folders = True

    (save_root := config.settings.game_save_root).mkdir(parents=True, exist_ok=True)
    mode = config.settings.default_game_mode
    save_path = save_root / mode / "Alpha"
    _prepare_save(save_path)

    zas, _module = _create_zas()
    zas.game_mode = mode
    zas.save_to_backup = "Alpha"

    target_base = config.settings.backup_save_path / mode / "snapshot"
    zas.archive_saves(target_base, save_path)

    archive_path = Path(str(target_base) + ".zip")
    assert archive_path.exists()


def test_archive_saves_copies_directory_when_compression_disabled(
    test_env: "TestEnvironment",
) -> None:
    config = test_env.config
    config.settings.compress_folders = False

    mode = config.settings.default_game_mode
    save_path = config.settings.game_save_root / mode / "Alpha"
    _prepare_save(save_path)

    zas, _module = _create_zas()
    zas.game_mode = mode
    zas.save_to_backup = "Alpha"

    target_base = config.settings.backup_save_path / mode / "snapshot_copy"
    zas.archive_saves(target_base, save_path)

    assert target_base.exists()
    assert (target_base / "world.dat").exists()


def test_keep_last_n_saves_removes_oldest(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    backup_dir = config.settings.backup_save_path / mode
    backup_dir.mkdir(parents=True, exist_ok=True)

    zas, _module = _create_zas()
    zas.game_mode = mode
    zas.save_to_backup = "Alpha"

    for idx in range(3):
        entry = backup_dir / f"{idx}_Alpha"
        entry.mkdir()
        os.utime(entry, (idx + 1, idx + 1))

    zas.keep_last_n_saves(2)

    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert remaining == ["1_Alpha", "2_Alpha"]


def test_save_poller_handles_keyboard_interrupt(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    save_path = config.settings.game_save_root / mode / "Alpha"
    _prepare_save(save_path)

    zas, module = _create_zas()
    zas.game_mode = mode
    zas.save_to_backup = "Alpha"

    with mock.patch.object(zas, "back_up_saves") as mock_backup:
        with mock.patch.object(module.time, "sleep", side_effect=KeyboardInterrupt):
            with pytest.raises(SystemExit) as excinfo:
                zas.save_poller()

    mock_backup.assert_called_once()
    assert excinfo.value.code == 0


def test_back_up_saves_creates_archive(
    test_env: "TestEnvironment", monkeypatch: MonkeyPatch
) -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    save_path = config.settings.game_save_root / mode / "ArchiveMe"
    _prepare_save(save_path)

    monkeypatch.setattr(config.settings, "compress_folders", True)
    zas, _module = _create_zas()
    zas.game_mode = mode
    zas.save_to_backup = "ArchiveMe"

    zas.back_up_saves()

    backups = list((config.settings.backup_save_path / mode).glob("*_ArchiveMe.zip"))
    assert backups, "expected a zipped backup to be created"


def test_back_up_saves_raises_when_save_missing(test_env: "TestEnvironment") -> None:
    config = test_env.config
    zas, _module = _create_zas()
    zas.game_mode = config.settings.default_game_mode
    zas.save_to_backup = "Missing"

    with pytest.raises(FileNotFoundError):
        zas.back_up_saves()


def test_keep_last_n_saves_noop_when_retain_zero(test_env: "TestEnvironment") -> None:
    config = test_env.config
    backup_dir = config.settings.backup_save_path / config.settings.default_game_mode
    (backup_dir / "0_Alpha").mkdir(parents=True, exist_ok=True)

    zas, _module = _create_zas()
    zas.game_mode = config.settings.default_game_mode

    zas.keep_last_n_saves(0)

    assert (backup_dir / "0_Alpha").exists()


def test_keep_last_n_saves_missing_directory_is_noop(test_env: "TestEnvironment") -> None:
    config = test_env.config
    zas, _module = _create_zas()
    zas.game_mode = config.settings.default_game_mode

    missing_dir = config.settings.backup_save_path / zas.game_mode
    if missing_dir.exists():
        shutil.rmtree(missing_dir)

    zas.keep_last_n_saves(3)

    assert not missing_dir.exists()


def test_save_poller_exits_on_value_error(monkeypatch: MonkeyPatch) -> None:
    zas, _ = _create_zas()

    def boom() -> None:
        raise ValueError("bad state")

    monkeypatch.setattr(zas, "back_up_saves", boom)

    with pytest.raises(SystemExit) as excinfo:
        zas.save_poller()

    assert excinfo.value.code == 1

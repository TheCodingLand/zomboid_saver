from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false

import importlib
import os
import sqlite3
import time
from pathlib import Path

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .conftest import TestEnvironment

from pytest import MonkeyPatch  # type: ignore[import-not-found]


def _create_backend():
    module = importlib.import_module("zomboid_saver.backend")
    return module.ZomboidSaverBackend()


def _write_bytes(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_mkfolder_system_creates_backup_structure(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode_dir = test_env.save_root / config.settings.default_game_mode
    (mode_dir / "Alpha").mkdir(parents=True, exist_ok=True)

    _create_backend()

    backup_mode_dir = test_env.backup_root / config.settings.default_game_mode
    assert backup_mode_dir.exists()


def test_get_save_disk_usage_counts_save_and_backups(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    save_name = "Alpha"

    save_dir = test_env.save_root / mode / save_name
    save_dir.mkdir(parents=True, exist_ok=True)
    _write_bytes(save_dir / "save.dat", 128)
    _write_bytes(save_dir / "nested" / "asset.bin", 256)

    backup_dir = test_env.backup_root / mode
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_a = backup_dir / f"111_{save_name}"
    backup_b = backup_dir / f"222_{save_name}.zip"
    _write_bytes(backup_a / "data.bin", 512)
    _write_bytes(backup_b, 1024)

    backend = _create_backend()

    save_bytes, backup_bytes = backend.get_save_disk_usage(save_name)

    assert save_bytes == 384
    assert backup_bytes == 1536


def test_enforce_quota_removes_oldest(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    save_name = "Alpha"
    backup_dir = test_env.backup_root / mode
    backup_dir.mkdir(parents=True, exist_ok=True)

    backend = _create_backend()

    config.settings.save_quotas_mb[save_name] = 1  # 1 MB quota

    removed_expected: list[Path] = []
    for idx in range(3):
        path = backup_dir / f"{idx}_{save_name}"
        path.mkdir()
        _write_bytes(path / "payload.bin", 700_000)
        ts = time.time() - (10 - idx)
        os.utime(path, (ts, ts))
        if idx < 2:
            removed_expected.append(path)

    removed = backend.enforce_quota(save_name)

    assert set(Path(p) for p in removed) == set(removed_expected)
    for candidate in removed_expected:
        assert not candidate.exists()


def test_enforce_keep_last_trims_backups(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    save_name = "Alpha"
    backup_dir = test_env.backup_root / mode
    backup_dir.mkdir(parents=True, exist_ok=True)

    backend = _create_backend()
    config.settings.keep_last_n_saves = 2

    keepers: list[Path] = []
    for idx in range(3):
        path = backup_dir / f"{idx}_{save_name}"
        path.mkdir()
        _write_bytes(path / "payload.bin", 10)
        ts = time.time() + idx
        os.utime(path, (ts, ts))
        if idx >= 1:
            keepers.append(path)

    backend.enforce_keep_last(save_name)

    for path in keepers:
        assert path.exists()
    assert not (backup_dir / f"0_{save_name}").exists()


def test_get_backups_filters_by_save_name(test_env: "TestEnvironment") -> None:
    config = test_env.config
    mode = config.settings.default_game_mode
    backup_dir = test_env.backup_root / mode
    backup_dir.mkdir(parents=True, exist_ok=True)

    backend = _create_backend()

    target = backup_dir / "100_Alpha"
    other = backup_dir / "101_Beta"
    _write_bytes(target / "payload.bin", 10)
    _write_bytes(other / "payload.bin", 10)

    filtered = backend.get_backups(filter_save_name="Alpha")

    assert [item.name for item in filtered] == [target.name]


def test_get_save_stats_prefers_parser(
    test_env: "TestEnvironment", monkeypatch: MonkeyPatch
) -> None:
    backend_module = importlib.import_module("zomboid_saver.backend")

    def fake_parser(path: Path) -> dict[str, Any]:
        return {
            "character_name": "Alice",
            "hours_survived": 12,
            "zombies_killed": 34,
            "traits": ["Brave"],
        }

    monkeypatch.setattr(backend_module, "get_player_info", fake_parser)

    backend = backend_module.ZomboidSaverBackend()
    save_dir = test_env.save_root / backend.game_mode / "Alpha"
    save_dir.mkdir(parents=True, exist_ok=True)

    stats = backend.get_save_stats("Alpha")

    assert stats["character_name"] == "Alice"
    assert stats["hours"] == 12
    assert stats["zombies"] == 34
    assert stats["traits"] == ["Brave"]


def test_get_save_stats_falls_back_to_sqlite(
    test_env: "TestEnvironment", monkeypatch: MonkeyPatch
) -> None:
    backend_module = importlib.import_module("zomboid_saver.backend")

    def return_none(path: Path) -> None:
        return None

    monkeypatch.setattr(backend_module, "get_player_info", return_none)

    backend = backend_module.ZomboidSaverBackend()
    mode = backend.game_mode
    save_dir = test_env.save_root / mode / "Beta"
    save_dir.mkdir(parents=True, exist_ok=True)

    db_path = save_dir / "players.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE survivors (hours REAL, zombiekills INTEGER)")
    conn.execute("INSERT INTO survivors (hours, zombiekills) VALUES (?, ?)", (21.5, 99))
    conn.commit()
    conn.close()

    stats = backend.get_save_stats("Beta")

    assert stats["hours"] == 21.5
    assert stats["zombies"] == 99


def test_backup_and_restore_round_trip(
    test_env: "TestEnvironment", monkeypatch: MonkeyPatch
) -> None:
    backend_module = importlib.import_module("zomboid_saver.backend")
    backend = backend_module.ZomboidSaverBackend()
    mode = backend.game_mode
    save_name = "Gamma"
    save_dir = test_env.save_root / mode / save_name
    (save_dir / "nested").mkdir(parents=True, exist_ok=True)
    (save_dir / "nested" / "file.txt").write_text("payload", encoding="utf-8")

    monkeypatch.setattr(test_env.config.settings, "compress_folders", False)
    backup_path = Path(backend.backup_save(save_name))
    assert backup_path.exists() and backup_path.is_dir()

    target_name = "GammaRestored"
    restored_path = backend.restore_backup(str(backup_path), target_name)
    restored_file = Path(restored_path) / "nested" / "file.txt"
    assert restored_file.read_text(encoding="utf-8") == "payload"


def test_get_thumbnail_path_returns_string(test_env: "TestEnvironment") -> None:
    backend_module = importlib.import_module("zomboid_saver.backend")
    backend = backend_module.ZomboidSaverBackend()
    mode = backend.game_mode
    save_name = "Thumb"
    thumb_dir = test_env.save_root / mode / save_name
    thumb_dir.mkdir(parents=True, exist_ok=True)
    (thumb_dir / "thumb.png").write_bytes(b"image")

    thumbnail = backend.get_thumbnail_path(save_name)

    assert thumbnail is not None
    assert thumbnail.endswith("thumb.png")

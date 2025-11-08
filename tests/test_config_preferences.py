from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false

import json
from pathlib import Path
from typing import TYPE_CHECKING

from zomboid_saver.config import AppPreferences, load_preferences

if TYPE_CHECKING:
    from .conftest import TestEnvironment


def test_update_save_quota_persists(test_env: "TestEnvironment") -> None:
    config = test_env.config

    config.update_save_quota("Alpha", 123)

    assert config.settings.save_quotas_mb["Alpha"] == 123
    assert config.preferences.save_quotas_mb["Alpha"] == 123

    saved = json.loads(test_env.prefs_path.read_text(encoding="utf-8"))
    assert saved["save_quotas_mb"]["Alpha"] == 123


def test_update_settings_round_trip(test_env: "TestEnvironment") -> None:
    config = test_env.config

    config.update_save_interval(420)
    config.update_keep_last_n_saves(7)
    config.update_compress_folders(False)
    config.update_default_game_mode("Challenge")
    new_root = test_env.save_root / "alternate"
    config.update_game_save_root(new_root)

    saved = json.loads(test_env.prefs_path.read_text(encoding="utf-8"))

    assert config.settings.save_interval_sec == 420
    assert config.settings.keep_last_n_saves == 7
    assert config.settings.compress_folders is False
    assert config.settings.default_game_mode == "Challenge"
    assert config.settings.game_save_root == new_root

    assert saved["save_interval_sec"] == 420
    assert saved["keep_last_n_saves"] == 7
    assert saved["compress_folders"] is False
    assert saved["default_game_mode"] == "Challenge"
    assert Path(saved["game_save_root"]) == new_root


def test_load_preferences_recovers_from_corruption(tmp_path: Path) -> None:
    prefs = tmp_path / "prefs.json"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text("{not valid json", encoding="utf-8")

    recovered = load_preferences(prefs)
    backup = prefs.with_suffix(prefs.suffix + ".corrupt")

    assert isinstance(recovered, AppPreferences)
    assert recovered.save_quotas_mb == {}
    assert backup.exists()

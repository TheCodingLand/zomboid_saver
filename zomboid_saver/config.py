from __future__ import annotations

# pyright: reportCallIssue=false

import json
import os
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_backup_path() -> Path:
    return (Path.home() / "Zomboid" / "zas_backup_saves").expanduser()


def _default_game_save_root() -> Path:
    return (Path.home() / "Zomboid" / "Saves").expanduser()


def _default_preferences_path() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("APPDATA", Path.home()))
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "zomboid_saver" / "preferences.json"


class AppSettings(BaseSettings):
    """Runtime configuration loaded from environment variables or a .env file."""

    save_interval_sec: int = Field(300, ge=10, description="Seconds between automatic backups")
    backup_save_path: Path = Field(default_factory=_default_backup_path)
    compress_folders: bool = Field(True, description="Zip saves instead of copying directories")
    keep_last_n_saves: int = Field(10, ge=0)
    default_save_quota_mb: int = Field(2048, ge=0)
    save_quotas_mb: Dict[str, int] = Field(default_factory=dict)
    preferences_path: Path = Field(default_factory=_default_preferences_path)
    game_save_root: Path = Field(default_factory=_default_game_save_root)
    default_game_mode: str = Field("Sandbox", description="Default game mode to monitor")

    model_config = SettingsConfigDict(
        env_prefix="ZAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("backup_save_path", "preferences_path", "game_save_root", mode="before")
    @classmethod
    def _expand_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value.expanduser()
        return Path(str(value)).expanduser()


class AppPreferences(BaseModel):
    """Persisted user preferences that can change at runtime."""

    save_quotas_mb: Dict[str, int] = Field(default_factory=dict)
    save_interval_sec: Optional[int] = None
    keep_last_n_saves: Optional[int] = None
    compress_folders: Optional[bool] = None
    default_game_mode: Optional[str] = None
    game_save_root: Optional[str] = None

    def resolve_quota(self, save_name: str, fallback: int) -> int:
        return self.save_quotas_mb.get(save_name, fallback)


def load_preferences(path: Path) -> AppPreferences:
    if path.exists():
        try:
            return AppPreferences.model_validate_json(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            backup = path.with_suffix(path.suffix + ".corrupt")
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(path.read_text(encoding="utf-8", errors="ignore"))
    return AppPreferences()


def save_preferences(preferences: AppPreferences, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(preferences.model_dump_json(indent=2), encoding="utf-8")


settings = AppSettings()  # type: ignore[call-arg]
preferences = load_preferences(settings.preferences_path)

if preferences.save_quotas_mb:
    merged = {**preferences.save_quotas_mb, **settings.save_quotas_mb}
    settings.save_quotas_mb = merged
elif settings.save_quotas_mb:
    preferences.save_quotas_mb.update(settings.save_quotas_mb)

if preferences.save_interval_sec is not None:
    settings.save_interval_sec = preferences.save_interval_sec

if preferences.keep_last_n_saves is not None:
    settings.keep_last_n_saves = preferences.keep_last_n_saves

if preferences.compress_folders is not None:
    settings.compress_folders = preferences.compress_folders

if preferences.default_game_mode:
    settings.default_game_mode = preferences.default_game_mode

if preferences.game_save_root:
    settings.game_save_root = Path(preferences.game_save_root).expanduser()


def persist_preferences() -> None:
    save_preferences(preferences, settings.preferences_path)


def update_save_quota(save_name: str, quota_mb: int) -> None:
    preferences.save_quotas_mb[save_name] = quota_mb
    settings.save_quotas_mb[save_name] = quota_mb
    persist_preferences()


def resolve_save_quota(save_name: str) -> int:
    return settings.save_quotas_mb.get(save_name, settings.default_save_quota_mb)


def update_save_interval(seconds: int) -> None:
    settings.save_interval_sec = seconds
    preferences.save_interval_sec = seconds
    persist_preferences()


def update_keep_last_n_saves(count: int) -> None:
    settings.keep_last_n_saves = count
    preferences.keep_last_n_saves = count
    persist_preferences()


def update_compress_folders(enabled: bool) -> None:
    settings.compress_folders = enabled
    preferences.compress_folders = enabled
    persist_preferences()


def update_default_game_mode(mode: str) -> None:
    settings.default_game_mode = mode
    preferences.default_game_mode = mode
    persist_preferences()


def update_game_save_root(path: str | Path) -> None:
    resolved = Path(path).expanduser()
    settings.game_save_root = resolved
    preferences.game_save_root = str(resolved)
    persist_preferences()

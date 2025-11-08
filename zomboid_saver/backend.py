from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, List, Optional

from .config import resolve_save_quota, settings
from zomboid_parser import get_player_info


class ZomboidSaverBackend:
    """Core filesystem operations for Zomboid save management."""

    def __init__(self) -> None:
        self.save_root: Path = settings.game_save_root
        self.game_mode: str = settings.default_game_mode
        self.save_to_backup: Optional[str] = None
        self.backup_root: Path = settings.backup_save_path
        self.mkfolder_system()

    def mkfolder_system(self) -> None:
        """Ensure backup folders exist to mirror the save structure."""
        self.backup_root.mkdir(parents=True, exist_ok=True)
        if not self.save_root.exists():
            return

        for folder in self.save_root.iterdir():
            if not folder.is_dir():
                continue
            mode_path = self.backup_root / folder.name
            mode_path.mkdir(parents=True, exist_ok=True)

    def get_available_saves(self) -> List[str]:
        """Return available save folders sorted by modification time."""
        save_path = self.save_root / self.game_mode
        if not save_path.exists():
            return []

        saves = [(f.name, f.stat().st_mtime) for f in save_path.iterdir() if f.is_dir()]
        saves.sort(key=lambda item: item[1], reverse=True)
        return [save_name for save_name, _ in saves]

    def get_save_stats(self, save_name: str) -> dict[str, Any]:
        """Pull metadata from Project Zomboid save databases when available."""
        save_path = self.save_root / self.game_mode / save_name

        player_info = get_player_info(save_path)
        if player_info:
            return {
                "character_name": player_info.get("character_name", "Unknown"),
                "hours": player_info.get("hours_survived", 0),
                "zombies": player_info.get("zombies_killed", 0),
                "traits": player_info.get("traits", []),
            }

        db_path = save_path / "players.db"
        if not db_path.exists():
            return {"character_name": "Unknown", "hours": 0, "zombies": 0, "traits": []}

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT hours, zombiekills FROM survivors LIMIT 1")
            result = cursor.fetchone()
            conn.close()
        except Exception as exc:  # pragma: no cover - defensive branch
            return {
                "character_name": "Unknown",
                "hours": 0,
                "zombies": 0,
                "traits": [],
                "error": str(exc),
            }

        if result:
            return {
                "character_name": "Unknown",
                "hours": result[0] or 0,
                "zombies": result[1] or 0,
                "traits": [],
            }
        return {"character_name": "Unknown", "hours": 0, "zombies": 0, "traits": []}

    def get_thumbnail_path(self, save_name: str) -> Optional[str]:
        thumb_path = self.save_root / self.game_mode / save_name / "thumb.png"
        return str(thumb_path) if thumb_path.exists() else None

    def backup_save(self, save_name: str) -> str:
        base_save_path = self.save_root / self.game_mode / save_name
        if not base_save_path.exists():
            raise FileNotFoundError(f"Save '{save_name}' not found")
        if not (self.backup_root / self.game_mode).exists():
            (self.backup_root / self.game_mode).mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        zip_name = f"{timestamp}_{save_name}"
        full_backup_path = self.backup_root / self.game_mode / zip_name

        if settings.compress_folders:
            shutil.make_archive(str(full_backup_path), "zip", str(base_save_path))
            return f"{full_backup_path}.zip"

        shutil.copytree(str(base_save_path), str(full_backup_path))
        return str(full_backup_path)

    def get_backups(
        self,
        filter_save_name: Optional[str] = None,
        game_mode: Optional[str] = None,
    ) -> List[Path]:
        mode = game_mode or self.game_mode
        backup_path = self.backup_root / mode
        backups: List[Path] = []
        if not backup_path.exists():
            return backups

        for item in backup_path.iterdir():
            if filter_save_name:
                item_name = item.stem if item.suffix == ".zip" else item.name
                if "_" in item_name:
                    backup_save_name = "_".join(item_name.split("_")[1:])
                    if backup_save_name != filter_save_name:
                        continue

            if item.is_file() and item.suffix == ".zip":
                backups.append(item)
            elif item.is_dir():
                backups.append(item)

        backups.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        return backups

    def get_save_disk_usage(
        self, save_name: str, game_mode: Optional[str] = None
    ) -> tuple[int, int]:
        mode = game_mode or self.game_mode
        save_path = self.save_root / mode / save_name

        save_bytes = 0
        if save_path.exists():
            for item in save_path.rglob("*"):
                if item.is_file():
                    save_bytes += item.stat().st_size

        backup_bytes = 0
        for backup in self.get_backups(filter_save_name=save_name, game_mode=mode):
            backup_bytes += self._get_backup_size(backup)

        return save_bytes, backup_bytes

    def restore_backup(self, backup_path: str, target_save_name: str) -> str:
        target_path = self.save_root / self.game_mode / target_save_name
        backup_p = Path(backup_path)

        if target_path.exists():
            shutil.rmtree(target_path)

        if backup_p.suffix == ".zip":
            shutil.unpack_archive(str(backup_p), str(target_path))
        else:
            shutil.copytree(str(backup_p), str(target_path))

        return str(target_path)

    def enforce_quota(self, save_name: str) -> List[str]:
        quota_mb = self._resolve_quota_mb(save_name)
        if quota_mb <= 0:
            return []

        backups = self.get_backups(filter_save_name=save_name)
        if not backups:
            return []

        total_bytes = sum(self._get_backup_size(item) for item in backups)
        quota_bytes = quota_mb * 1024 * 1024

        if total_bytes <= quota_bytes:
            return []

        removed: List[str] = []
        for backup in sorted(backups, key=lambda path: path.stat().st_mtime):
            backup_size = self._get_backup_size(backup)
            self._remove_backup(backup)
            removed.append(str(backup))
            total_bytes -= backup_size
            if total_bytes <= quota_bytes:
                break

        return removed

    def enforce_keep_last(self, save_name: str) -> List[str]:
        retain = settings.keep_last_n_saves
        if retain <= 0:
            return []

        backups = self.get_backups(filter_save_name=save_name)
        if len(backups) <= retain:
            return []

        ordered = sorted(backups, key=lambda path: path.stat().st_mtime)
        to_remove = ordered[:-retain]

        removed: List[str] = []
        for backup in to_remove:
            self._remove_backup(backup)
            removed.append(str(backup))

        return removed

    def _resolve_quota_mb(self, save_name: str) -> int:
        return resolve_save_quota(save_name)

    def _get_backup_size(self, backup: Path) -> int:
        if backup.is_file():
            return backup.stat().st_size

        size = 0
        for item in backup.rglob("*"):
            if item.is_file():
                size += item.stat().st_size
        return size

    def _remove_backup(self, backup: Path) -> None:
        if backup.is_dir():
            shutil.rmtree(backup, ignore_errors=True)
        else:
            backup.unlink(missing_ok=True)

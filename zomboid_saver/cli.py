from __future__ import annotations

import datetime
import shutil
import sys
import time
from pathlib import Path

from .config import settings


class ZAS:
    """Legacy CLI automation for scheduled Project Zomboid backups."""

    def __init__(self) -> None:
        self.save_root: Path = settings.game_save_root
        self.game_mode: str = settings.default_game_mode
        self.save_to_backup: str = "2025-01-01_00-05-54"
        self.next_save_time: float = time.time() + settings.save_interval_sec
        self.has_just_started: bool = True
        self.mkfolder_system()

    def mkfolder_system(self) -> None:
        backup_root = settings.backup_save_path
        backup_root.mkdir(parents=True, exist_ok=True)
        if not self.save_root.exists():
            return

        for folder in self.save_root.iterdir():
            if folder.is_dir():
                (backup_root / folder.name).mkdir(parents=True, exist_ok=True)

    def back_up_saves(self) -> None:
        base_save_path = self.save_root / self.game_mode / self.save_to_backup
        if not base_save_path.exists():
            raise FileNotFoundError(f"Save '{base_save_path.name}' not found")

        zip_name = f"{int(time.time())}_{base_save_path.name}"
        full_backup_path = settings.backup_save_path / self.game_mode / zip_name
        now = datetime.datetime.now().strftime("%m/%d/%y %I:%M:%S")
        print(f"{now} -- Archiving '{base_save_path.name}', into: '{full_backup_path}.zip'")
        self.archive_saves(full_backup_path, base_save_path)
        print("Done!")
        self.keep_last_n_saves(settings.keep_last_n_saves)

    def archive_saves(self, path_to_backup: Path, target_save_path: Path) -> None:
        if settings.compress_folders:
            shutil.make_archive(str(path_to_backup), "zip", str(target_save_path))
        else:
            shutil.copytree(str(target_save_path), str(path_to_backup))

    def save_poller(self) -> None:
        try:
            while True:
                if time.time() >= self.next_save_time or self.has_just_started:
                    self.has_just_started = False
                    self.back_up_saves()
                    self.next_save_time = time.time() + settings.save_interval_sec
                time.sleep(10)
        except KeyboardInterrupt:
            print("Hope you killed some Zeds my friend!")
            sys.exit(0)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)

    def keep_last_n_saves(self, retain: int) -> None:
        if retain <= 0:
            return
        save_path = settings.backup_save_path / self.game_mode
        if not save_path.exists():
            return
        files = sorted(save_path.iterdir(), key=lambda path: path.stat().st_mtime)
        for file_path in files[:-retain]:
            if file_path.is_dir():
                shutil.rmtree(file_path, ignore_errors=True)
            else:
                file_path.unlink(missing_ok=True)


def main() -> None:
    zas = ZAS()
    zas.save_poller()


if __name__ == "__main__":
    main()

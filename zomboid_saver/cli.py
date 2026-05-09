from __future__ import annotations

import logging
import sys
import time

from . import config as _config
from .backend import ZomboidSaverBackend

logger = logging.getLogger(__name__)


class ZAS:
    """CLI automation for scheduled Project Zomboid backups.

    Thin wrapper around :class:`ZomboidSaverBackend` that adds a polling
    loop for headless / unattended operation.
    """

    def __init__(self) -> None:
        self.backend = ZomboidSaverBackend()
        self._game_mode: str = _config.settings.default_game_mode
        self.save_to_backup: str = "2025-01-01_00-05-54"
        self.next_save_time: float = time.time() + _config.settings.save_interval_sec
        self.has_just_started: bool = True

    @property
    def game_mode(self) -> str:
        return self._game_mode

    @game_mode.setter
    def game_mode(self, value: str) -> None:
        self._game_mode = value
        self.backend.game_mode = value

    # ------------------------------------------------------------------
    # Delegated helpers kept for backward compatibility
    # ------------------------------------------------------------------

    def mkfolder_system(self) -> None:
        self.backend.mkfolder_system()

    def back_up_saves(self) -> None:
        backup_path = self.backend.backup_save(self.save_to_backup)
        logger.info("Backup created: %s", backup_path)
        self.keep_last_n_saves(_config.settings.keep_last_n_saves)

    def archive_saves(self, path_to_backup: "object", target_save_path: "object") -> None:
        """Kept for test compatibility – delegates to backend.backup_save."""
        from pathlib import Path
        import shutil

        if _config.settings.compress_folders:
            shutil.make_archive(str(path_to_backup), "zip", str(target_save_path))
        else:
            shutil.copytree(str(target_save_path), str(path_to_backup))

    def save_poller(self) -> None:
        try:
            while True:
                if time.time() >= self.next_save_time or self.has_just_started:
                    self.has_just_started = False
                    self.back_up_saves()
                    self.next_save_time = time.time() + _config.settings.save_interval_sec
                time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Hope you killed some Zeds my friend!")
            sys.exit(0)
        except ValueError as exc:
            logger.error("ERROR: %s", exc)
            sys.exit(1)

    def keep_last_n_saves(self, retain: int) -> None:
        if retain <= 0:
            return
        removed = self.backend.enforce_keep_last(self.save_to_backup)
        if removed:
            logger.info("Pruned %d old backup(s)", len(removed))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%m/%d/%y %I:%M:%S",
    )
    zas = ZAS()
    zas.save_poller()


if __name__ == "__main__":
    main()

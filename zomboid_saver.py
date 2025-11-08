"""
This is a project zomboid script that will auto save your game every interval
NOTE: This is the CLI version. For the GUI version, use zomboid_saver_ui.py
"""

import datetime
import shutil
import sys
import time
from pathlib import Path

from config import settings


class ZAS:
    "This is a class that runs the Zomboid Auto Save system"

    def __init__(self):
        self.save_root: Path = settings.game_save_root
        self.game_mode = settings.default_game_mode
        self.save_to_backup = "2025-01-01_00-05-54"
        self.next_save_time = time.time() + settings.save_interval_sec
        self.has_just_started = True
        self.mkfolder_system()

    def mkfolder_system(self):
        """Checks to see if we need to make the folders where we put the backup Zips"""
        backup_root = settings.backup_save_path
        backup_root.mkdir(parents=True, exist_ok=True)
        if not self.save_root.exists():
            return

        for folder in self.save_root.iterdir():
            if folder.is_dir():
                (backup_root / folder.name).mkdir(parents=True, exist_ok=True)

        print(f"All saves are in: '{backup_root}'")

    def back_up_saves(self):
        """Step the save folders and backups all saves"""

        base_save_path = self.save_root / self.game_mode / self.save_to_backup

        zip_name = f"{int(time.time())}_{base_save_path.name}"
        full_backup_path = settings.backup_save_path / self.game_mode / zip_name
        now = datetime.datetime.now()
        current_time = now.strftime("%m/%d/%y %I:%M:%S")
        print(
            f"{current_time} -- Archiving '{base_save_path.name}', into: '{full_backup_path}.zip'"
        )
        self.archive_saves(full_backup_path, base_save_path)
        print("Done!")
        self.keep_last_n_saves(settings.keep_last_n_saves)

    def archive_saves(self, path_to_backup: Path, target_save_path: Path):
        """depending on the settings it will archive the saves as a .ZIP of the targeted folder or just copy the folders"""
        if settings.compress_folders:
            shutil.make_archive(str(path_to_backup), "zip", str(target_save_path))
        else:
            shutil.copytree(str(target_save_path), str(path_to_backup))

    def save_poller(self):
        """Every SAVE_INTERVAL_SEC it will review the folders created and backup your save files"""
        try:
            while True:
                if time.time() >= self.next_save_time or self.has_just_started:
                    self.has_just_started = False
                    self.back_up_saves()
                    self.current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    self.next_save_time = (
                        time.time() + settings.save_interval_sec
                    )  # Reset the next save time
                time.sleep(10)
        except KeyboardInterrupt:
            print("Hope you killed some Zeds my friend!")
            sys.exit(0)
        except ValueError as e:
            print("ERROR: %s" % e)
            sys.exit(1)

    def keep_last_n_saves(self, n: int):
        """This will keep the last N saves and delete the rest, based on time created"""
        if n <= 0:
            return
        save_path = settings.backup_save_path / self.game_mode
        if not save_path.exists():
            return
        # sort by time created
        files = sorted(save_path.iterdir(), key=lambda p: p.stat().st_mtime)
        # keep the last N files
        for file in files[:-n]:
            if file.is_dir():
                shutil.rmtree(file, ignore_errors=True)
            else:
                file.unlink(missing_ok=True)


def main() -> None:
    zas = ZAS()
    zas.save_poller()


if __name__ == "__main__":
    main()

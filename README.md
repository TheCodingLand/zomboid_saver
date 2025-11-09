# Zomboid Auto-Saver

Automated backup companion for Project Zomboid. The desktop app watches your saves, takes care of scheduled snapshots, and lets you restore a previous run in a couple of clicks—no file wrangling required.

![Coverage](https://thecodingland.github.io/zomboid_saver/coverage.svg)

## What It Does
- Keeps an eye on the active save slot and creates rolling backups while you play.
- Lets you trigger a manual backup before risky in-game moments.
- Restores any recorded backup and re-opens the game folder for you.
- Applies per-save storage limits so old snapshots are pruned automatically.
- Runs quietly in the system tray once configured.

## Quick Start (Prebuilt Downloads)
- **Windows:** Download `zomboid_saver-windows.exe` from the latest GitHub Release, move it to a permanent folder, and double-click to launch. Windows SmartScreen may warn about an unknown publisher—choose *More info → Run anyway* to continue. The app minimizes to the tray once the first backup cycle starts.
- **Linux:** Download `zomboid_saver-linux`, make it executable (`chmod +x zomboid_saver-linux`), then run `./zomboid_saver-linux`. Nuitka unpacks the app to a temporary directory at runtime and cleans it up automatically when you quit.

## Quick Start (Run From Source)
1. Install Python 3.13+ and the `uv` package manager.
2. Clone the repository and open a terminal in the project folder.
3. Install dependencies: `uv sync`
4. Start the app: `uv run python zomboid_saver_ui.py`

On first launch the app creates a preferences file at `%APPDATA%\zomboid_saver\preferences.json` (Windows) or `$XDG_CONFIG_HOME/zomboid_saver/preferences.json` (Linux/macOS).

## Using the App
- **Dashboard:** Shows your detected Project Zomboid saves and the time of the next automatic backup. Click a save to see available snapshots.
- **Manual backup:** Press *Backup Now* to create an immediate snapshot of the selected save.
- **Restore:** Choose a snapshot and hit *Restore*. The app copies the archived files back into Project Zomboid’s save directory and opens the destination folder so you can confirm the result.
- **System tray:** Close the window to send the app to the tray. Right-click the tray icon for quick access to *Backup Now*, *Pause Auto-Backups*, and *Quit* options.

## Tuning Preferences
- Open *Preferences* from the top-left setting menu.
- **Save interval:** Choose how frequently automatic backups run (default: every 10 minutes).
- **Backup location:** Set the folder where archives are stored. Keep it on a drive with enough free space.
- **Compression:** Toggle zip compression if you want smaller archives in exchange for slightly longer backup times.
- **Keep last N backups:** Define how many snapshots per save should be retained. Older ones are deleted automatically once the limit is reached.
- **Notifications:** Enable toast pop-ups when backups complete or fail.

All preference changes are saved instantly. You can also place overrides in a `.env` file using keys such as `ZAS_SAVE_INTERVAL_SEC`, `ZAS_BACKUP_SAVE_PATH`, or `ZAS_KEEP_LAST_N_SAVES` if you prefer environment-based control.

## Tips & Troubleshooting
- **No saves listed?** Point the *Save Root* preference to your Project Zomboid `Saves` directory (e.g. `%USERPROFILE%\Zomboid\Saves`).
- **Backups seem slow?** Try disabling compression or reducing the keep-last count.
- **Need a fresh start?** Delete the preferences file and relaunch to revert to defaults.
- **Want headless operation?** Run `uv run python -m zomboid_saver.cli` to invoke the batch-friendly CLI that performs the same backup cycle.

## For Power Users
- Run `uv run pytest` if you want to execute the test suite or inspect coverage locally.
- GitHub Actions builds standalone Windows and Linux artifacts with Nuitka whenever a tag matching `v*` is pushed and attaches them to the release automatically.

Enjoy safer survivor stories!

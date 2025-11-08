# Zomboid Auto-Saver

Automated backup utility for Project Zomboid saves. A PyQt6 desktop app keeps watch over your game folders, performs interval backups, and lets you restore prior runs without digging through directories.

> `![Coverage](https://thecodingland.github.io/zomboid_saver/coverage.svg)`

## Features
- Auto-backup the active save at a configurable interval
- Per-save disk quota and keep-last pruning to control storage
- Manual backup and restore workflow with confirmation prompts
- Preferences dialog that syncs with a persisted settings file
- Legacy CLI entry point for headless or scripted usage

## Requirements
- Python 3.13 or newer
- `uv` for dependency management (https://github.com/astral-sh/uv)
- Project Zomboid installed locally with saves in the default location, or a custom path configured via the app

## Getting Started
1. Clone the repository and switch to the project directory.
2. Sync dependencies (including build extras if you plan to run PyOxidizer):
	 - GUI and tests only: `uv sync`
	 - Include build tooling: `uv sync --extra build`
3. Launch the GUI: `uv run python zomboid_saver_ui.py`
4. First run initializes the preferences file at `%APPDATA%\zomboid_saver\preferences.json` (Windows) or `$XDG_CONFIG_HOME/zomboid_saver/preferences.json`.

## Configuration
- Environment variables (prefixed with `ZAS_`) override defaults at startup. Place them in a `.env` file or export in your shell. Common settings:
	- `ZAS_SAVE_INTERVAL_SEC`
	- `ZAS_BACKUP_SAVE_PATH`
	- `ZAS_COMPRESS_FOLDERS`
	- `ZAS_KEEP_LAST_N_SAVES`
	- `ZAS_DEFAULT_GAME_MODE`
- Runtime changes made through the Preferences dialog are persisted to the preferences file.
- Per-save quota adjustments use `update_save_quota` and are persisted alongside other preferences.

## CLI Usage
The legacy CLI runner remains available for scripted environments:

```
uv run python -m zomboid_saver.cli
```

It respects the same configuration sources as the GUI and prints backup progress to stdout.

## Testing and Coverage
- Run tests locally with `uv run pytest`.
- Coverage thresholds are enforced at 80%, with results written to `coverage.xml` for CI badge generation.
- CI (GitHub Actions) executes the test suite on Windows, uploads coverage artifacts, and publishes the badge to `gh-pages` on every push.

## Building the Windows Executable
PyOxidizer packages the GUI into a standalone executable:
1. Install build dependencies: `uv sync --extra build`
2. Build locally: `uv run pyoxidizer build --release`
3. The executable and supporting files are emitted under `build/`.

The `Build and Release` workflow mirrors these steps and attaches a zipped build to GitHub releases whenever a tag matching `v*` is pushed.

## Release Workflow
- Create a tag (`git tag v0.2.0 && git push origin v0.2.0`) to trigger the release pipeline.
- The workflow runs PyOxidizer, zips the output, uploads the artifact, and publishes a GitHub Release with the packaged build.
- Use `gh release create` if you prefer to author notes manually; the action only needs the tag to exist.

## Troubleshooting
- **GUI does not show saves:** confirm the game save root path in Preferences points to your Project Zomboid `Saves/` directory.
- **Backups are missing thumbnails:** the backend copies `map_screenshot.png` when available; older saves without screenshots will display placeholder text.
- **Coverage badge missing:** ensure GitHub Pages is configured to serve the `gh-pages` branch and allow the CI job to complete after a push.

# TODO

- [x] Support minimizing the GUI to the system tray while keeping auto-save active.
- [x] Replace remaining hard-coded configuration in `zomboid_saver_ui.py` with values from `config.settings` / `preferences` where functionality is still pending (e.g., quota editing, compression toggle, save interval).
- [x] Remove UI components that dont work (zombie kill count, hours survived)
- [x] Add UI controls to adjust per-save quota values and persist them via `update_save_quota`.

- [x] Expose runtime settings (save interval, compression, keep-last count) in the UI and sync changes back to the settings/preferences store.
- [x] Ensure disk-usage calculations run asynchronously and update the UI reliably.
- [x] Add unit tests, ensure 80% coverage
- [x] Cleanup the code, remove the scripts other than the gui script, and refactor what makes sense into sub modules.
- [ ] Add github actions for tests, the test coverage badge, executable build and releases.
- [ ] Document the program, the configuration flow and PyOxidizer build process in `README.md` (include dependency install steps).


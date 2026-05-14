from __future__ import annotations

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false, reportUntypedFunctionDecorator=false

import importlib
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Generator
from unittest import mock

import pytest  # type: ignore[import-not-found]
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QListWidgetItem, QMessageBox
from pytest import MonkeyPatch  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from .conftest import TestEnvironment


@pytest.fixture
def qapp() -> Generator[QApplication, None, None]:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _import_ui_module() -> ModuleType:
    return importlib.import_module("zomboid_saver.ui")


def _create_window(
    qapp: QApplication,
    monkeypatch: MonkeyPatch,
    *,
    patch_disk_usage: bool = True,
) -> tuple[object, ModuleType]:
    ui_module = _import_ui_module()
    if patch_disk_usage:
        monkeypatch.setattr(
            ui_module.ZomboidSaverUI,
            "_start_disk_usage_task",
            lambda self, save_name, game_mode: None,
        )

    window = ui_module.ZomboidSaverUI()
    window.timer.stop()
    qapp.processEvents()
    return window, ui_module


def _prepare_save(path: Path, qapp: QApplication, *, with_thumbnail: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "world.dat").write_bytes(b"data")
    if with_thumbnail:
        pixmap = QPixmap(1, 1)
        pixmap.fill()
        assert pixmap.save(str(path / "thumb.png"))


def _make_selected_backup_item(path: Path) -> QListWidgetItem:
    item = QListWidgetItem(path.name)
    item.setData(Qt.ItemDataRole.UserRole, str(path))
    return item


def test_preferences_dialog_collects_values_and_game_modes(
    test_env: "TestEnvironment", qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    ui_module = _import_ui_module()
    current_root = test_env.config.settings.game_save_root
    (current_root / "Apocalypse").mkdir(parents=True, exist_ok=True)
    (current_root / "Builder").mkdir(parents=True, exist_ok=True)

    dialog = ui_module.PreferencesDialog(None)
    dialog.save_root_edit.setText(str(current_root))
    dialog._save_root_edited()

    assert dialog.game_mode_combo.count() == 2

    alternate_root = test_env.save_root / "custom"
    (alternate_root / "Survivor").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        ui_module.QFileDialog,
        "getExistingDirectory",
        lambda *args: str(alternate_root),
    )
    dialog._browse_save_root()

    dialog.interval_spin.setValue(123)
    dialog.keep_last_spin.setValue(7)
    dialog.compress_checkbox.setChecked(False)
    dialog.game_mode_combo.setEditText("Survivor")
    dialog.accept()

    assert dialog.save_root_edit.text() == str(alternate_root)
    assert dialog.values() == {
        "save_interval_sec": 123,
        "keep_last_n_saves": 7,
        "compress_folders": False,
        "default_game_mode": "Survivor",
        "game_save_root": str(alternate_root),
    }

    dialog.close()
    qapp.processEvents()


def test_ui_initialization_loads_save_and_disk_usage_paths(
    test_env: "TestEnvironment", qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    mode = test_env.config.settings.default_game_mode
    save_path = test_env.save_root / mode / "Alpha"
    backup_path = test_env.backup_root / mode / "100_Alpha"

    _prepare_save(save_path, qapp, with_thumbnail=True)
    backup_path.mkdir(parents=True, exist_ok=True)
    (backup_path / "snapshot.bin").write_bytes(b"backup")

    window, _ui_module = _create_window(qapp, monkeypatch)

    assert window.save_combo.count() == 1
    assert window.save_combo.currentText() == "Alpha"
    assert window.backup_list.count() == 1
    assert window.char_value.text() == "Unknown"
    assert window.thumbnail_label.pixmap() is not None

    key = window._make_cache_key(mode, "Alpha")
    window._handle_disk_usage_result(mode, "Alpha", 12, 34, 1, key, None)
    assert window.save_usage_label.text() == "Save Size: 12 B"
    assert window.backup_usage_label.text() == "Backups Size: 34 B"

    window._trigger_disk_usage_update(None)
    assert window.save_usage_label.text() == "Save Size: --"
    assert window.backup_usage_label.text() == "Backups Size: --"

    window._disk_usage_cache[key] = (56, 78)
    window._trigger_disk_usage_update("Alpha")
    assert window.save_usage_label.text() == "Save Size: 56 B"
    assert window.backup_usage_label.text() == "Backups Size: 78 B"

    window.on_save_selected("")
    assert not window.quota_spin.isEnabled()
    assert not window.quota_apply_btn.isEnabled()

    window.close()
    qapp.processEvents()


def test_ui_preferences_timer_backup_and_tray_flows(
    test_env: "TestEnvironment", qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    mode = test_env.config.settings.default_game_mode
    _prepare_save(test_env.save_root / mode / "Alpha", qapp)

    window, ui_module = _create_window(qapp, monkeypatch)

    class CancelDialog:
        def __init__(self, parent: object) -> None:
            self.parent = parent

        def exec(self) -> int:
            return int(QDialog.DialogCode.Rejected)

    class RefreshDialog:
        def __init__(self, parent: object) -> None:
            self.parent = parent

        def exec(self) -> int:
            return int(QDialog.DialogCode.Accepted)

        def values(self) -> dict[str, object]:
            return {
                "save_interval_sec": test_env.config.settings.save_interval_sec + 30,
                "keep_last_n_saves": test_env.config.settings.keep_last_n_saves + 1,
                "compress_folders": (not test_env.config.settings.compress_folders),
                "default_game_mode": test_env.config.settings.default_game_mode,
                "game_save_root": str(test_env.config.settings.game_save_root),
            }

    class ReloadDialog:
        def __init__(self, parent: object) -> None:
            self.parent = parent

        def exec(self) -> int:
            return int(QDialog.DialogCode.Accepted)

        def values(self) -> dict[str, object]:
            new_root = test_env.save_root / "alt-root"
            (new_root / "Builder").mkdir(parents=True, exist_ok=True)
            return {
                "save_interval_sec": test_env.config.settings.save_interval_sec,
                "keep_last_n_saves": test_env.config.settings.keep_last_n_saves,
                "compress_folders": test_env.config.settings.compress_folders,
                "default_game_mode": "Builder",
                "game_save_root": str(new_root),
            }

    monkeypatch.setattr(ui_module, "PreferencesDialog", CancelDialog)
    window.open_preferences_dialog()

    monkeypatch.setattr(ui_module, "PreferencesDialog", RefreshDialog)
    load_backups = mock.Mock()
    load_saves = mock.Mock()
    trigger_usage = mock.Mock()
    enforce_keep_last = mock.Mock(return_value=[str(test_env.backup_root / mode / "old_Alpha")])
    monkeypatch.setattr(window, "load_backups", load_backups)
    monkeypatch.setattr(window, "load_saves", load_saves)
    monkeypatch.setattr(window, "_trigger_disk_usage_update", trigger_usage)
    monkeypatch.setattr(window.backend, "enforce_keep_last", enforce_keep_last)
    window.save_combo.clear()
    window.save_combo.addItem("Alpha")
    window.save_combo.setCurrentText("Alpha")
    load_backups.reset_mock()
    load_saves.reset_mock()
    trigger_usage.reset_mock()
    enforce_keep_last.reset_mock()
    window.open_preferences_dialog()

    load_backups.assert_called_once_with(invalidate_usage=True)
    enforce_keep_last.assert_called_once_with("Alpha")

    monkeypatch.setattr(ui_module, "PreferencesDialog", ReloadDialog)
    window.open_preferences_dialog()

    load_saves.assert_called_once_with()
    trigger_usage.assert_called_with(None)

    perform_backup = mock.Mock()
    monkeypatch.setattr(window, "perform_backup", perform_backup)
    window.manual_backup()
    perform_backup.assert_called_once_with()

    window.toggle_auto_save()
    assert window.timer_label.text() == "PAUSED"
    window.toggle_auto_save()
    assert window.auto_save_enabled is True

    monkeypatch.setattr(window, "perform_backup", perform_backup)
    perform_backup.reset_mock()
    window.next_save_time = time.time() - 1
    window.save_combo.setCurrentText("Alpha")
    window.update_timer()
    perform_backup.assert_called_once_with()

    window.next_save_time = time.time() + 20
    window.update_timer()
    assert "#ff0000" in window.timer_label.styleSheet()

    window.next_save_time = time.time() + 45
    window.update_timer()
    assert "#ffa500" in window.timer_label.styleSheet()

    window.next_save_time = time.time() + 120
    window.update_timer()
    assert "#0f0" in window.timer_label.styleSheet()

    warning = mock.Mock()
    critical = mock.Mock()
    monkeypatch.setattr(ui_module.QMessageBox, "warning", warning)
    monkeypatch.setattr(ui_module.QMessageBox, "critical", critical)

    window.save_combo.clear()
    ui_module.ZomboidSaverUI.perform_backup(window)
    warning.assert_called_once()

    warning.reset_mock()
    window.save_combo.addItem("Alpha")
    window.save_combo.setCurrentText("Alpha")
    monkeypatch.setattr(window.backend, "backup_save", mock.Mock(return_value="backup.zip"))
    monkeypatch.setattr(window.backend, "enforce_quota", mock.Mock(return_value=[]))
    monkeypatch.setattr(window.backend, "enforce_keep_last", mock.Mock(return_value=[]))
    ui_module.ZomboidSaverUI.perform_backup(window)

    monkeypatch.setattr(window.backend, "backup_save", mock.Mock(side_effect=RuntimeError("boom")))
    ui_module.ZomboidSaverUI.perform_backup(window)
    critical.assert_called_once()

    class FakeSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback: object) -> None:
            self.callback = callback

    class FakeTrayIcon:
        MessageIcon = SimpleNamespace(Information=1)
        ActivationReason = SimpleNamespace(Trigger=1, DoubleClick=2)

        def __init__(self, icon: object, parent: object) -> None:
            self.icon = icon
            self.parent = parent
            self.activated = FakeSignal()
            self.context_menu = None
            self.tool_tip = ""
            self.shown = False
            self.hidden = False
            self.messages: list[tuple[object, ...]] = []

        @staticmethod
        def isSystemTrayAvailable() -> bool:
            return True

        def setToolTip(self, text: str) -> None:
            self.tool_tip = text

        def setContextMenu(self, menu: object) -> None:
            self.context_menu = menu

        def show(self) -> None:
            self.shown = True

        def hide(self) -> None:
            self.hidden = True

        def showMessage(self, *args: object) -> None:
            self.messages.append(args)

    monkeypatch.setattr(ui_module, "QSystemTrayIcon", FakeTrayIcon)
    monkeypatch.setattr(ui_module.QTimer, "singleShot", lambda delay, callback: callback())
    window.init_tray_icon()
    assert window.tray_icon is not None

    show_normal = mock.Mock()
    activate_window = mock.Mock()
    raise_window = mock.Mock()
    monkeypatch.setattr(window, "showNormal", show_normal)
    monkeypatch.setattr(window, "activateWindow", activate_window)
    monkeypatch.setattr(window, "raise_", raise_window)
    window.restore_from_tray()
    show_normal.assert_called_once_with()
    activate_window.assert_called_once_with()
    raise_window.assert_called_once_with()

    restore_from_tray = mock.Mock()
    monkeypatch.setattr(window, "restore_from_tray", restore_from_tray)
    window.handle_tray_activation(FakeTrayIcon.ActivationReason.Trigger)
    window.handle_tray_activation(FakeTrayIcon.ActivationReason.DoubleClick)
    assert restore_from_tray.call_count == 2

    monkeypatch.setattr(window, "isMinimized", lambda: True)
    hide_window = mock.Mock()
    monkeypatch.setattr(window, "hide", hide_window)
    window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
    hide_window.assert_called_once_with()
    assert window._tray_hint_shown is True

    quit_app = mock.Mock()
    monkeypatch.setattr(qapp, "quit", quit_app)
    window._quit_application()
    quit_app.assert_called_once_with()

    window.close()
    qapp.processEvents()


def test_ui_restore_quota_and_entrypoints(
    test_env: "TestEnvironment", qapp: QApplication, monkeypatch: MonkeyPatch
) -> None:
    mode = test_env.config.settings.default_game_mode
    _prepare_save(test_env.save_root / mode / "Alpha", qapp)
    _prepare_save(test_env.save_root / mode / "Beta", qapp)

    backup_dir = test_env.backup_root / mode / "200_Alpha"
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "snapshot.bin").write_bytes(b"backup")

    window, ui_module = _create_window(qapp, monkeypatch)
    window.save_combo.clear()
    window.save_combo.addItem("Alpha")
    window.save_combo.setCurrentText("Alpha")

    warning = mock.Mock()
    info = mock.Mock()
    critical = mock.Mock()
    question = mock.Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(ui_module.QMessageBox, "warning", warning)
    monkeypatch.setattr(ui_module.QMessageBox, "information", info)
    monkeypatch.setattr(ui_module.QMessageBox, "critical", critical)
    monkeypatch.setattr(ui_module.QMessageBox, "question", question)

    window.backup_list.clear()
    window.restore_backup()
    warning.assert_called_once()

    warning.reset_mock()
    selected_item = _make_selected_backup_item(backup_dir)
    window.backup_list.addItem(selected_item)
    selected_item.setSelected(True)
    window.backup_list.setCurrentItem(selected_item)
    window.restore_backup()
    question.assert_called_once()

    question.reset_mock(return_value=True)
    question.return_value = QMessageBox.StandardButton.Yes
    window.save_combo.clear()
    window.restore_backup()
    warning.assert_called_once()

    warning.reset_mock()
    window.save_combo.addItem("Alpha")
    window.save_combo.setCurrentText("Alpha")
    window.backup_list.clear()
    selected_item = _make_selected_backup_item(backup_dir)
    window.backup_list.addItem(selected_item)
    selected_item.setSelected(True)
    window.backup_list.setCurrentItem(selected_item)

    on_save_selected = mock.Mock()
    monkeypatch.setattr(window, "on_save_selected", on_save_selected)
    monkeypatch.setattr(window.backend, "restore_backup", mock.Mock(return_value="restored-path"))
    window.restore_backup()
    info.assert_called_once()
    on_save_selected.assert_called_once_with("Alpha")

    monkeypatch.setattr(window.backend, "restore_backup", mock.Mock(side_effect=RuntimeError("boom")))
    window.restore_backup()
    critical.assert_called_once()

    window.save_combo.clear()
    window.apply_quota_change()
    status_bar = window.statusBar()
    assert status_bar is not None
    assert status_bar.currentMessage() == "Select a save before updating quota"

    window.save_combo.addItem("Alpha")
    window.save_combo.setCurrentText("Alpha")
    window.quota_spin.setValue(0)
    monkeypatch.setattr(window.backend, "enforce_quota", mock.Mock(return_value=[]))
    load_backups = mock.Mock()
    refresh_controls = mock.Mock()
    monkeypatch.setattr(window, "load_backups", load_backups)
    monkeypatch.setattr(window, "_refresh_quota_controls", refresh_controls)
    window.apply_quota_change()
    load_backups.assert_called_once_with(invalidate_usage=True)
    refresh_controls.assert_called_once_with("Alpha")

    ui_main = importlib.import_module("zomboid_saver.__main__")
    cli_main = mock.Mock()
    monkeypatch.setattr(ui_main.cli, "main", cli_main)
    ui_main.main()
    cli_main.assert_called_once_with()

    ui_module = _import_ui_module()

    class FakeApp:
        def __init__(self, argv: list[str]) -> None:
            self.argv = argv

        def setStyle(self, style: str) -> None:
            self.style = style

        def exec(self) -> int:
            return 0

    fake_window = mock.Mock()
    monkeypatch.setattr(ui_module, "QApplication", FakeApp)
    monkeypatch.setattr(ui_module, "ZomboidSaverUI", mock.Mock(return_value=fake_window))
    monkeypatch.setattr(ui_module.logging, "basicConfig", mock.Mock())

    def fake_exit(code: int) -> None:
        raise SystemExit(code)

    monkeypatch.setattr(ui_module.sys, "exit", fake_exit)
    with pytest.raises(SystemExit) as excinfo:
        ui_module.main()

    assert excinfo.value.code == 0
    fake_window.show.assert_called_once_with()

    window.close()
    qapp.processEvents()
"""PyQt6 front-end for managing Project Zomboid save backups."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnknownArgumentType=false

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional, cast

from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QPalette, QPixmap, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QFrame,
    QGroupBox,
    QGridLayout,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QDialog,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
)

from zomboid_saver.config import (
    resolve_save_quota,
    settings,
    update_compress_folders,
    update_default_game_mode,
    update_game_save_root,
    update_keep_last_n_saves,
    update_save_interval,
    update_save_quota,
)
from zomboid_saver.backend import ZomboidSaverBackend


class PreferencesDialog(QDialog):
    """Dialog allowing users to tweak global preferences."""

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.interval_spin = QSpinBox(self)
        self.interval_spin.setRange(10, 7200)
        self.interval_spin.setSingleStep(30)
        self.interval_spin.setValue(settings.save_interval_sec)
        form_layout.addRow("Auto-save interval (seconds)", self.interval_spin)

        self.keep_last_spin = QSpinBox(self)
        self.keep_last_spin.setRange(0, 200)
        self.keep_last_spin.setValue(settings.keep_last_n_saves)
        form_layout.addRow("Keep last backups", self.keep_last_spin)

        self.compress_checkbox = QCheckBox("Compress backups (ZIP)", self)
        self.compress_checkbox.setChecked(settings.compress_folders)
        form_layout.addRow("Compression", self.compress_checkbox)

        self.game_mode_combo = QComboBox(self)
        self.game_mode_combo.setEditable(True)
        self._populate_game_modes(settings.game_save_root, settings.default_game_mode)
        form_layout.addRow("Default game mode", self.game_mode_combo)

        path_layout = QHBoxLayout()
        self.save_root_edit = QLineEdit(str(settings.game_save_root), self)
        browse_btn = QPushButton("Browse...", self)
        browse_btn.clicked.connect(self._browse_save_root)
        path_layout.addWidget(self.save_root_edit)
        path_layout.addWidget(browse_btn)
        form_layout.addRow("Game save root", path_layout)
        self.save_root_edit.editingFinished.connect(self._save_root_edited)

        layout.addLayout(form_layout)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._result: dict[str, Any] = {}

    def _browse_save_root(self) -> None:
        current_dir = str(self.save_root_edit.text() or settings.game_save_root)
        directory = QFileDialog.getExistingDirectory(self, "Select Game Save Root", current_dir)
        if directory:
            self.save_root_edit.setText(directory)
            self._populate_game_modes(
                Path(directory).expanduser(), self.game_mode_combo.currentText()
            )

    def _save_root_edited(self) -> None:
        text = self.save_root_edit.text().strip()
        if not text:
            return
        self._populate_game_modes(Path(text).expanduser(), self.game_mode_combo.currentText())

    def _populate_game_modes(self, base_path: Path, preferred: Optional[str]) -> None:
        current_choice = (preferred or settings.default_game_mode).strip()
        candidates: list[str] = []
        if base_path.exists():
            candidates = sorted([entry.name for entry in base_path.iterdir() if entry.is_dir()])

        previous_block_state = self.game_mode_combo.blockSignals(True)
        self.game_mode_combo.clear()
        if candidates:
            self.game_mode_combo.addItems(candidates)

        if candidates:
            index = self.game_mode_combo.findText(current_choice)
            if index >= 0:
                self.game_mode_combo.setCurrentIndex(index)
            else:
                fallback = current_choice or candidates[0]
                if fallback:
                    idx = self.game_mode_combo.findText(fallback)
                    if idx >= 0:
                        self.game_mode_combo.setCurrentIndex(idx)
                    else:
                        self.game_mode_combo.setEditText(fallback)
        else:
            fallback = current_choice or settings.default_game_mode
            if fallback:
                self.game_mode_combo.setEditText(fallback)

        self.game_mode_combo.blockSignals(previous_block_state)

    def accept(self) -> None:  # type: ignore[override]
        game_mode = self.game_mode_combo.currentText().strip() or settings.default_game_mode
        save_root = self.save_root_edit.text().strip() or str(settings.game_save_root)
        self._result = {
            "save_interval_sec": int(self.interval_spin.value()),
            "keep_last_n_saves": int(self.keep_last_spin.value()),
            "compress_folders": bool(self.compress_checkbox.isChecked()),
            "default_game_mode": game_mode,
            "game_save_root": save_root,
        }
        super().accept()

    def values(self) -> dict[str, Any]:
        return self._result


class ZomboidSaverUI(QMainWindow):
    """Main UI window for Zomboid Auto-Saver"""

    save_combo: QComboBox
    backup_list: QListWidget
    thumbnail_label: QLabel
    timer_label: QLabel
    char_value: QLabel
    save_usage_label: QLabel
    backup_usage_label: QLabel
    traits_label: QLabel
    manual_save_btn: QPushButton
    refresh_btn: QPushButton
    restore_btn: QPushButton
    quota_spin: QSpinBox
    quota_apply_btn: QPushButton
    timer: QTimer

    disk_usage_ready = pyqtSignal(str, str, int, int, object, object, object)

    def __init__(self) -> None:
        super().__init__()
        self.backend: ZomboidSaverBackend = ZomboidSaverBackend()
        self.next_save_time: float = time.time() + settings.save_interval_sec
        self.auto_save_enabled: bool = True
        self.timer: QTimer = QTimer(self)
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._tray_hint_shown: bool = False
        self._disk_usage_cache: dict[tuple[str, str], tuple[int, int]] = {}
        self._latest_disk_usage_request_key: Optional[tuple[str, str]] = None
        self._disk_usage_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1)
        self._disk_usage_executor_shutdown: bool = False
        self._disk_usage_future: Optional[Future[tuple[int, int]]] = None
        self._disk_usage_request_id: int = 0

        self.disk_usage_ready.connect(self._handle_disk_usage_result)

        self.init_ui()
        self.init_menu()
        self.init_tray_icon()
        self.setup_timer()
        self.load_saves()

    def init_menu(self) -> None:
        """Create the application menu bar with settings entry."""
        menu_bar = self.menuBar()
        if menu_bar is None:
            return

        settings_menu = cast(QMenu, menu_bar.addMenu("Settings"))

        preferences_action = QAction("Preferences...", self)
        preferences_action.triggered.connect(self.open_preferences_dialog)
        settings_menu.addAction(preferences_action)

    def init_tray_icon(self) -> None:
        """Create the system tray icon and context menu if supported."""
        tray_cls: Any = QSystemTrayIcon
        if not tray_cls.isSystemTrayAvailable():
            self.tray_icon = None
            return

        style = self.style()
        if style is None:
            style = QApplication.style()
        if style is None:
            return
        icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        tray_obj: Any = QSystemTrayIcon(icon, self)
        tray_obj.setToolTip("Zomboid Auto-Saver")

        menu: Any = QMenu(self)

        restore_action: Any = QAction("Restore Window", self)
        restore_action.triggered.connect(self.restore_from_tray)
        menu.addAction(restore_action)

        backup_action: Any = QAction("Backup Now", self)
        backup_action.triggered.connect(self.perform_backup)
        menu.addAction(backup_action)

        menu.addSeparator()

        exit_action: Any = QAction("Exit", self)
        exit_action.triggered.connect(self._quit_application)
        menu.addAction(exit_action)

        tray_obj.setContextMenu(menu)
        tray_obj.activated.connect(self.handle_tray_activation)
        tray_obj.show()

        self.tray_icon = cast(QSystemTrayIcon, tray_obj)

    def open_preferences_dialog(self) -> None:
        dialog = PreferencesDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values: dict[str, Any] = dialog.values()
        updated = False
        mode_changed = False
        refresh_backups = False
        path_changed = False

        new_interval = int(values.get("save_interval_sec", settings.save_interval_sec))
        if new_interval != settings.save_interval_sec:
            update_save_interval(new_interval)
            self.next_save_time = time.time() + settings.save_interval_sec
            self.update_timer()
            updated = True

        new_keep_last = int(values.get("keep_last_n_saves", settings.keep_last_n_saves))
        if new_keep_last != settings.keep_last_n_saves:
            update_keep_last_n_saves(new_keep_last)
            updated = True
            refresh_backups = True

        new_compress = bool(values.get("compress_folders", settings.compress_folders))
        if new_compress != settings.compress_folders:
            update_compress_folders(new_compress)
            updated = True

        new_mode = str(values.get("default_game_mode", settings.default_game_mode))
        if new_mode and new_mode != settings.default_game_mode:
            update_default_game_mode(new_mode)
            self.backend.game_mode = settings.default_game_mode
            self.backend.save_to_backup = None
            self.backend.mkfolder_system()
            updated = True
            mode_changed = True

        new_root_text = str(values.get("game_save_root", settings.game_save_root))
        new_root = Path(new_root_text).expanduser()
        if new_root != settings.game_save_root:
            update_game_save_root(new_root)
            self.backend.save_root = settings.game_save_root
            self.backend.save_to_backup = None
            self.backend.mkfolder_system()
            updated = True
            path_changed = True

        if updated:
            pruned: List[str] = []
            if refresh_backups and not mode_changed and not path_changed:
                current_save = self.save_combo.currentText()
                if current_save:
                    pruned = self.backend.enforce_keep_last(current_save)

            if mode_changed or path_changed:
                self._disk_usage_cache.clear()
                self._trigger_disk_usage_update(None)
                self.load_saves()
            elif refresh_backups:
                self.load_backups(invalidate_usage=True)

            if pruned:
                removed_display = ", ".join(Path(path).name for path in pruned)
                self._set_status_message(f"Preferences updated; pruned: {removed_display}")
            else:
                self._set_status_message("Preferences updated")
        else:
            self._set_status_message("Preferences unchanged")

    def handle_tray_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Restore the window from the tray when the icon is triggered."""
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_from_tray()

    def restore_from_tray(self) -> None:
        """Show the main window after being hidden in the tray."""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._tray_hint_shown = False

    def changeEvent(self, a0: Optional[QEvent]) -> None:
        """Hide the window in the tray when minimized."""
        event = a0
        if (
            event is not None
            and event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray_icon
        ):
            QTimer.singleShot(0, self.hide)
            tray_icon_any: Any = self.tray_icon
            if not self._tray_hint_shown:
                tray_icon_any.showMessage(  # type: ignore[call-arg]
                    "Zomboid Auto-Saver",
                    "Still watching your saves from the system tray.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
                self._tray_hint_shown = True
            self._set_status_message("Minimized to system tray")
        super().changeEvent(a0)

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        """Ensure the tray icon disappears once the window closes."""
        self._cancel_disk_usage_future()
        if not self._disk_usage_executor_shutdown:
            self._disk_usage_executor.shutdown(wait=False, cancel_futures=True)
            self._disk_usage_executor_shutdown = True
        if self.tray_icon:
            self.tray_icon.hide()
        super().closeEvent(a0)

    def _quit_application(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _set_status_message(self, message: str) -> None:
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message)

    @staticmethod
    def _format_bytes(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{value:.1f} TB"

    def _make_cache_key(self, game_mode: str, save_name: str) -> tuple[str, str]:
        return (game_mode, save_name)

    def _set_disk_usage_labels(self, save_bytes: int, backup_bytes: int) -> None:
        self.save_usage_label.setText(f"Save Size: {self._format_bytes(save_bytes)}")
        self.backup_usage_label.setText(f"Backups Size: {self._format_bytes(backup_bytes)}")

    def _cancel_disk_usage_future(self) -> None:
        future = self._disk_usage_future
        if future is None:
            return
        future.cancel()
        self._disk_usage_future = None

    def _start_disk_usage_task(self, save_name: str, game_mode: str) -> None:
        self._cancel_disk_usage_future()
        if self._disk_usage_executor_shutdown:
            return
        key = self._make_cache_key(game_mode, save_name)
        self._latest_disk_usage_request_key = key
        self._disk_usage_request_id += 1
        request_id = self._disk_usage_request_id

        future = self._disk_usage_executor.submit(
            self.backend.get_save_disk_usage, save_name, game_mode
        )
        self._disk_usage_future = future

        def on_done(
            fut: Future[tuple[int, int]],
            *,
            result_key: tuple[str, str] = key,
            result_game_mode: str = game_mode,
            result_save_name: str = save_name,
            result_request_id: int = request_id,
        ) -> None:
            if fut.cancelled():
                return
            try:
                save_bytes, backup_bytes = fut.result()
            except Exception:
                save_bytes, backup_bytes = 0, 0

            self.disk_usage_ready.emit(
                result_game_mode,
                result_save_name,
                save_bytes,
                backup_bytes,
                result_request_id,
                result_key,
                fut,
            )

        future.add_done_callback(on_done)

    def _handle_disk_usage_result(
        self,
        game_mode: str,
        save_name: str,
        save_bytes: int,
        backup_bytes: int,
        request_id: object = None,
        key: object = None,
        future_obj: object = None,
    ) -> None:
        future = future_obj if isinstance(future_obj, Future) else None
        if future is not None and self._disk_usage_future is future:
            self._disk_usage_future = None

        cache_key = key if isinstance(key, tuple) else self._make_cache_key(game_mode, save_name)
        self._disk_usage_cache[cache_key] = (save_bytes, backup_bytes)

        request_id_int = request_id if isinstance(request_id, int) else None
        is_latest = request_id_int is None or request_id_int == self._disk_usage_request_id

        current_save = self.save_combo.currentText()
        current_mode = self.backend.game_mode
        matches_current = current_save == save_name and current_mode == game_mode
        is_pending_key = self._latest_disk_usage_request_key == cache_key

        should_update = matches_current or (is_latest and is_pending_key)

        print(
            "[disk-usage-result]",
            f"mode={game_mode}",
            f"save={save_name}",
            f"save_bytes={save_bytes}",
            f"backup_bytes={backup_bytes}",
            f"matches_current={matches_current}",
            f"is_latest={is_latest}",
            f"is_pending={is_pending_key}",
            f"should_update={should_update}",
            flush=True,
        )

        if should_update:
            self._set_disk_usage_labels(save_bytes, backup_bytes)

        if is_latest and is_pending_key:
            self._latest_disk_usage_request_key = None

    def _trigger_disk_usage_update(
        self, save_name: Optional[str], invalidate: bool = False
    ) -> None:
        if not save_name:
            self._cancel_disk_usage_future()
            self.save_usage_label.setText("Save Size: --")
            self.backup_usage_label.setText("Backups Size: --")
            self._latest_disk_usage_request_key = None
            return

        game_mode = self.backend.game_mode
        key = self._make_cache_key(game_mode, save_name)
        if invalidate:
            self._disk_usage_cache.pop(key, None)

        cached = self._disk_usage_cache.get(key)
        if cached:
            self._set_disk_usage_labels(*cached)
        else:
            self.save_usage_label.setText("Save Size: calculating...")
            self.backup_usage_label.setText("Backups Size: calculating...")

        self._start_disk_usage_task(save_name, game_mode)

    def _refresh_quota_controls(self, save_name: Optional[str]) -> None:
        if not hasattr(self, "quota_spin"):
            return

        if not save_name:
            previous = self.quota_spin.blockSignals(True)
            self.quota_spin.setValue(settings.default_save_quota_mb)
            self.quota_spin.blockSignals(previous)
            self.quota_spin.setEnabled(False)
            self.quota_apply_btn.setEnabled(False)
            return

        quota_mb = resolve_save_quota(save_name)
        previous = self.quota_spin.blockSignals(True)
        self.quota_spin.setValue(quota_mb)
        self.quota_spin.blockSignals(previous)
        self.quota_spin.setEnabled(True)
        self.quota_apply_btn.setEnabled(True)

    def apply_quota_change(self) -> None:
        save_name = self.save_combo.currentText()
        if not save_name:
            self._set_status_message("Select a save before updating quota")
            return

        quota_mb = int(self.quota_spin.value())
        update_save_quota(save_name, quota_mb)

        removed = self.backend.enforce_quota(save_name)
        self.load_backups(invalidate_usage=True)
        self._refresh_quota_controls(save_name)

        quota_desc = "unlimited" if quota_mb == 0 else f"{quota_mb} MB"
        if removed:
            removed_display = ", ".join(Path(path).name for path in removed)
            self._set_status_message(f"Quota set to {quota_desc}; pruned: {removed_display}")
        else:
            self._set_status_message(f"Quota for {save_name} set to {quota_desc}")

    def init_ui(self) -> None:
        """Initialize the user interface"""
        self.setWindowTitle("Zomboid Auto-Saver 🧟")
        self.setMinimumSize(900, 700)

        # Apply dark zombie theme
        self.apply_dark_theme()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = self.create_header()
        main_layout.addWidget(header)

        # Content area
        content_layout = QHBoxLayout()

        # Left panel - Save selection and stats
        left_panel = self.create_left_panel()
        content_layout.addWidget(left_panel, 2)

        # Right panel - Thumbnail and timer
        right_panel = self.create_right_panel()
        content_layout.addWidget(right_panel, 1)

        main_layout.addLayout(content_layout)

        # Bottom panel - Backup management
        bottom_panel = self.create_bottom_panel()
        main_layout.addWidget(bottom_panel)

        # Status bar
        self._set_status_message("Ready to protect your saves from the undead...")
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.setStyleSheet("background-color: #1a1a1a; color: #8b0000; padding: 5px;")

    def create_header(self) -> QFrame:
        """Creates the header section"""
        header = QFrame()
        header.setFrameShape(QFrame.Shape.StyledPanel)
        header.setStyleSheet("""
            QFrame {
                background-color: #0d0d0d;
                border: 2px solid #8b0000;
                border-radius: 8px;
                padding: 15px;
            }
        """)

        layout = QVBoxLayout(header)

        title = QLabel("🧟 ZOMBOID AUTO-SAVER 🧟")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #8b0000; border: none; padding: 0;")
        layout.addWidget(title)

        subtitle = QLabel("SURVIVE. BACKUP. REPEAT.")
        subtitle.setFont(QFont("Courier New", 10))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666; border: none; padding: 0;")
        layout.addWidget(subtitle)

        return header

    def create_left_panel(self) -> QGroupBox:
        """Creates the left panel with save selection and stats"""
        panel = QGroupBox("💾 ACTIVE SAVE")
        panel.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        panel.setStyleSheet("""
            QGroupBox {
                color: #8b0000;
                border: 2px solid #8b0000;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #0d0d0d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(panel)

        # Save selector
        selector_label = QLabel("Select Save to Auto-Backup:")
        selector_label.setStyleSheet("color: #bbb; border: none;")
        layout.addWidget(selector_label)

        self.save_combo = QComboBox()
        self.save_combo.setFont(QFont("Courier New", 10))
        self.save_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a;
                color: #0f0;
                border: 2px solid #8b0000;
                border-radius: 5px;
                padding: 8px;
                min-height: 30px;
            }
            QComboBox:hover {
                border: 2px solid #ff0000;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #8b0000;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #0f0;
                border: 2px solid #8b0000;
                selection-background-color: #8b0000;
            }
        """)
        self.save_combo.currentTextChanged.connect(self.on_save_selected)
        layout.addWidget(self.save_combo)

        # Stats display
        stats_frame = QFrame()
        stats_frame.setFrameShape(QFrame.Shape.StyledPanel)
        stats_frame.setStyleSheet("""
            QFrame {
                background-color: #000;
                border: 2px solid #333;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        stats_layout = QGridLayout(stats_frame)

        # Character Name
        char_icon = QLabel("👤")
        char_icon.setFont(QFont("Segoe UI Emoji", 16))
        char_icon.setStyleSheet("border: none;")
        stats_layout.addWidget(char_icon, 0, 0)

        char_label = QLabel("Character:")
        char_label.setStyleSheet("color: #bbb; border: none;")
        stats_layout.addWidget(char_label, 0, 1)

        self.char_value = QLabel("Unknown")
        self.char_value.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self.char_value.setStyleSheet("color: #00ffff; border: none;")
        stats_layout.addWidget(self.char_value, 0, 2)

        self.save_usage_label = QLabel("Save Size: --")
        self.save_usage_label.setStyleSheet("color: #bbb; border: none;")
        stats_layout.addWidget(self.save_usage_label, 1, 0, 1, 3)

        self.backup_usage_label = QLabel("Backups Size: --")
        self.backup_usage_label.setStyleSheet("color: #bbb; border: none;")
        stats_layout.addWidget(self.backup_usage_label, 2, 0, 1, 3)

        # Traits (will be populated dynamically)
        self.traits_label = QLabel("")
        self.traits_label.setFont(QFont("Courier New", 9))
        self.traits_label.setStyleSheet("color: #ffa500; border: none; padding-top: 5px;")
        self.traits_label.setWordWrap(True)
        stats_layout.addWidget(self.traits_label, 3, 0, 1, 3)  # Span all columns below header

        stats_layout.setColumnStretch(2, 1)
        layout.addWidget(stats_frame)

        layout.addStretch()

        return panel

    def create_right_panel(self) -> QGroupBox:
        """Creates the right panel with thumbnail and timer"""
        panel = QGroupBox("📸 PREVIEW")
        panel.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        panel.setStyleSheet("""
            QGroupBox {
                color: #8b0000;
                border: 2px solid #8b0000;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #0d0d0d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(panel)

        # Thumbnail display
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setMinimumSize(300, 200)
        self.thumbnail_label.setStyleSheet("""
            QLabel {
                background-color: #000;
                border: 2px solid #333;
                border-radius: 5px;
                color: #666;
            }
        """)
        self.thumbnail_label.setText("No thumbnail available")
        layout.addWidget(self.thumbnail_label)

        # Timer display
        timer_frame = QFrame()
        timer_frame.setStyleSheet("""
            QFrame {
                background-color: #000;
                border: 2px solid #8b0000;
                border-radius: 5px;
                padding: 15px;
            }
        """)
        timer_layout = QVBoxLayout(timer_frame)

        timer_title = QLabel("⏰ NEXT AUTO-SAVE IN:")
        timer_title.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        timer_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_title.setStyleSheet("color: #bbb; border: none;")
        timer_layout.addWidget(timer_title)

        self.timer_label = QLabel("--:--")
        self.timer_label.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet("color: #0f0; border: none;")
        timer_layout.addWidget(self.timer_label)

        layout.addWidget(timer_frame)

        # Manual save button
        self.manual_save_btn = QPushButton("💾 MANUAL BACKUP NOW")
        self.manual_save_btn.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self.manual_save_btn.setMinimumHeight(50)
        self.manual_save_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b0000;
                color: #fff;
                border: 2px solid #ff0000;
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #ff0000;
                border: 2px solid #fff;
            }
            QPushButton:pressed {
                background-color: #660000;
            }
        """)
        self.manual_save_btn.clicked.connect(self.manual_backup)
        layout.addWidget(self.manual_save_btn)

        return panel

    def create_bottom_panel(self) -> QGroupBox:
        """Creates the bottom panel for backup management"""
        panel = QGroupBox("📦 BACKUP MANAGEMENT")
        panel.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        panel.setStyleSheet("""
            QGroupBox {
                color: #8b0000;
                border: 2px solid #8b0000;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: #0d0d0d;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }
        """)

        layout = QVBoxLayout(panel)

        # Backup list
        list_label = QLabel("Available Backups:")
        list_label.setStyleSheet("color: #bbb; border: none;")
        layout.addWidget(list_label)

        self.backup_list = QListWidget()
        self.backup_list.setFont(QFont("Courier New", 9))
        self.backup_list.setMaximumHeight(150)
        self.backup_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                color: #0f0;
                border: 2px solid #8b0000;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #333;
            }
            QListWidget::item:selected {
                background-color: #8b0000;
                color: #fff;
            }
            QListWidget::item:hover {
                background-color: #330000;
            }
        """)
        layout.addWidget(self.backup_list)

        quota_layout = QHBoxLayout()
        quota_label = QLabel("Per-save quota (MB):")
        quota_label.setStyleSheet("color: #bbb; border: none;")
        quota_layout.addWidget(quota_label)

        self.quota_spin = QSpinBox()
        self.quota_spin.setRange(0, 100000)
        self.quota_spin.setSingleStep(100)
        self.quota_spin.setSuffix(" MB")
        self.quota_spin.setValue(settings.default_save_quota_mb)
        self.quota_spin.setToolTip("Set to 0 to disable size-based pruning for this save.")
        self.quota_spin.setEnabled(False)
        quota_layout.addWidget(self.quota_spin)

        self.quota_apply_btn = QPushButton("Apply Quota")
        self.quota_apply_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.quota_apply_btn.setStyleSheet(self.get_button_style("#552200", "#aa5500"))
        self.quota_apply_btn.setEnabled(False)
        self.quota_apply_btn.clicked.connect(self.apply_quota_change)
        quota_layout.addWidget(self.quota_apply_btn)

        quota_layout.addStretch()
        layout.addLayout(quota_layout)

        # Restore button
        button_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("🔄 Refresh List")
        self.refresh_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self.refresh_btn.setStyleSheet(self.get_button_style("#333", "#555"))
        self.refresh_btn.clicked.connect(lambda: self.load_backups(invalidate_usage=True))
        button_layout.addWidget(self.refresh_btn)

        self.restore_btn = QPushButton("⚠️ RESTORE SELECTED BACKUP")
        self.restore_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self.restore_btn.setStyleSheet(self.get_button_style("#8b6500", "#ffa500"))
        self.restore_btn.clicked.connect(self.restore_backup)
        button_layout.addWidget(self.restore_btn)

        layout.addLayout(button_layout)

        return panel

    def get_button_style(self, bg_color: str, hover_color: str) -> str:
        """Returns a button style string"""
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: #fff;
                border: 2px solid {hover_color};
                border-radius: 5px;
                padding: 10px;
                min-height: 30px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border: 2px solid #fff;
            }}
            QPushButton:pressed {{
                background-color: #000;
            }}
        """

    def apply_dark_theme(self) -> None:
        """Applies a dark zombie-themed color scheme"""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(26, 26, 26))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(200, 200, 200))
        palette.setColor(QPalette.ColorRole.Base, QColor(13, 13, 13))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(26, 26, 26))
        palette.setColor(QPalette.ColorRole.Text, QColor(200, 200, 200))
        palette.setColor(QPalette.ColorRole.Button, QColor(26, 26, 26))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(200, 200, 200))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(139, 0, 0))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

        self.setPalette(palette)

        # Global stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QToolTip {
                background-color: #000;
                color: #0f0;
                border: 2px solid #8b0000;
                padding: 5px;
            }
        """)

    def setup_timer(self) -> None:
        """Sets up the QTimer for periodic updates"""
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)  # Update every second

    def update_timer(self) -> None:
        """Updates the countdown timer and triggers auto-save"""
        time_remaining = int(self.next_save_time - time.time())

        if time_remaining <= 0 and self.auto_save_enabled:
            # Trigger auto-save
            if self.save_combo.currentText():
                self.perform_backup()
            self.next_save_time = time.time() + settings.save_interval_sec
            time_remaining = settings.save_interval_sec

        minutes = time_remaining // 60
        seconds = time_remaining % 60
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")

        # Change color based on time remaining
        if time_remaining < 30:
            self.timer_label.setStyleSheet("color: #ff0000; border: none;")
        elif time_remaining < 60:
            self.timer_label.setStyleSheet("color: #ffa500; border: none;")
        else:
            self.timer_label.setStyleSheet("color: #0f0; border: none;")

    def load_saves(self) -> None:
        """Loads available saves into the combo box"""
        saves = self.backend.get_available_saves()
        self.save_combo.clear()
        self.save_combo.addItems(saves)

        if saves:
            self.save_combo.setCurrentIndex(0)
        else:
            self._refresh_quota_controls(None)
            self._trigger_disk_usage_update(None)

    def on_save_selected(self, save_name: str) -> None:
        """Called when a save is selected"""
        if not save_name:
            self._refresh_quota_controls(None)
            self._trigger_disk_usage_update(None)
            return

        self.backend.save_to_backup = save_name
        self._refresh_quota_controls(save_name)
        self._trigger_disk_usage_update(save_name)

        # Load stats
        stats = self.backend.get_save_stats(save_name)

        # Update character info
        self.char_value.setText(stats.get("character_name", "Unknown"))

        # Update traits
        traits_raw: Any = stats.get("traits", [])
        traits: List[str] = []
        if isinstance(traits_raw, (list, tuple, set)):
            iterable = cast(Iterable[Any], traits_raw)
            traits = [str(t) for t in iterable if t]

        if traits:
            traits_text = "Traits: " + ", ".join(traits)
            self.traits_label.setText(traits_text)
        else:
            self.traits_label.setText("")

        # Load thumbnail
        thumb_path = self.backend.get_thumbnail_path(save_name)
        if thumb_path:
            pixmap = QPixmap(thumb_path)
            scaled_pixmap = pixmap.scaled(
                300,
                200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(scaled_pixmap)
        else:
            self.thumbnail_label.clear()
            self.thumbnail_label.setText("No thumbnail available")

        # Refresh backup list to show only backups for this save
        self.load_backups()

        self._set_status_message(f"Selected save: {save_name}")

    def manual_backup(self) -> None:
        """Performs a manual backup"""
        self.perform_backup()

    def perform_backup(self) -> None:
        """Performs the actual backup operation"""
        save_name: str = self.save_combo.currentText()
        if not save_name:
            QMessageBox.warning(self, "No Save Selected", "Please select a save to backup!")
            return

        try:
            backup_path = self.backend.backup_save(save_name)
            timestamp = datetime.datetime.now().strftime("%I:%M:%S %p")
            self._set_status_message(f"✅ Backup created at {timestamp} - {backup_path}")

            removed_quota = self.backend.enforce_quota(save_name)
            removed_keep_last = self.backend.enforce_keep_last(save_name)
            removed_combined = list(dict.fromkeys(removed_quota + removed_keep_last))
            if removed_combined:
                removed_display = ", ".join(Path(path).name for path in removed_combined)
                self._set_status_message(
                    f"♻️ Backup created at {timestamp}; pruned: {removed_display}"
                )

            # Refresh backup list
            self.load_backups(invalidate_usage=True)
        except Exception as e:
            QMessageBox.critical(self, "Backup Failed", f"Failed to backup save:\n{str(e)}")
            self._set_status_message("❌ Backup failed!")

    def load_backups(self, *, invalidate_usage: bool = False) -> None:
        """Loads the list of available backups filtered by currently selected save"""
        self.backup_list.clear()

        # Get the currently selected save name
        current_save_raw = self.save_combo.currentText()
        current_save: str = str(current_save_raw)
        filter_value: Optional[str] = current_save if current_save else None

        # Get backups filtered by the current save
        backups = self.backend.get_backups(filter_save_name=filter_value)

        for backup in backups:
            # Format the display name
            mod_time = datetime.datetime.fromtimestamp(backup.stat().st_mtime)
            time_str = mod_time.strftime("%Y-%m-%d %I:%M:%S %p")
            display_name = f"{backup.name} [{time_str}]"

            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, str(backup))  # Store full path
            self.backup_list.addItem(item)

        status_msg = f"Found {len(backups)} backup(s)"
        if current_save:
            status_msg += f" for '{current_save}'"
        self._set_status_message(status_msg)

        if current_save and invalidate_usage:
            self._trigger_disk_usage_update(current_save, invalidate=True)

    def restore_backup(self) -> None:
        """Restores a selected backup"""
        selected_items = self.backup_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Backup Selected", "Please select a backup to restore!")
            return

        backup_path = str(selected_items[0].data(Qt.ItemDataRole.UserRole))

        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Restore",
            "⚠️ WARNING ⚠️\n\n"
            "This will OVERWRITE your current save!\n"
            "Make sure the game is closed.\n\n"
            "Do you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        # Ask for target save name
        current_save: str = self.save_combo.currentText()
        if not current_save:
            QMessageBox.warning(self, "No Target Save", "Please select a target save first!")
            return

        try:
            restored_path = self.backend.restore_backup(backup_path, current_save)
            QMessageBox.information(
                self,
                "Restore Successful",
                f"Backup has been restored to:\n{restored_path}\n\nYou can now launch the game!",
            )
            self._set_status_message("✅ Backup restored successfully!")

            # Refresh the display
            self.on_save_selected(current_save)
        except Exception as e:
            QMessageBox.critical(self, "Restore Failed", f"Failed to restore backup:\n{str(e)}")
            self._set_status_message("❌ Restore failed!")


def main() -> None:
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Use Fusion style for better dark theme

    window = ZomboidSaverUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Dark OLED Precision floating HUD interface for QuickTasks."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QSettings, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from db import TaskDB
from google_client import GoogleTasksClient, parse_due_syntax
from sync_engine import SyncManager, SyncWorker

STYLE_PATH = Path(__file__).parent / "styles.qss"


class AuthWorker(QThread):
    auth_succeeded = pyqtSignal()
    auth_failed = pyqtSignal(str)

    def __init__(self, client: GoogleTasksClient):
        super().__init__()
        self.client = client

    def run(self) -> None:
        try:
            self.client.authenticate_interactive(open_browser=True)
            self.auth_succeeded.emit()
        except Exception as e:
            self.auth_failed.emit(str(e))


class TaskRowWidget(QWidget):
    toggle_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, task: Dict[str, Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.task = task
        self.task_id = task["id"]
        self._init_ui()

    def _init_ui(self) -> None:
        self.setFixedHeight(46)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Checkbox button
        is_done = self.task["status"] == "completed"
        self.check_btn = QPushButton("✓" if is_done else "")
        self.check_btn.setProperty("class", "TaskCheckBtn")
        self.check_btn.setProperty("checked", "true" if is_done else "false")
        self.check_btn.setFixedSize(20, 20)
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.check_btn.clicked.connect(lambda: self.toggle_clicked.emit(self.task_id))
        layout.addWidget(self.check_btn)

        # Task Title
        self.title_label = QLabel(self.task["title"])
        font = QFont("-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif", 10)
        if is_done:
            font.setStrikeOut(True)
            self.title_label.setStyleSheet("color: #64748b; font-size: 13px;")
        else:
            self.title_label.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 500;")
        self.title_label.setFont(font)
        layout.addWidget(self.title_label, stretch=1)

        # Due Date Badge
        if self.task.get("due_date"):
            due_iso = self.task["due_date"]
            due_display = due_iso[:10]
            is_overdue = False
            try:
                # Google Tasks dates mean "all-day on this UTC date". 
                # Parse as naive GMT date to match the all-day semantic without shifting it.
                dt = datetime.fromisoformat(due_iso[:10])
                today = datetime.now().date()
                diff_days = (dt.date() - today).days

                if diff_days == 0:
                    due_display = "TODAY"
                elif diff_days == 1:
                    due_display = "TOMORROW"
                elif diff_days == -1:
                    due_display = "YESTERDAY"
                    is_overdue = True
                elif diff_days < -1:
                    date_part = dt.strftime("%b %d").upper()
                    due_display = f"OVERDUE {date_part}"
                    is_overdue = True
                else:
                    date_part = dt.strftime("%b %d").upper()
                    due_display = f"DUE {date_part}"
            except Exception:
                pass

            due_badge = QLabel(due_display)
            if is_overdue and self.task.get("status") != "completed":
                due_badge.setStyleSheet(
                    "color: #f87171; background-color: rgba(239, 68, 68, 0.1); "
                    "border: 1px solid rgba(239, 68, 68, 0.25); "
                    "border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700; "
                    "font-family: ui-monospace, 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace; "
                    "letter-spacing: 0.3px;"
                )
            else:
                due_badge.setStyleSheet(
                    "color: #38bdf8; background-color: rgba(56, 189, 248, 0.08); "
                    "border: 1px solid rgba(56, 189, 248, 0.22); "
                    "border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700; "
                    "font-family: ui-monospace, 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace; "
                    "letter-spacing: 0.3px;"
                )
            layout.addWidget(due_badge)

        # Minimalist Sync Status Dot
        sync_status = self.task.get("sync_status", "pending_create")
        sync_label = QLabel()
        if sync_status == "synced":
            sync_label.setText("● Synced")
            sync_label.setStyleSheet(
                "color: #34d399; background: rgba(52, 211, 153, 0.08); "
                "border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 4px; "
                "padding: 2px 6px; font-size: 10px; font-weight: 600; "
                "font-family: ui-monospace, monospace;"
            )
            sync_label.setToolTip("Synced with Google Tasks")
        else:
            sync_label.setText("○ Local")
            sync_label.setStyleSheet(
                "color: #94a3b8; background: rgba(148, 163, 184, 0.08); "
                "border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 4px; "
                "padding: 2px 6px; font-size: 10px; font-weight: 600; "
                "font-family: ui-monospace, monospace;"
            )
            sync_label.setToolTip("Pending sync with Google Tasks")
        layout.addWidget(sync_label)

        # Delete Button
        self.delete_btn = QPushButton("✕")
        self.delete_btn.setProperty("class", "TaskDeleteBtn")
        self.delete_btn.setFixedSize(22, 22)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_btn.setToolTip("Delete task")
        self.delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.task_id))
        layout.addWidget(self.delete_btn)


class QuickTasksOverlay(QWidget):
    def __init__(self, db: TaskDB, client: GoogleTasksClient, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self.client = client
        self.sync_manager = SyncManager(db, client)
        self.sync_worker = SyncWorker(self.sync_manager, interval_sec=45)
        self.settings = QSettings("QuickTasks", "Overlay")
        self._drag_offset: Optional[QPoint] = None

        self._init_window()
        self._init_layout()
        self._apply_stylesheet()
        self._setup_shortcuts()
        self._setup_sync_worker()
        self.reload_tasks()

    def _init_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumWidth(400)
        self.setMaximumWidth(1200)
        self.setMinimumHeight(240)
        self.setMaximumHeight(900)

        saved_w = self.settings.value("width", 600, type=int)
        saved_h = self.settings.value("height", 480, type=int)
        self.resize(saved_w, saved_h)

    def _init_layout(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)

        # Main OLED Container
        self.container = QFrame(self)
        self.container.setObjectName("OverlayContainer")

        # Soft drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 220))
        shadow.setOffset(0, 6)
        self.container.setGraphicsEffect(shadow)

        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(16, 14, 16, 12)
        container_layout.setSpacing(10)

        # Draggable Header Bar
        self.header_bar = QFrame(self.container)
        self.header_bar.setObjectName("DragHeaderBar")
        self.header_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(2, 0, 2, 0)
        header_layout.setSpacing(8)

        # Title & Badge
        self.brand_label = QLabel("⚡ QUICKTASKS", self.header_bar)
        self.brand_label.setObjectName("BrandLabel")
        self.brand_label.setToolTip("Click and drag to reposition · Double-click to center")
        header_layout.addWidget(self.brand_label)

        self.badge_count_label = QLabel("● 0 ACTIVE", self.header_bar)
        self.badge_count_label.setObjectName("BadgeCountLabel")
        header_layout.addWidget(self.badge_count_label)

        header_layout.addStretch(1)

        # Hide Done Button
        self.hide_done_btn = QPushButton("Hide Done", self.header_bar)
        self.hide_done_btn.setObjectName("HideDoneButton")
        self.hide_done_btn.setCheckable(True)
        self.hide_done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_done_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        saved_hide_done = self.settings.value("hide_done", False, type=bool)
        self.hide_done_btn.setChecked(saved_hide_done)
        self._update_hide_done_btn_label(saved_hide_done)
        self.hide_done_btn.toggled.connect(self._on_toggle_hide_done)
        header_layout.addWidget(self.hide_done_btn)

        # Close Button
        self.close_btn = QPushButton("✕", self.header_bar)
        self.close_btn.setObjectName("CloseButton")
        self.close_btn.setToolTip("Dismiss (Esc or Super+Shift+T)")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.close_btn)

        container_layout.addWidget(self.header_bar)

        # Task Input Box
        self.input_field = QLineEdit(self)
        self.input_field.setObjectName("TaskInput")
        self.input_field.setPlaceholderText("Add task (e.g. Audit SSH config /due:tomorrow) or type to filter...")
        self.input_field.returnPressed.connect(self._on_enter_pressed)
        self.input_field.textChanged.connect(self._on_text_changed)
        container_layout.addWidget(self.input_field)

        # Center: Task List
        self.task_list = QListWidget(self)
        self.task_list.setObjectName("TaskList")
        self.task_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.task_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.task_list.itemClicked.connect(self._on_item_clicked)
        container_layout.addWidget(self.task_list, stretch=1)

        # Install event filters
        self.input_field.installEventFilter(self)
        self.task_list.installEventFilter(self)
        self.header_bar.installEventFilter(self)
        self.brand_label.installEventFilter(self)
        self.container.installEventFilter(self)

        # Bottom Bar: Status & Keycap hints
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 4, 2, 0)
        footer_layout.setSpacing(10)

        # Google Sync status
        self.sync_status_label = QLabel("● Google Tasks: Synced", self)
        self.sync_status_label.setObjectName("SyncStatusConnected")
        footer_layout.addWidget(self.sync_status_label)

        self.auth_button = QPushButton("Connect Account", self)
        self.auth_button.setObjectName("AuthButton")
        self.auth_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auth_button.clicked.connect(self._on_connect_clicked)
        self.auth_button.hide()
        footer_layout.addWidget(self.auth_button)

        footer_layout.addStretch(1)

        self.hints_label = QLabel(self)
        self.hints_label.setText(
            '<span style="color: #64748b; font-size: 10px; font-family: ui-monospace, monospace;">'
            '<span style="background: #0d121d; border: 1px solid #1e283d; border-radius: 3px; padding: 1px 5px; color: #94a3b8;">↵ Add</span>&nbsp;&nbsp;'
            '<span style="background: #0d121d; border: 1px solid #1e283d; border-radius: 3px; padding: 1px 5px; color: #94a3b8;">Space Toggle</span>&nbsp;&nbsp;'
            '<span style="background: #0d121d; border: 1px solid #1e283d; border-radius: 3px; padding: 1px 5px; color: #94a3b8;">Del Delete</span>&nbsp;&nbsp;'
            '<span style="background: #0d121d; border: 1px solid #1e283d; border-radius: 3px; padding: 1px 5px; color: #94a3b8;">Esc Dismiss</span>'
            '</span>'
        )
        footer_layout.addWidget(self.hints_label)

        self.size_grip = QSizeGrip(self)
        self.size_grip.setObjectName("WindowSizeGrip")
        footer_layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)

        container_layout.addLayout(footer_layout)
        root_layout.addWidget(self.container)

    def _apply_stylesheet(self) -> None:
        if STYLE_PATH.exists():
            with open(STYLE_PATH, "r") as f:
                self.setStyleSheet(f.read())

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.hide)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.hide_done_btn.toggle)

    def _update_hide_done_btn_label(self, checked: bool) -> None:
        if checked:
            self.hide_done_btn.setText("Active Only")
            self.hide_done_btn.setToolTip("Showing active tasks only. Click to show all")
        else:
            self.hide_done_btn.setText("Hide Done")
            self.hide_done_btn.setToolTip("Click to hide completed tasks")

    def _on_toggle_hide_done(self, checked: bool) -> None:
        self.settings.setValue("hide_done", checked)
        self._update_hide_done_btn_label(checked)
        self.reload_tasks()

    def _get_visible_task_indices(self) -> List[int]:
        return [i for i in range(self.task_list.count()) if not self.task_list.item(i).isHidden()]

    def _start_drag(self, global_pos: QPoint) -> None:
        self._drag_offset = global_pos - self.pos()
        QApplication.setOverrideCursor(Qt.CursorShape.ClosedHandCursor)

    def _do_drag(self, global_pos: QPoint) -> None:
        if self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)

    def _end_drag(self) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            QApplication.restoreOverrideCursor()
            self.save_window_position()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._do_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._end_drag()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.header_bar, self.brand_label, self.container):
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._start_drag(event.globalPosition().toPoint())
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if event.buttons() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
                    self._do_drag(event.globalPosition().toPoint())
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._drag_offset is not None:
                    self._end_drag()
                    return True
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                if watched in (self.header_bar, self.brand_label):
                    self._center_on_primary_screen()
                    self.save_window_position()
                    return True

        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            vis = self._get_visible_task_indices()

            if watched == self.input_field:
                if key == Qt.Key.Key_Down:
                    if vis:
                        curr = self.task_list.currentRow()
                        if curr == -1 or curr not in vis:
                            self.task_list.setCurrentRow(vis[0])
                        else:
                            next_indices = [i for i in vis if i > curr]
                            if next_indices:
                                self.task_list.setCurrentRow(next_indices[0])
                        if self.task_list.currentItem():
                            self.task_list.scrollToItem(self.task_list.currentItem())
                    return True

                elif key == Qt.Key.Key_Up:
                    if vis:
                        curr = self.task_list.currentRow()
                        if curr != -1:
                            if curr <= vis[0]:
                                self.task_list.setCurrentRow(-1)
                            else:
                                prev_indices = [i for i in vis if i < curr]
                                if prev_indices:
                                    self.task_list.setCurrentRow(prev_indices[-1])
                            if self.task_list.currentItem():
                                self.task_list.scrollToItem(self.task_list.currentItem())
                    return True

                elif key == Qt.Key.Key_Tab:
                    if vis:
                        self.task_list.setFocus()
                        if self.task_list.currentRow() == -1:
                            self.task_list.setCurrentRow(vis[0])
                        return True

                elif key == Qt.Key.Key_Space:
                    if not self.input_field.text():
                        curr = self.task_list.currentItem()
                        if curr:
                            self._toggle_selected_task()
                            return True

                elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    if not self.input_field.text():
                        curr = self.task_list.currentItem()
                        if curr:
                            self._delete_selected_task()
                            return True

            elif watched == self.task_list:
                if key == Qt.Key.Key_Up:
                    curr = self.task_list.currentRow()
                    if not vis or curr <= vis[0]:
                        self.task_list.setCurrentRow(-1)
                        self.input_field.setFocus()
                        self.input_field.setCursorPosition(len(self.input_field.text()))
                        return True

                elif key == Qt.Key.Key_Tab:
                    self.input_field.setFocus()
                    return True

                elif key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._toggle_selected_task()
                    return True

                elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._delete_selected_task()
                    return True

                elif event.text() and event.text().isprintable() and not (
                    event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
                ):
                    self.input_field.setFocus()
                    self.input_field.setText(self.input_field.text() + event.text())
                    self.input_field.setCursorPosition(len(self.input_field.text()))
                    return True

        return super().eventFilter(watched, event)

    def _setup_sync_worker(self) -> None:
        self.sync_worker.sync_started.connect(self._on_sync_started)
        self.sync_worker.sync_finished.connect(self._on_sync_finished)
        self.sync_worker.sync_failed.connect(self._on_sync_failed)
        self.sync_worker.auth_needed.connect(self._on_auth_needed)
        self.sync_worker.start()

    def _on_sync_started(self) -> None:
        self.sync_status_label.setText("● Google Tasks: Syncing...")
        self.sync_status_label.setObjectName("SyncStatusConnected")
        self.sync_status_label.setStyleSheet("color: #38bdf8; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.hide()

    def _on_sync_finished(self, count: int) -> None:
        self.sync_status_label.setText("● Google Tasks: Synced")
        self.sync_status_label.setObjectName("SyncStatusConnected")
        self.sync_status_label.setStyleSheet("color: #34d399; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.hide()
        self.reload_tasks()

    def _on_sync_failed(self, error: str) -> None:
        if "disabled" in error.lower() or "not been used in project" in error.lower():
            self.sync_status_label.setText("⚠ API Disabled in Console")
        else:
            self.sync_status_label.setText("⚠ Sync Disconnected")
        self.sync_status_label.setToolTip(error)
        self.sync_status_label.setStyleSheet("color: #f59e0b; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")

    def _on_auth_needed(self) -> None:
        self.sync_status_label.setText("○ Google Tasks: Disconnected")
        self.sync_status_label.setStyleSheet("color: #94a3b8; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.show()

    def _on_connect_clicked(self) -> None:
        self.sync_status_label.setText("Waiting for browser auth...")
        self.sync_status_label.setStyleSheet("color: #38bdf8; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.setEnabled(False)
        self.auth_worker = AuthWorker(self.client)
        self.auth_worker.auth_succeeded.connect(self._on_auth_worker_success)
        self.auth_worker.auth_failed.connect(self._on_auth_worker_failure)
        self.auth_worker.start()

    def _on_auth_worker_success(self) -> None:
        self.sync_status_label.setText("● Google Tasks: Synced")
        self.sync_status_label.setStyleSheet("color: #34d399; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.hide()
        self.auth_button.setEnabled(True)
        self.sync_worker.trigger_immediate_sync()
        self.reload_tasks()

    def _on_auth_worker_failure(self, err: str) -> None:
        self.sync_status_label.setText("Auth failed")
        self.sync_status_label.setStyleSheet("color: #ef4444; font-family: ui-monospace, monospace; font-size: 11px; font-weight: 600;")
        self.auth_button.setEnabled(True)

    def _toggle_selected_task(self) -> None:
        current_item = self.task_list.currentItem()
        if current_item:
            task_id = current_item.data(Qt.ItemDataRole.UserRole)
            if task_id:
                self._toggle_task(task_id)

    def _delete_selected_task(self) -> None:
        current_item = self.task_list.currentItem()
        if current_item:
            task_id = current_item.data(Qt.ItemDataRole.UserRole)
            if task_id:
                self._delete_task(task_id)

    def _toggle_task(self, task_id: str) -> None:
        self.db.toggle_task_status(task_id)
        self.sync_worker.trigger_immediate_sync()
        self.reload_tasks()

    def _delete_task(self, task_id: str) -> None:
        self.db.mark_deleted(task_id)
        self.sync_worker.trigger_immediate_sync()
        self.reload_tasks()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.task_list.setCurrentItem(item)

    def _on_enter_pressed(self) -> None:
        text = self.input_field.text().strip()
        if not text:
            if self.task_list.currentItem():
                self._toggle_selected_task()
            return

        title, due = parse_due_syntax(text)
        if title:
            self.db.add_task(title=title, due_date=due)
            self.input_field.clear()
            self.task_list.setCurrentRow(-1)
            self.sync_worker.trigger_immediate_sync()
            self.reload_tasks()

    def _on_text_changed(self, text: str) -> None:
        cleaned_query = re.sub(r'/due:(?:"[^"]*"|\'[^\']*\'|\S+.*)', '', text, flags=re.IGNORECASE).strip().lower()
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            row_widget = self.task_list.itemWidget(item)
            if isinstance(row_widget, TaskRowWidget):
                matches = cleaned_query in row_widget.task["title"].lower() if cleaned_query else True
                item.setHidden(not matches)

    def reload_tasks(self) -> None:
        tasks = self.db.list_active_tasks()
        selected_id = None
        current_item = self.task_list.currentItem()
        if current_item:
            selected_id = current_item.data(Qt.ItemDataRole.UserRole)

        self.task_list.clear()

        hide_done = getattr(self, "hide_done_btn", None) and self.hide_done_btn.isChecked()
        displayed_tasks = [t for t in tasks if not (hide_done and t["status"] == "completed")]

        uncompleted = sum(1 for t in tasks if t["status"] == "needsAction")
        hidden_done_count = len(tasks) - len(displayed_tasks)

        self.badge_count_label.setText(f"● {uncompleted} ACTIVE")

        for task in displayed_tasks:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            row_widget = TaskRowWidget(task)
            row_widget.toggle_clicked.connect(self._toggle_task)
            row_widget.delete_clicked.connect(self._delete_task)

            item.setSizeHint(QSize(0, 48))
            self.task_list.addItem(item)
            self.task_list.setItemWidget(item, row_widget)

            if selected_id and task["id"] == selected_id:
                self.task_list.setCurrentItem(item)

        if not displayed_tasks:
            empty_widget = QWidget()
            e_layout = QVBoxLayout(empty_widget)
            e_layout.setContentsMargins(16, 24, 16, 24)
            e_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_layout.setSpacing(6)

            title_lbl = QLabel("No active tasks", empty_widget)
            title_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 600;")
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            sub_lbl = QLabel("Type in the command bar above and press Enter", empty_widget)
            sub_lbl.setStyleSheet("color: #64748b; font-size: 11px; font-family: ui-monospace, monospace;")
            sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            e_layout.addWidget(title_lbl)
            e_layout.addWidget(sub_lbl)

            empty_item = QListWidgetItem()
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setSizeHint(QSize(0, 80))
            self.task_list.addItem(empty_item)
            self.task_list.setItemWidget(empty_item, empty_widget)

    def save_window_position(self) -> None:
        self.settings.setValue("pos_x", self.pos().x())
        self.settings.setValue("pos_y", self.pos().y())

    def save_window_geometry(self) -> None:
        self.save_window_position()
        self.settings.setValue("width", self.width())
        self.settings.setValue("height", self.height())

    def hideEvent(self, event) -> None:
        self.save_window_geometry()
        super().hideEvent(event)

    def _center_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = screen_geo.x() + (screen_geo.width() - self.width()) // 2
            y = screen_geo.y() + int(screen_geo.height() * 0.12)
            self.move(x, y)

    def _restore_saved_position(self) -> bool:
        x = self.settings.value("pos_x", None)
        y = self.settings.value("pos_y", None)
        if x is None or y is None:
            return False
        try:
            x, y = int(x), int(y)
        except (ValueError, TypeError):
            return False

        w = self.width() or 600
        header_rect = QRect(x, y, min(w, 200), 50)
        for screen in QApplication.screens():
            if screen.geometry().intersects(header_rect):
                self.move(x, y)
                return True
        return False

    def show_window(self, force_center: bool = False) -> None:
        if force_center or not self._restore_saved_position():
            self._center_on_primary_screen()

        self.show()
        self.raise_()
        self.activateWindow()
        self.input_field.setFocus()
        self.input_field.selectAll()

    def show_centered(self) -> None:
        self.show_window(force_center=True)

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.reload_tasks()
            self.show_window()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self.save_window_geometry()
        self.sync_worker.stop()
        self.sync_worker.wait()
        super().closeEvent(event)

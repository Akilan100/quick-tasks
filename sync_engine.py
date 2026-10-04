"""Bidirectional synchronization engine between TaskDB and Google Tasks."""

import time
from typing import Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from db import TaskDB
from google_client import GoogleTasksClient


class SyncManager:
    def __init__(self, db: TaskDB, client: GoogleTasksClient):
        self.db = db
        self.client = client

    def push_pending(self) -> int:
        if not self.client.is_authenticated():
            return 0

        pending = self.db.get_pending_sync_tasks()
        synced_count = 0

        for task in pending:
            status = task["sync_status"]
            google_id = task["google_id"]

            if status == "pending_create":
                created = self.client.create_task(
                    title=task["title"],
                    notes=task["notes"],
                    due=task["due_date"]
                )
                if created and "id" in created:
                    if task["status"] == "completed":
                        self.client.update_task(created["id"], status="completed")
                    self.db.mark_synced(task["id"], google_id=created["id"])
                    synced_count += 1

            elif status == "pending_update":
                if google_id:
                    try:
                        res = self.client.update_task(
                            google_id=google_id,
                            title=task["title"],
                            notes=task["notes"],
                            due=task["due_date"],
                            status=task["status"]
                        )
                        if res:
                            self.db.mark_synced(task["id"])
                            synced_count += 1
                    except Exception as e:
                        if "404" in str(e):
                            # Already deleted remotely on Google Tasks
                            self.db.purge_deleted_task(task["id"])
                        else:
                            raise
                else:
                    created = self.client.create_task(
                        title=task["title"],
                        notes=task["notes"],
                        due=task["due_date"]
                    )
                    if created and "id" in created:
                        self.db.mark_synced(task["id"], google_id=created["id"])
                        synced_count += 1

            elif status == "pending_delete":
                if google_id:
                    try:
                        self.client.delete_task(google_id)
                    except Exception as e:
                        if "404" not in str(e):
                            raise
                self.db.purge_deleted_task(task["id"])
                synced_count += 1

        return synced_count

    def pull_remote(self) -> int:
        if not self.client.is_authenticated():
            return 0

        remote_tasks = self.client.list_all_tasks(show_completed=True, show_hidden=True)
        for item in remote_tasks:
            self.db.upsert_remote_task(item)
        return len(remote_tasks)

    def sync_cycle(self) -> int:
        if not self.client.is_authenticated():
            return 0
        pushed = self.push_pending()
        pulled = self.pull_remote()
        return pushed + pulled


class SyncWorker(QThread):
    sync_started = pyqtSignal()
    sync_finished = pyqtSignal(int)
    sync_failed = pyqtSignal(str)
    auth_needed = pyqtSignal()

    def __init__(self, sync_manager: SyncManager, interval_sec: int = 60, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.sync_manager = sync_manager
        self.interval_sec = interval_sec
        self._running = True
        self._sync_requested = False

    def trigger_immediate_sync(self) -> None:
        self._sync_requested = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        last_check = 0.0
        while self._running:
            now = time.time()
            if self._sync_requested or (now - last_check >= self.interval_sec):
                self._sync_requested = False
                last_check = now

                if not self.sync_manager.client.is_authenticated():
                    self.auth_needed.emit()
                    time.sleep(2.0)
                    continue

                self.sync_started.emit()
                try:
                    count = self.sync_manager.sync_cycle()
                    self.sync_finished.emit(count)
                except Exception as e:
                    self.sync_failed.emit(str(e))

            time.sleep(0.5)

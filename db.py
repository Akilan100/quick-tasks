"""Local SQLite storage engine for QuickTasks with offline-first synchronization tracking."""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

DEFAULT_DB_PATH = Path.home() / ".local/share/quick-tasks/tasks.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    google_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    due_date TEXT,
                    status TEXT CHECK(status IN ('needsAction', 'completed')) DEFAULT 'needsAction',
                    completed_at TEXT,
                    sync_status TEXT CHECK(sync_status IN ('synced', 'pending_create', 'pending_update', 'pending_delete')) DEFAULT 'pending_create',
                    updated_at TEXT NOT NULL,
                    deleted INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, deleted);
                CREATE INDEX IF NOT EXISTS idx_tasks_sync_status ON tasks(sync_status);
                CREATE INDEX IF NOT EXISTS idx_tasks_google_id ON tasks(google_id);
            """)

    def add_task(
        self,
        title: str,
        notes: str = "",
        due_date: Optional[str] = None,
        google_id: Optional[str] = None,
        sync_status: str = "pending_create"
    ) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, google_id, title, notes, due_date, status, sync_status, updated_at, deleted)
                VALUES (?, ?, ?, ?, ?, 'needsAction', ?, ?, 0)
                """,
                (task_id, google_id, title.strip(), notes.strip(), due_date, sync_status, now)
            )
        return self.get_task(task_id)  # type: ignore

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_task_by_google_id(self, google_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE google_id = ?", (google_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_active_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM tasks
                WHERE deleted = 0
                ORDER BY 
                    CASE WHEN status = 'needsAction' THEN 0 ELSE 1 END,
                    CASE WHEN due_date IS NOT NULL THEN 0 ELSE 1 END,
                    due_date ASC,
                    updated_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def toggle_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return None

        new_status = "completed" if task["status"] == "needsAction" else "needsAction"
        completed_at = utc_now_iso() if new_status == "completed" else None
        now = utc_now_iso()
        new_sync = "pending_create" if task["sync_status"] == "pending_create" else "pending_update"

        with self._connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, completed_at = ?, sync_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, completed_at, new_sync, now, task_id)
            )
        return self.get_task(task_id)

    def mark_deleted(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False

        now = utc_now_iso()
        with self._connection() as conn:
            if not task["google_id"]:
                # Never reached Google Tasks, safe to hard delete
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            else:
                # Mark for remote deletion
                conn.execute(
                    """
                    UPDATE tasks
                    SET deleted = 1, sync_status = 'pending_delete', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, task_id)
                )
        return True

    def get_pending_sync_tasks(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM tasks WHERE sync_status != 'synced'"
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_synced(self, task_id: str, google_id: Optional[str] = None) -> None:
        with self._connection() as conn:
            if google_id:
                conn.execute(
                    "UPDATE tasks SET sync_status = 'synced', google_id = ? WHERE id = ?",
                    (google_id, task_id)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET sync_status = 'synced' WHERE id = ?",
                    (task_id,)
                )

    def purge_deleted_task(self, task_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def upsert_remote_task(self, google_task: Dict[str, Any]) -> None:
        google_id = google_task["id"]
        title = google_task.get("title", "").strip()
        notes = google_task.get("notes", "") or ""
        due_date = google_task.get("due")
        status = google_task.get("status", "needsAction")
        completed_at = google_task.get("completed")
        updated_at = google_task.get("updated", utc_now_iso())
        is_deleted = 1 if google_task.get("deleted", False) else 0

        with self._connection() as conn:
            cur = conn.execute("SELECT id, sync_status, updated_at FROM tasks WHERE google_id = ?", (google_id,))
            existing = cur.fetchone()

            if existing:
                # If there are local unpushed changes, don't overwrite blindly
                if existing["sync_status"] != "synced":
                    return

                if is_deleted:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (existing["id"],))
                else:
                    conn.execute(
                        """
                        UPDATE tasks
                        SET title = ?, notes = ?, due_date = ?, status = ?, completed_at = ?,
                            sync_status = 'synced', updated_at = ?, deleted = 0
                        WHERE id = ?
                        """,
                        (title, notes, due_date, status, completed_at, updated_at, existing["id"])
                    )
            else:
                if not is_deleted and title:
                    new_id = str(uuid.uuid4())
                    conn.execute(
                        """
                        INSERT INTO tasks (id, google_id, title, notes, due_date, status, completed_at, sync_status, updated_at, deleted)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'synced', ?, 0)
                        """,
                        (new_id, google_id, title, notes, due_date, status, completed_at, updated_at)
                    )

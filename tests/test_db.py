"""Unit tests for TaskDB."""

import tempfile
import unittest
from pathlib import Path
from db import TaskDB


class TestTaskDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tasks.db"
        self.db = TaskDB(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_list_tasks(self):
        task = self.db.add_task(title="Deploy honeypot", notes="Check port 8080", due_date="2026-09-24T00:00:00Z")
        self.assertEqual(task["title"], "Deploy honeypot")
        self.assertEqual(task["notes"], "Check port 8080")
        self.assertEqual(task["status"], "needsAction")
        self.assertEqual(task["sync_status"], "pending_create")

        active = self.db.list_active_tasks()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], task["id"])

    def test_toggle_task_status(self):
        task = self.db.add_task(title="Rotate SSH keys")
        toggled = self.db.toggle_task_status(task["id"])
        self.assertEqual(toggled["status"], "completed")
        self.assertIsNotNone(toggled["completed_at"])

        untoggled = self.db.toggle_task_status(task["id"])
        self.assertEqual(untoggled["status"], "needsAction")
        self.assertIsNone(untoggled["completed_at"])

    def test_deletion_behavior(self):
        # Local-only task: hard deletes directly
        local_task = self.db.add_task(title="Local scratchpad")
        self.assertTrue(self.db.mark_deleted(local_task["id"]))
        self.assertIsNone(self.db.get_task(local_task["id"]))

        # Synced task: soft deletes to preserve sync tombstone
        remote_task = self.db.add_task(title="Cloud rule", google_id="gtask_123", sync_status="synced")
        self.assertTrue(self.db.mark_deleted(remote_task["id"]))
        marked = self.db.get_task(remote_task["id"])
        self.assertEqual(marked["deleted"], 1)
        self.assertEqual(marked["sync_status"], "pending_delete")

        # Excluded from active tasks
        active = self.db.list_active_tasks()
        self.assertEqual(len(active), 0)

    def test_remote_upsert(self):
        google_payload = {
            "id": "g_abc_999",
            "title": "Investigate Wazuh alert",
            "notes": "Suricata dropped rule",
            "due": "2026-09-25T12:00:00Z",
            "status": "needsAction",
            "updated": "2026-09-23T10:00:00Z"
        }
        self.db.upsert_remote_task(google_payload)
        task = self.db.get_task_by_google_id("g_abc_999")
        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "Investigate Wazuh alert")
        self.assertEqual(task["sync_status"], "synced")


if __name__ == "__main__":
    unittest.main()

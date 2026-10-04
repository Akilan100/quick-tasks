"""Main entrypoint and CLI dispatcher for QuickTasks."""

import argparse
import os
import signal
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from db import TaskDB
from google_client import GoogleTasksClient
from ipc import IPCServer, send_ipc_command
from ui import QuickTasksOverlay


def run_daemon() -> int:
    # Ensure DISPLAY is set on Linux
    if os.name == 'posix' and "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"

    app = QApplication(sys.argv)
    app.setApplicationName("QuickTasks")
    app.setQuitOnLastWindowClosed(False)

    db = TaskDB()
    client = GoogleTasksClient()
    overlay = QuickTasksOverlay(db=db, client=client)

    ipc = IPCServer()
    if not ipc.start():
        print("QuickTasks daemon is already running.")
        return 1

    def handle_command(cmd: str):
        cmd = cmd.strip().upper()
        if cmd == "TOGGLE":
            overlay.toggle_visibility()
        elif cmd == "SHOW":
            overlay.reload_tasks()
            overlay.show_window()
        elif cmd == "CENTER":
            overlay.show_centered()
        elif cmd == "HIDE":
            overlay.hide()
        elif cmd == "SYNC":
            overlay.sync_worker.trigger_immediate_sync()
        elif cmd == "RELOAD":
            overlay.reload_tasks()
        elif cmd == "QUIT":
            ipc.stop()
            app.quit()

    ipc.command_received.connect(handle_command)

    # Clean signal handling for systemd / SIGTERM / SIGINT
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    print("QuickTasks daemon started successfully.")
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description="QuickTasks: Fast Dark OLED To-Do Overlay with Google Tasks Sync")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("daemon", help="Run background daemon service")
    subparsers.add_parser("toggle", help="Toggle overlay visibility via IPC")
    subparsers.add_parser("show", help="Show overlay window")
    subparsers.add_parser("hide", help="Hide overlay window")
    subparsers.add_parser("sync", help="Trigger Google Tasks sync")
    subparsers.add_parser("center", help="Reset overlay window to center of primary screen")
    subparsers.add_parser("auth", help="Authenticate with Google Tasks via browser")
    subparsers.add_parser("status", help="Check daemon and sync status")

    add_parser = subparsers.add_parser("add", help="Add a task directly from CLI")
    add_parser.add_argument("task_text", nargs="+", help="Task title with optional /due:today")

    args = parser.parse_args()

    if not args.command or args.command == "toggle":
        # Default behavior: toggle overlay
        if not send_ipc_command("TOGGLE"):
            print("QuickTasks daemon not responding. Attempting to start daemon...")
            import subprocess
            
            # Start gracefully detached
            if os.name == 'nt':
                python_exe = sys.executable.replace('python.exe', 'pythonw.exe')
                if not os.path.exists(python_exe):
                    python_exe = sys.executable
                kwargs = {'creationflags': 0x08000000} # CREATE_NO_WINDOW
                subprocess.Popen([python_exe, str(Path(__file__).resolve()), "daemon"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "daemon"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            import time
            for _ in range(15):
                time.sleep(0.1)
                if send_ipc_command("SHOW"):
                    return 0
            print("Failed to start daemon.")
            return 1
        return 0

    if args.command == "daemon":
        return run_daemon()

    elif args.command == "show":
        if not send_ipc_command("SHOW"):
            print("Daemon not running. Start with 'quick-tasks daemon'.")
            return 1
        return 0

    elif args.command == "hide":
        if not send_ipc_command("HIDE"):
            print("Daemon not running.")
            return 1
        return 0

    elif args.command == "center":
        if not send_ipc_command("CENTER"):
            print("Daemon not running.")
            return 1
        return 0

    elif args.command == "sync":
        print("Synchronizing with Google Tasks...")
        from sync_engine import SyncManager
        db = TaskDB()
        client = GoogleTasksClient()
        if not client.is_authenticated():
            print("Error: Google Tasks not authenticated. Run 'quick-tasks auth' first.")
            return 1
        mgr = SyncManager(db, client)
        try:
            count = mgr.sync_cycle()
            print(f"Sync complete. {count} items processed.")
            send_ipc_command("RELOAD")
            return 0
        except Exception as e:
            print(f"Sync failed:\n{e}")
            return 1

    elif args.command == "auth":
        print("Initiating Google Tasks OAuth flow...")
        client = GoogleTasksClient()
        success = client.authenticate_interactive(open_browser=True)
        if success:
            print("Authentication successful! Token saved to ~/.config/quick-tasks/token.json.")
            send_ipc_command("SYNC")
            return 0
        else:
            print("Authentication failed.")
            return 1

    elif args.command == "status":
        daemon_active = send_ipc_command("PING")
        client = GoogleTasksClient()
        auth_active = client.is_authenticated()
        db = TaskDB()
        active_tasks = db.list_active_tasks()
        pending_tasks = db.get_pending_sync_tasks()

        print(f"Daemon Running: {'Yes' if daemon_active else 'No'}")
        print(f"Google Tasks Authenticated: {'Yes' if auth_active else 'No'}")
        if auth_active:
            ok, msg = client.verify_api_enabled()
            if ok:
                print("Google Tasks API Status: Connected and active ✔")
            else:
                print(f"Google Tasks API Status: ⚠ Inactive/Blocked\n  -> {msg}")
        print(f"Active Tasks in DB: {len(active_tasks)}")
        print(f"Pending Sync Mutations: {len(pending_tasks)}")
        return 0

    elif args.command == "add":
        full_text = " ".join(args.task_text)
        from google_client import parse_due_syntax
        title, due = parse_due_syntax(full_text)
        db = TaskDB()
        task = db.add_task(title=title, due_date=due)
        print(f"Added task [{task['id'][:8]}]: '{task['title']}' (due: {task['due_date']})")
        send_ipc_command("SYNC")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

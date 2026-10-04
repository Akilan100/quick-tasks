"""IPC Socket server and client for ultra-fast hotkey response."""

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QEventLoop, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


def get_socket_path() -> str:
    # On Windows, QLocalServer uses this string directly as a Named Pipe name.
    # On Linux/macOS, it uses it as a file path.
    if os.name == 'nt':
        return "quick_tasks_socket"
    
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and Path(runtime_dir).exists():
        return str(Path(runtime_dir) / "quick-tasks.sock")
    return str(Path.home() / ".local/share/quick-tasks/quick-tasks.sock")


def send_ipc_command(command: str = "TOGGLE", timeout: float = 1.0) -> bool:
    sock_path = get_socket_path()
    
    # QLocalSocket requires a QCoreApplication or QApplication to event-pump properly,
    # but QLocalSocket.waitForConnected() handles its own loop natively.
    client = QLocalSocket()
    client.connectToServer(sock_path)
    
    if not client.waitForConnected(int(timeout * 1000)):
        return False

    try:
        client.write((command.strip() + "\n").encode("utf-8"))
        client.flush()
        if not client.waitForReadyRead(int(timeout * 1000)):
            client.disconnectFromServer()
            return False
            
        data = client.readAll().data().decode("utf-8")
        client.disconnectFromServer()
        return "OK" in data
    except Exception as e:
        print(f"[IPC] Failed to communicate with daemon: {e}")
        return False


class IPCServer(QObject):
    command_received = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._handle_connection)
        self.sock_path = get_socket_path()

    def start(self) -> bool:
        # Check if already running
        if send_ipc_command("PING", timeout=0.3):
            print("[IPCServer] Another daemon instance is already active.")
            return False

        if os.name != 'nt' and os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError:
                pass

        QLocalServer.removeServer(self.sock_path)
        if not self.server.listen(self.sock_path):
            print(f"[IPCServer] Failed to listen on socket: {self.server.errorString()}")
            return False

        print(f"[IPCServer] Listening on {self.sock_path}")
        return True

    def stop(self) -> None:
        self.server.close()
        if os.name != 'nt' and os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError:
                pass

    def _handle_connection(self) -> None:
        client_socket: QLocalSocket = self.server.nextPendingConnection()
        if not client_socket:
            return

        def on_ready_read():
            data = client_socket.readAll().data().decode("utf-8").strip()
            if data:
                if data == "PING":
                    client_socket.write(b"OK PONG\n")
                else:
                    self.command_received.emit(data)
                    client_socket.write(b"OK\n")
                client_socket.flush()
                client_socket.disconnectFromServer()

        client_socket.readyRead.connect(on_ready_read)

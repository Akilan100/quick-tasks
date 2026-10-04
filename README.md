# QuickTasks

A lightning-fast, ultra-minimal Dark OLED floating To-Do HUD that strictly integrates exclusively with Google Tasks & Calendar.

It’s designed to be hooked to a global keyboard shortcut (like \`Super+Shift+T\`). It immediately summons a minimalist overlay above any application on any OS, allowing you to quickly add or manage tasks, which asynchronously sync behind the scenes with Google.

## Features

- **Cross-Platform:** Works on Windows 10/11 and Linux (X11 / Wayland).
- **Daemon-Based Architecture:** Uses an ultra-fast IPC socket overlay so the UI triggers in less than 20ms without reloading Python.
- **Smart Natural Language Due Dates:** Parses commands logically. (e.g., `Update drivers /due:tomorrow` or `/due:15-10-2026`).
- **Offline Resilient:** Add tasks without an internet connection using local SQLite, and the daemon will push them natively when connected.

## Installation 

### Windows (10/11)

1. Clone or download this repository.
2. Ensure you have **Python 3.10+** installed, and check **"Add Python to PATH"** in the python installer!
3. Double-click the **`Windows-Setup.bat`** file. 
4. The setup will automatically:
   - Install all required `pip` dependencies.
   - Create a background Daemon in your Windows Startup so it starts silently at login.
   - Place a `QuickTasks` shortcut on your Desktop to toggle the HUD.

*(Optionally, assign a Global Keyboard shortcut to the Desktop Shortcut by Right Clicking it -> Properties -> Shortcut Key).*

### Linux (Kali, Ubuntu, Arch, etc.)

1. Clone the repository.
2. Run the provided script:
   ```bash
   ./Linux-Setup.sh
   ```
3. The setup automatically configures the daemon via a `systemd` user service and places `quick-tasks` in your `~/.local/bin`.
4. Bind the command `quick-tasks toggle` to a system-wide hotkey in your Desktop Environment settings (e.g. `Super+Shift+T`).

## Authentication

The very first time you start the app, or if you need to authorize it with your Google Account, run the CLI:
`python main.py auth` on Windows or `quick-tasks auth` on Linux. 

This will open your browser and generate the required OAuth token safely stored in your local configuration dir!


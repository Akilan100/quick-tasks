import os
import sys
import subprocess
import shutil
from pathlib import Path

def print_step(msg):
    print(f"\n---> {msg}")

def run_cmd(cmd_list):
    print(f"Running: {' '.join(cmd_list)}")
    subprocess.check_call(cmd_list)

def setup_windows():
    print_step("Installing dependencies...")
    run_cmd([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    print_step("Setting up Shortcuts (Desktop & Startup)...")
    import winreg
    def get_reg(name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                val, _ = winreg.QueryValueEx(key, name)
                return os.path.expandvars(val)
        except:
            return None

    desktop = get_reg("Desktop") or os.path.expanduser("~/Desktop")
    startup = get_reg("Startup") or os.path.join(os.path.expanduser("~"), r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup")
    
    pythonw = sys.executable.replace('python.exe', 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    
    main_script = os.path.abspath("main.py")
    
    vbs_path = os.path.join(os.environ.get("TEMP", "C:/Windows/Temp"), "create_shortcut.vbs")
    
    def create_shortcut(target_path, link_path, arguments="", window_style=1):
        vbs_content = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{link_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_path}"
oLink.Arguments = "{arguments}"
oLink.WindowStyle = {window_style}
oLink.WorkingDirectory = "{os.path.dirname(main_script)}"
oLink.Save
'''
        with open(vbs_path, "w") as f:
            f.write(vbs_content)
        subprocess.run(["cscript", "//nologo", vbs_path])
        os.remove(vbs_path)

    # 1. Desktop Toggle Shortcut (Shows/Hides HUD)
    create_shortcut(sys.executable, os.path.join(desktop, "QuickTasks.lnk"), f'"{main_script}" toggle', 7) # 7=minimized
    
    # 2. Startup Daemon (Runs in background at login)
    create_shortcut(pythonw, os.path.join(startup, "QuickTasks Daemon.lnk"), f'"{main_script}" daemon', 7)
    
    print_step("Starting QuickTasks Daemon from Startup...")
    os.startfile(os.path.join(startup, "QuickTasks Daemon.lnk"))

def setup_linux():
    print_step("Installing dependencies...")
    run_cmd([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--break-system-packages"])
    print_step("Installing Systemd Service...")
    service_path = Path.home() / ".config/systemd/user/quick-tasks.service"
    service_path.parent.mkdir(parents=True, exist_ok=True)
    main_script = os.path.abspath("main.py")
    service_content = f"""[Unit]
Description=QuickTasks Daemon
After=graphical-session.target

[Service]
ExecStart={sys.executable} {main_script} daemon
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
    service_path.write_text(service_content)
    run_cmd(["systemctl", "--user", "daemon-reload"])
    run_cmd(["systemctl", "--user", "enable", "--now", "quick-tasks.service"])
    
    print_step("Installing CLI shortcut (QuickTasks)...")
    bin_path = Path.home() / ".local/bin/quick-tasks"
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    cli_content = f"#!/usr/bin/env bash\n{sys.executable} {main_script} \"$@\"\n"
    bin_path.write_text(cli_content)
    bin_path.chmod(0o755)
    
    print_step("Added CLI 'quick-tasks'. Remember to add ~/.local/bin to your PATH.")

def main():
    print("Welcome to QuickTasks cross-platform installer!")
    
    config_dir = Path.home() / ".config/quick-tasks"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    if os.name == 'nt':
        setup_windows()
        print("\nSetup Complete! You can press Win+R and type shell:startup to see the autorun.")
        print("Double-click the 'QuickTasks' shortcut on your Desktop to open the HUD.")
    else:
        setup_linux()
        print("\nSetup Complete! Run 'quick-tasks toggle' or bind it to a Global Window Manager Hotkey.")
        
    print("\nIMPORTANT API SETUP:")
    print(f"To use Google Tasks, place your Google Cloud OAuth token at: {config_dir / 'client_secret.json'}")
    print("Then run 'quick-tasks auth' in your terminal (or 'python main.py auth' on Windows) to log in!\n")

if __name__ == "__main__":
    main()

"""Back up the dashboard's data to Google Drive, or restore it from there.

    python db_sync.py backup     copy this computer's data to Google Drive
    python db_sync.py restore    replace this computer's data with the copy on Google Drive
    python db_sync.py status     compare this computer's data with the copy on Google Drive

The copy goes to "My Drive/rakes_received_backup" in Google Drive for Desktop, which syncs it to the
other computer. Set RAKES_BACKUP_DIR to use another folder. Import on one computer at a time: back up
after importing, and restore on the other computer before importing there.
"""
import os
import shutil
import socket
import sqlite3
import string
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", BASE_DIR))
DB_NAME = "rake_data.db"
OTHER_FILES = ["station_mappings.txt", "commodity_mappings.txt"]
FOLDER_NAME = "rakes_received_backup"
HISTORY_KEPT = 10  # dated copies of the database kept on Drive
PORT = int(os.environ.get("PORT", 5000))


def backup_dir():
    """The backup folder on Google Drive: RAKES_BACKUP_DIR, or "My Drive" on whichever drive letter has it."""
    chosen = os.environ.get("RAKES_BACKUP_DIR")
    if chosen:
        return chosen
    for letter in string.ascii_uppercase:
        my_drive = f"{letter}:\\My Drive"
        if os.path.isdir(my_drive):
            return os.path.join(my_drive, FOLDER_NAME)
    sys.exit('Google Drive was not found (no "My Drive" folder on any drive). Start Google Drive for '
             "Desktop, or set RAKES_BACKUP_DIR to the folder to use.")


def describe(path):
    """Size, time and row counts of a database file, or why it can't be read."""
    if not os.path.exists(path):
        return "not there"
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "DAMAGED (integrity check failed)"
            rakes = db.execute("SELECT COUNT(*) FROM rakes").fetchone()[0]
            lists, latest = db.execute("SELECT COUNT(DISTINCT imported_at), MAX(imported_at) FROM inbound_rakes").fetchone()
        finally:
            db.close()
    except sqlite3.Error as error:
        return f"unreadable ({error})"
    modified = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d-%m-%Y %H:%M")
    return (f"{os.path.getsize(path) / 1e6:.1f} MB, saved {modified}, {rakes} rakes received, "
            f"{lists} en-route lists, latest list {(latest or 'none')[:16]}")


def is_usable(path):
    return os.path.exists(path) and not describe(path).startswith(("DAMAGED", "unreadable"))


def copy_database(source, target):
    """Copy a database with SQLite's own backup, which is safe while the app has it open."""
    partial = target + ".partial"
    if os.path.exists(partial):
        os.remove(partial)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(partial, target)


def server_running():
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def backup():
    local = os.path.join(DATA_DIR, DB_NAME)
    if not is_usable(local):
        sys.exit(f"Nothing backed up: {local} is {describe(local)}.")
    folder = backup_dir()
    history = os.path.join(folder, "history")
    os.makedirs(history, exist_ok=True)

    target = os.path.join(folder, DB_NAME)
    copy_database(local, target)
    shutil.copy2(target, os.path.join(history, f"rake_data_{datetime.now():%Y-%m-%d_%H%M%S}.db"))
    for old in sorted(os.listdir(history))[:-HISTORY_KEPT]:
        os.remove(os.path.join(history, old))
    for name in OTHER_FILES:
        if os.path.exists(os.path.join(DATA_DIR, name)):
            shutil.copy2(os.path.join(DATA_DIR, name), os.path.join(folder, name))

    print(f"Backed up to {folder}")
    print(f"  {describe(target)}")
    print("Wait for Google Drive to finish syncing before restoring on the other computer.")


def restore():
    folder = backup_dir()
    source = os.path.join(folder, DB_NAME)
    if not is_usable(source):
        sys.exit(f"Nothing restored: the backup at {source} is {describe(source)}.")
    if server_running() and "--force" not in sys.argv:
        sys.exit(f"Nothing restored: the dashboard is running on port {PORT}. Stop it first, then restore.")

    local = os.path.join(DATA_DIR, DB_NAME)
    if os.path.exists(local):
        kept = os.path.join(DATA_DIR, "rake_data_before_restore.db")
        shutil.copy2(local, kept)
        print(f"This computer's old data was kept as {kept}")
    copy_database(source, local)
    for name in OTHER_FILES:
        if os.path.exists(os.path.join(folder, name)):
            shutil.copy2(os.path.join(folder, name), os.path.join(DATA_DIR, name))

    print(f"Restored from {folder}")
    print(f"  {describe(local)}")


def status():
    folder = backup_dir()
    print(f"This computer: {describe(os.path.join(DATA_DIR, DB_NAME))}")
    print(f"Google Drive:  {describe(os.path.join(folder, DB_NAME))}")
    print(f"  ({folder})")


if __name__ == "__main__":
    commands = {"backup": backup, "restore": restore, "status": status}
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in commands:
        sys.exit(__doc__)
    commands[command]()

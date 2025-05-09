import time
import sqlite3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os

def write_one_file(cursor, path: str):
    cursor.execute(f"INSERT INTO image_files (filepath)\nVALUES (\"{path}\");")
    print(path)

class NewFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            conn = sqlite3.connect('../frames.db')
            cursor = conn.cursor()
            write_one_file(cursor, event.src_path)
            conn.commit()
            cursor.close()
            conn.close()



def create_table(cursor):
    cursor.execute(
"""CREATE TABLE IF NOT EXISTS image_files (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filepath VARCHAR(255) NOT NULL UNIQUE
);
""")

def write_files_from_dir(cursor, dir: str):
    files = set(os.listdir(dir))
    for file in files:
        write_one_file(cursor, dir+file)

def monitor_dir(dir: str):
    event_handler = NewFileHandler()
    observer = Observer()
    observer.schedule(event_handler, dir, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# TODO: async or threads
def database_appending():
    dir = "../ipcamera/tmp/"
    conn = sqlite3.connect('../frames.db')
    cursor = conn.cursor()
    create_table(cursor)
    write_files_from_dir(cursor, dir)
    conn.commit()
    cursor.close()
    conn.close()
    monitor_dir(dir) 


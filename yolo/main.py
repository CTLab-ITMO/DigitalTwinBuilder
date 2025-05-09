import sqlite3
import sqlite3
import time

def create_meta_table():
    conn = sqlite3.connect('../frames.db')
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK (id = 1), last_updated INTEGER);")
    cursor.execute("INSERT OR IGNORE INTO meta (id, last_updated) VALUES (1, 0);")
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS after_insert_trigger
        AFTER INSERT ON image_files
        BEGIN
            UPDATE meta SET last_updated = CAST((julianday('now') - 2440587.5)*86400000 AS INTEGER);
        END;
    """)
    conn.commit()
    cursor.close()
    conn.close()

def check_updates():
    conn = sqlite3.connect('../frames.db')
    cursor = conn.cursor()
    cursor.execute("SELECT last_updated FROM meta")
    current = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return current



def main(): 
    create_meta_table()
    last_updated = check_updates()
    while True:
        current = check_updates()
        if current > last_updated:
            print("doing something here")
            last_updated = current
        time.sleep(1)

if __name__=="__main__":
    main()

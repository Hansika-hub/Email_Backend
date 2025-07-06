import sqlite3
from datetime import datetime, timedelta

DB_NAME = 'events.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT,
            date TEXT,
            time TEXT,
            venue TEXT,
            reminder_set_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


def save_to_db(event):
    init_db()  # ensure table exists

    reminder_set_at = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        INSERT INTO events (event_name, date, time, venue, reminder_set_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        event['event_name'],
        event['date'],
        event['time'],
        event['venue'],
        reminder_set_at
    ))
    conn.commit()
    conn.close()


def delete_expired_events():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Assuming you want to delete reminders older than 1 day after the event date + time
    now = datetime.utcnow()

    # Convert date + time strings to datetime for comparison
    c.execute('SELECT id, date, time FROM events')
    all_events = c.fetchall()

    deleted_ids = []
    for row in all_events:
        event_id, date_str, time_str = row
        try:
            event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if event_dt + timedelta(hours=1) < now:
                c.execute('DELETE FROM events WHERE id = ?', (event_id,))
                deleted_ids.append(event_id)
        except Exception as e:
            print(f"⛔ Error parsing datetime: {e}")

    conn.commit()
    conn.close()
    return deleted_ids

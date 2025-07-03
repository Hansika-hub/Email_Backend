import sqlite3

def save_to_db(event):
    conn = sqlite3.connect('events.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_name TEXT, date TEXT, time TEXT, venue TEXT
    )''')
    c.execute('INSERT INTO events (event_name, date, time, venue) VALUES (?, ?, ?, ?)',
              (event['event_name'], event['date'], event['time'], event['venue']))
    conn.commit()
    conn.close()

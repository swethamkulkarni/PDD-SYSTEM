import sqlite3
conn = sqlite3.connect('dd_platform.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT action, detail, created_at FROM audit_log WHERE detail LIKE '%6e0ee408%' ORDER BY id DESC").fetchall()
for r in rows:
    print(dict(r))
conn.close()
import sqlite3

conn = sqlite3.connect('dd_platform.db')
conn.row_factory = sqlite3.Row

a = conn.execute('SELECT id, user_email FROM analyses ORDER BY created_at DESC LIMIT 1').fetchone()
print('Analysis:', dict(a))

u = conn.execute('SELECT role FROM users WHERE email=?', (a['user_email'],)).fetchone()
print('User role:', dict(u) if u else 'not found')

f = conn.execute(
    "SELECT check_id, status, suggestion FROM findings WHERE analysis_id=? AND status IN ('FLAGGED','UNCLEAR') LIMIT 5",
    (a['id'],)
).fetchall()

print('Sample findings:')
for row in f:
    print(dict(row))

conn.close()
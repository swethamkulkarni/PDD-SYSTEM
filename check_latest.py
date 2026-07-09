import sqlite3
conn = sqlite3.connect('dd_platform.db')
conn.row_factory = sqlite3.Row
a = conn.execute('SELECT id, status, slide_count, deal_score, created_at FROM analyses ORDER BY created_at DESC LIMIT 1').fetchone()
print('Latest analysis:', dict(a))
conn.close()
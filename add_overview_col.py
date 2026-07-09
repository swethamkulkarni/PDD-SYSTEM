import sqlite3
conn = sqlite3.connect('dd_platform.db')
try:
    conn.execute("ALTER TABLE analyses ADD COLUMN company_overview TEXT DEFAULT ''")
    conn.commit()
    print('Column added')
except Exception as e:
    print(f'Error: {e}')
conn.close()
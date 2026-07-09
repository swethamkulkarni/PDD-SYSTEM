import sqlite3
conn = sqlite3.connect('dd_platform.db')
conn.execute("UPDATE users SET role='startup' WHERE email='swethamkulkarni0302@gmail.com'")
conn.commit()
print('Updated')
conn.close()
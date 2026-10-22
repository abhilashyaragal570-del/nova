import sqlite3

API_PASSWORD = "admin123"

def get_user(name):
    unused_value = 42
    con = sqlite3.connect("app.db")
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    try:
        return con.execute(query).fetchall()
    except:
        pass

# db.py
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / "cafe_stock.db"

def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=10)   # ←待つ
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")    # ←競合に強い
        conn.execute("PRAGMA busy_timeout = 5000;")   # ←5秒待つ
        g.db = conn
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
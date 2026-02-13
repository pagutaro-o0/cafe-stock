# db.py
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / "cafe_stock.db"

def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        g.db = conn
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()

    # --- users ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('owner','staff')),
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """)

    # --- storage locations ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS storage_locations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE
    )
    """)

    # --- items ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      category TEXT NOT NULL CHECK(category IN ('ingredient','consumable')),
      unit TEXT NOT NULL,
      reorder_point REAL NOT NULL DEFAULT 0,
      track_lots INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      default_location_id INTEGER,
      created_by INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(default_location_id) REFERENCES storage_locations(id),
      FOREIGN KEY(created_by) REFERENCES users(id)
    )
    """)

    # --- item stock ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS item_stock (
      item_id INTEGER PRIMARY KEY,
      current_qty REAL NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
    )
    """)

    # --- stock moves ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS stock_moves (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      move_type TEXT NOT NULL CHECK(move_type IN ('IN','OUT')),
      item_id INTEGER NOT NULL,
      qty REAL NOT NULL,
      performed_by INTEGER,
      note TEXT,
      occurred_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(item_id) REFERENCES items(id),
      FOREIGN KEY(performed_by) REFERENCES users(id)
    )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_moves_item_time ON stock_moves(item_id, occurred_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_moves_time ON stock_moves(occurred_at)")

    # --- notifications ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_id INTEGER NOT NULL,
      type TEXT NOT NULL,
      message TEXT NOT NULL,
      is_read INTEGER NOT NULL DEFAULT 0,
      created_by INTEGER,
      created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      read_at TEXT,
      FOREIGN KEY(item_id) REFERENCES items(id),
      FOREIGN KEY(created_by) REFERENCES users(id)
    )
    """)
    db.execute("""
    CREATE INDEX IF NOT EXISTS idx_notifications_item_unread
    ON notifications(item_id, type, is_read)
    """)

    db.commit()
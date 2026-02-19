# db.py
import os
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / "cafe_stock.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


def get_db():
    if "db" in g:
        return g.db

    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        g.db = conn
        g.db_kind = "postgres"
        return g.db

    # SQLite
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    g.db = conn
    g.db_kind = "sqlite"
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    g.pop("db_kind", None)
    if db is not None:
        db.close()


def _execute(db, sql: str, params=()):
    """
    アプリ側のSQLは SQLite 互換の「?」で統一して書く。
    Postgres のときだけ「?」→「%s」に変換して実行する。
    """
    kind = getattr(g, "db_kind", "sqlite")
    if kind == "postgres":
        sql = sql.replace("?", "%s")
    return db.execute(sql, params)


def init_db():
    db = get_db()
    kind = getattr(g, "db_kind", "sqlite")

    if kind == "postgres":
        # Postgres 用 DDL
        _execute(db, """
        CREATE TABLE IF NOT EXISTS users (
          id BIGSERIAL PRIMARY KEY,
          username TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('owner','staff')),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

        _execute(db, """
        CREATE TABLE IF NOT EXISTS storage_locations (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL UNIQUE
        )
        """)

        _execute(db, """
        CREATE TABLE IF NOT EXISTS items (
          id BIGSERIAL PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          category TEXT NOT NULL CHECK(category IN ('ingredient','consumable')),
          unit TEXT NOT NULL,
          reorder_point DOUBLE PRECISION NOT NULL DEFAULT 0,
          track_lots BOOLEAN NOT NULL DEFAULT FALSE,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          default_location_id BIGINT REFERENCES storage_locations(id),
          created_by BIGINT REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)

        _execute(db, """
        CREATE TABLE IF NOT EXISTS item_stock (
          item_id BIGINT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
          current_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)

        _execute(db, """
        CREATE TABLE IF NOT EXISTS stock_moves (
          id BIGSERIAL PRIMARY KEY,
          move_type TEXT NOT NULL CHECK(move_type IN ('IN','OUT')),
          item_id BIGINT NOT NULL REFERENCES items(id),
          qty DOUBLE PRECISION NOT NULL,
          performed_by BIGINT REFERENCES users(id),
          note TEXT,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_moves_item_time ON stock_moves(item_id, occurred_at)")
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_moves_time ON stock_moves(occurred_at)")

        _execute(db, """
        CREATE TABLE IF NOT EXISTS notifications (
          id BIGSERIAL PRIMARY KEY,
          item_id BIGINT NOT NULL REFERENCES items(id),
          type TEXT NOT NULL,
          message TEXT NOT NULL,
          is_read BOOLEAN NOT NULL DEFAULT FALSE,
          created_by BIGINT REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          read_at TIMESTAMPTZ
        )
        """)
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_notifications_item_unread ON notifications(item_id, type, is_read)")

        db.commit()
        return

    # SQLite 用（いまのあなたのDDLでOK）
    db.execute("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('owner','staff')),
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
    """)

    db.execute("""
    CREATE TABLE IF NOT EXISTS storage_locations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE
    )
    """)

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

    db.execute("""
    CREATE TABLE IF NOT EXISTS item_stock (
      item_id INTEGER PRIMARY KEY,
      current_qty REAL NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
      FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
    )
    """)

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
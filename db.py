# db.py
import os
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / "cafe_stock.db"


def _is_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def get_db():
    """
    - Render: DATABASE_URL がある => Postgres(psycopg)
    - Local: ない => sqlite3
    """
    if "db" in g:
        return g.db

    if _is_postgres():
        import psycopg  # requirements.txt: psycopg[binary]
        conn = psycopg.connect(os.environ["DATABASE_URL"])
        conn.autocommit = False
        g.db = conn
        return conn

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    g.db = conn
    return conn


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _exec(db, sql: str, params=()):
    """
    sqlite3 と psycopg の差を吸収
    """
    cur = db.cursor()
    cur.execute(sql, params)
    return cur


def init_db():
    db = get_db()

    if _is_postgres():
        # Postgres: auto id は SERIAL相当、timestamp は NOW()
        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS users (
              id SERIAL PRIMARY KEY,
              username TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('owner','staff')),
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )

        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS storage_locations (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL UNIQUE
            )
            """,
        )

        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS items (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              category TEXT NOT NULL CHECK(category IN ('ingredient','consumable')),
              unit TEXT NOT NULL,
              reorder_point DOUBLE PRECISION NOT NULL DEFAULT 0,
              track_lots INTEGER NOT NULL DEFAULT 0,
              is_active INTEGER NOT NULL DEFAULT 1,
              default_location_id INTEGER REFERENCES storage_locations(id),
              created_by INTEGER REFERENCES users(id),
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )

        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS item_stock (
              item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
              current_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )

        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS stock_moves (
              id SERIAL PRIMARY KEY,
              move_type TEXT NOT NULL CHECK(move_type IN ('IN','OUT')),
              item_id INTEGER NOT NULL REFERENCES items(id),
              qty DOUBLE PRECISION NOT NULL,
              performed_by INTEGER REFERENCES users(id),
              note TEXT,
              occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        )

        _exec(db, "CREATE INDEX IF NOT EXISTS idx_moves_item_time ON stock_moves(item_id, occurred_at)")
        _exec(db, "CREATE INDEX IF NOT EXISTS idx_moves_time ON stock_moves(occurred_at)")

        _exec(
            db,
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id SERIAL PRIMARY KEY,
              item_id INTEGER NOT NULL REFERENCES items(id),
              type TEXT NOT NULL,
              message TEXT NOT NULL,
              is_read INTEGER NOT NULL DEFAULT 0,
              created_by INTEGER REFERENCES users(id),
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              read_at TIMESTAMPTZ
            )
            """,
        )
        _exec(db, "CREATE INDEX IF NOT EXISTS idx_notifications_item_unread ON notifications(item_id, type, is_read)")

        db.commit()
        return

    # --- SQLite (今まで通り) ---
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('owner','staff')),
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_locations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE
        )
        """
    )

    db.execute(
        """
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
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS item_stock (
          item_id INTEGER PRIMARY KEY,
          current_qty REAL NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """
    )

    db.execute(
        """
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
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_moves_item_time ON stock_moves(item_id, occurred_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_moves_time ON stock_moves(occurred_at)")

    db.execute(
        """
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
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notifications_item_unread
        ON notifications(item_id, type, is_read)
        """
    )

    db.commit()
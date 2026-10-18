"""SQLite data layer for the CCaaS prototype.

Stands in for Supabase/PostgreSQL: same three tables (cold_rooms, inventory,
telemetry) plus a tiny `control` key/value table and a `dispatches` table.
Every process (simulator, engine, dashboard) talks to the same ccaas.db file.
"""
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "CCAAS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ccaas.db")
)

# Illustrative rural Rift Valley (Kenya) locations. Edit freely.
DEPOT = {"name": "Nakuru Logistics Hub", "lat": -0.3031, "lng": 36.0800}
FAILURE_ROOM_ID = 3  # Room C is the one the demo button breaks

SEED_ROOMS = [
    (1, "Room A - Njoro", -0.3300, 35.9400),
    (2, "Room B - Molo", -0.2500, 35.7400),
    (3, "Room C - Subukia", -0.0200, 36.2000),
]
# (room_id, crop, farmer, kg, base_shelf_life_hours)
SEED_INVENTORY = [
    (1, "Mangoes", "Farmer Wanjiru", 1800, 336.0),
    (2, "Leafy greens", "Farmer Otieno", 900, 240.0),
    (3, "Tomatoes", "Farmer Achieng", 1500, 168.0),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS cold_rooms (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  lat REAL NOT NULL,
  lng REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'good',
  last_temp REAL
);
CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY,
  room_id INTEGER NOT NULL REFERENCES cold_rooms(id),
  crop_type TEXT NOT NULL,
  farmer TEXT,
  quantity_kg REAL,
  base_shelf_life_hours REAL NOT NULL,
  current_shelf_life REAL NOT NULL,
  drain_per_sec REAL NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL,
  rescued INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER NOT NULL,
  temperature REAL NOT NULL,
  timestamp REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS control (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dispatches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  eta_seconds REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'en_route',
  arrived_at REAL,
  shelf_life_at_dispatch REAL,
  shelf_life_on_arrival REAL
);
"""

DEFAULT_CONTROL = {
    "failure_room": "0",          # id of the room with a simulated power failure (0 = none)
    "sim_hours_per_tick": "1.0",  # simulated shelf-life hours per telemetry tick
    "tick_seconds": "5",          # real seconds between telemetry ticks (set by simulator)
    "truck_eta_seconds": "45",    # how long the truck takes to reach the failing room
    "engine_last_id": "0",        # last telemetry id the PRSL engine processed
    "reset_token": "0",           # bumped on reset so the simulator re-centres temperatures
}


@contextmanager
def connect():
    """Open a short-lived connection; commit on success, always close."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _use(conn):
    """Reuse the given connection, or open a new one."""
    if conn is not None:
        yield conn
    else:
        with connect() as c:
            yield c


def init_db():
    """Create tables and seed data if the database is empty."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM cold_rooms").fetchone()[0] == 0:
            now = time.time()
            conn.executemany(
                "INSERT INTO cold_rooms (id, name, lat, lng, last_temp) VALUES (?,?,?,?,4.0)",
                SEED_ROOMS,
            )
            conn.executemany(
                "INSERT INTO inventory (room_id, crop_type, farmer, quantity_kg, "
                "base_shelf_life_hours, current_shelf_life, updated_at) VALUES (?,?,?,?,?,?,?)",
                [(r, c, f, kg, base, base, now) for r, c, f, kg, base in SEED_INVENTORY],
            )
        for k, v in DEFAULT_CONTROL.items():
            conn.execute("INSERT OR IGNORE INTO control (key, value) VALUES (?, ?)", (k, v))


# ---- control key/value -------------------------------------------------------
def get_control(key, default=None, conn=None):
    with _use(conn) as c:
        row = c.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_control(key, value, conn=None):
    with _use(conn) as c:
        c.execute(
            "INSERT INTO control (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


# ---- reads -------------------------------------------------------------------
def get_rooms():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cold_rooms ORDER BY id")]


def get_inventory():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM inventory ORDER BY room_id, id")]


def get_latest_dispatch():
    with connect() as c:
        row = c.execute("SELECT * FROM dispatches ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def latest_telemetry_time():
    with connect() as c:
        row = c.execute("SELECT MAX(timestamp) AS t FROM telemetry").fetchone()
    return row["t"] if row and row["t"] else None


def recent_telemetry(per_room=40):
    with connect() as c:
        rows = c.execute(
            "SELECT t.id, r.name AS room, t.temperature, t.timestamp "
            "FROM telemetry t JOIN cold_rooms r ON r.id = t.room_id "
            "WHERE t.id > (SELECT COALESCE(MAX(id), 0) FROM telemetry) - ? ORDER BY t.id",
            (per_room * len(SEED_ROOMS),),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- writes ------------------------------------------------------------------
def insert_telemetry(readings):
    """readings: iterable of (room_id, temperature). One transaction per tick."""
    now = time.time()
    with connect() as c:
        c.executemany(
            "INSERT INTO telemetry (room_id, temperature, timestamp) VALUES (?,?,?)",
            [(rid, temp, now) for rid, temp in readings],
        )


def reset_demo():
    """Put everything back to the healthy starting state."""
    now = time.time()
    with connect() as c:
        c.execute("DELETE FROM telemetry")
        c.execute("DELETE FROM dispatches")
        c.execute("UPDATE cold_rooms SET status='good', last_temp=4.0")
        c.execute(
            "UPDATE inventory SET current_shelf_life=base_shelf_life_hours, "
            "drain_per_sec=0, updated_at=?, rescued=0",
            (now,),
        )
        set_control("failure_room", "0", conn=c)
        set_control("engine_last_id", "0", conn=c)
        set_control("reset_token", str(now), conn=c)

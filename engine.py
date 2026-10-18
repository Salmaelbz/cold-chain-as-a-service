"""PRSL engine: the brain.

Listens (polls) for new telemetry rows, applies the Q10 decay rule to each
room's inventory, updates room status, and dispatches a truck when a room
fails. Supabase would give you this via realtime subscriptions; with SQLite
a half-second poll is indistinguishable on stage.

    python engine.py
"""
import time

import db
import prsl

POLL_SECONDS = 0.5
TRUCK_TEMP_C = prsl.OPTIMAL_TEMP_C  # refrigerated truck keeps rescued crops at 4 degC


def interpolated_remaining(inv, now, tick_s):
    """Shelf life right now, between telemetry ticks (matches what the dashboard shows)."""
    elapsed = min(max(now - inv["updated_at"], 0.0), 1.5 * tick_s)
    return max(0.0, inv["current_shelf_life"] - elapsed * inv["drain_per_sec"])


def process_telemetry(conn):
    last_id = int(db.get_control("engine_last_id", "0", conn=conn))
    rows = conn.execute(
        "SELECT * FROM telemetry WHERE id > ? ORDER BY id", (last_id,)
    ).fetchall()
    if not rows:
        return
    sim_hours = float(db.get_control("sim_hours_per_tick", "1.0", conn=conn))
    tick_s = float(db.get_control("tick_seconds", "5", conn=conn))
    now = time.time()

    for row in rows:
        room_id, temp = row["room_id"], row["temperature"]
        status = prsl.classify(temp)
        conn.execute(
            "UPDATE cold_rooms SET status=?, last_temp=? WHERE id=?", (status, temp, room_id)
        )
        for inv in conn.execute("SELECT * FROM inventory WHERE room_id=?", (room_id,)).fetchall():
            effective_temp = TRUCK_TEMP_C if inv["rescued"] else temp
            new_life, mult = prsl.apply_decay(inv["current_shelf_life"], effective_temp, sim_hours)
            drain_per_sec = 0.0 if new_life <= 0 else (sim_hours * mult) / tick_s
            conn.execute(
                "UPDATE inventory SET current_shelf_life=?, drain_per_sec=?, updated_at=? WHERE id=?",
                (new_life, drain_per_sec, now, inv["id"]),
            )
            print(
                f"[engine] {inv['crop_type']:<13} room {room_id}  {temp:5.1f}C  x{mult:4.2f}  "
                f"-> {new_life:6.1f} h left" + ("  (in truck)" if inv["rescued"] else "")
            )
        maybe_dispatch(conn, room_id, status, now)
        last_id = row["id"]

    db.set_control("engine_last_id", last_id, conn=conn)


def maybe_dispatch(conn, room_id, status, now):
    """Reroute a truck when a room is failing and still has crops worth saving."""
    if status != "failing":
        return
    at_risk = conn.execute(
        "SELECT MIN(current_shelf_life) AS m FROM inventory "
        "WHERE room_id=? AND rescued=0 AND current_shelf_life>0",
        (room_id,),
    ).fetchone()["m"]
    if at_risk is None:
        return
    existing = conn.execute(
        "SELECT 1 FROM dispatches WHERE room_id=? AND status='en_route'", (room_id,)
    ).fetchone()
    if existing:
        return
    eta = float(db.get_control("truck_eta_seconds", "45", conn=conn))
    conn.execute(
        "INSERT INTO dispatches (room_id, created_at, eta_seconds, shelf_life_at_dispatch) "
        "VALUES (?,?,?,?)",
        (room_id, now, eta, at_risk),
    )
    print(f"[engine] *** REROUTE DISPATCH: truck sent to room {room_id}, ETA {eta:.0f}s, "
          f"{at_risk:.1f} h shelf life at dispatch ***")


def check_arrivals(conn):
    now = time.time()
    sim_hours = float(db.get_control("sim_hours_per_tick", "1.0", conn=conn))
    tick_s = float(db.get_control("tick_seconds", "5", conn=conn))
    for d in conn.execute("SELECT * FROM dispatches WHERE status='en_route'").fetchall():
        if now < d["created_at"] + d["eta_seconds"]:
            continue
        items = conn.execute(
            "SELECT * FROM inventory WHERE room_id=? AND rescued=0", (d["room_id"],)
        ).fetchall()
        remaining = min((interpolated_remaining(i, now, tick_s) for i in items), default=0.0)
        if remaining > 0:
            for i in items:
                life = interpolated_remaining(i, now, tick_s)
                conn.execute(
                    "UPDATE inventory SET rescued=?, current_shelf_life=?, drain_per_sec=?, "
                    "updated_at=? WHERE id=?",
                    (1 if life > 0 else 0, life, sim_hours / tick_s if life > 0 else 0.0, now, i["id"]),
                )
            status = "arrived"
        else:
            status = "too_late"
        conn.execute(
            "UPDATE dispatches SET status=?, arrived_at=?, shelf_life_on_arrival=? WHERE id=?",
            (status, now, remaining, d["id"]),
        )
        print(f"[engine] truck for room {d['room_id']} {status.upper()} with {remaining:.1f} h shelf life left")


def main():
    db.init_db()
    print("[engine] PRSL engine running (Ctrl+C to stop)")
    while True:
        with db.connect() as conn:
            process_telemetry(conn)
            check_arrivals(conn)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[engine] stopped")

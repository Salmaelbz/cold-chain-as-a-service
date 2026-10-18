"""IoT simulator: the fake edge.

Pushes mock temperature telemetry for the 3 cold rooms every few seconds.
Steady state is ~4 degC. When the dashboard (or `--fail`) flags a room as
failing, that room ramps up toward 30 degC like a real power failure.

    python simulator.py                # 5-second ticks
    python simulator.py --interval 1   # faster, for testing
"""
import argparse
import random
import time

import db

STEADY_C = 4.0
FAILURE_C = 30.0
RAMP_C_PER_TICK = 5.0  # how fast temperature moves toward its target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between ticks")
    ap.add_argument("--fail", type=int, default=0, help="room id to fail immediately (0 = none)")
    ap.add_argument("--ticks", type=int, default=0, help="stop after N ticks (0 = run forever)")
    args = ap.parse_args()

    db.init_db()
    db.set_control("tick_seconds", args.interval)
    if args.fail:
        db.set_control("failure_room", args.fail)

    rooms = db.get_rooms()
    temps = {r["id"]: STEADY_C for r in rooms}
    reset_token = db.get_control("reset_token")
    tick = 0
    print(f"[simulator] pushing telemetry for {len(rooms)} rooms every {args.interval}s (Ctrl+C to stop)")

    while True:
        # A demo reset re-centres every room so a failed room doesn't "cool down" through alerts.
        token = db.get_control("reset_token")
        if token != reset_token:
            reset_token = token
            temps = {r["id"]: STEADY_C for r in rooms}

        failing_id = int(float(db.get_control("failure_room", "0")))
        readings = []
        for r in rooms:
            target = FAILURE_C if r["id"] == failing_id else STEADY_C
            step = max(-RAMP_C_PER_TICK, min(RAMP_C_PER_TICK, target - temps[r["id"]]))
            temps[r["id"]] += step
            reading = round(temps[r["id"]] + random.uniform(-0.3, 0.3), 2)
            readings.append((r["id"], reading))
        db.insert_telemetry(readings)

        tick += 1
        flag = "  <-- POWER FAILURE" if failing_id else ""
        print(f"[simulator] tick {tick}: " + ", ".join(f"{rid}:{t:.1f}C" for rid, t in readings) + flag)
        if args.ticks and tick >= args.ticks:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[simulator] stopped")

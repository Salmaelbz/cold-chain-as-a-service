"""One command to run the whole demo: simulator + PRSL engine + dashboard.

    python run_demo.py            # fresh start (resets the database)
    python run_demo.py --keep     # keep existing data
"""
import subprocess
import sys
import time

import db


def main():
    db.init_db()
    if "--keep" not in sys.argv:
        db.reset_demo()
    procs = [
        subprocess.Popen([sys.executable, "simulator.py"]),
        subprocess.Popen([sys.executable, "engine.py"]),
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py"]),
    ]
    print("\nCCaaS demo running. Dashboard: http://localhost:8501  (Ctrl+C to stop)\n")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    main()

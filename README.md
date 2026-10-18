# CCaaS: Cold-Chain-as-a-Service (24-hour "Wizard of Oz" MVP)

Three moving parts, all Python, all talking through one SQLite file (`ccaas.db`):

| Part | File | Role |
|---|---|---|
| Fake edge | `simulator.py` | Pushes temperature telemetry for 3 cold rooms every 5 s (steady 4 °C; Room C ramps to 30 °C on power failure) |
| Brain | `engine.py` + `prsl.py` | Polls new telemetry, applies the Q10 decay rule to inventory shelf life, flags failing rooms, dispatches a truck |
| Demo UI | `app.py` | Streamlit dashboard: map, live shelf-life countdowns, flashing reroute alert, animated truck |

`db.py` is the data layer. The tables mirror the blueprint (`cold_rooms`, `inventory`, `telemetry`) plus `control` and `dispatches`. To move to Supabase later, replace the functions in `db.py`; nothing else touches SQL except `engine.py`.

## Run it

```bash
pip install -r requirements.txt
python run_demo.py          # starts simulator + engine + dashboard, resets data
```

Open http://localhost:8501. (The map tiles need an internet connection.)
Or run each piece in its own terminal: `python simulator.py`, `python engine.py`, `streamlit run app.py`.

Check the math any time with `python prsl.py`.

## Sidebar controls

- **Simulate power failure in Room C**: the demo trigger (becomes "Restore power" once pressed)
- **Reset demo**: back to healthy state, full shelf life, no dispatch
- **Sim speed**: shelf-life hours consumed per 5 s tick (default 1.0, so about 12 simulated minutes per real second)
- **Truck ETA**: seconds for the truck to reach the room (default 45). Raise it past ~120 s of spoilage time to show a "too late" case.

## The 3-minute demo script

| Time | Do | Say |
|---|---|---|
| 0:00 | Dashboard open, three green rooms, countdowns ticking slowly | "Meet Farmer Achieng. 1,500 kg of tomatoes, one rural cold room, no one watching it at night." |
| 0:30 | Point at the telemetry chart and the PRSL rule in the sidebar | "Every 5 seconds each room reports its temperature. We don't just alert, we compute remaining shelf life: decay doubles for every 10 °C of excursion." |
| 1:00 | Click **Simulate power failure in Room C** | "Power fails at 2 a.m." |
| 1:10 | Room C turns amber, then red and flashing; the tomato countdown races | "Within seconds the room is at 30 °C and the tomatoes are aging 6× faster. Mangoes and greens next door are fine." |
| 1:30 | **Reroute Dispatch** banner appears, truck starts moving along the route | "The platform already knows the clock. It diverts the nearest truck, and tells us the tomatoes will have days of shelf life left when it arrives. Without us, they'd be spoiled in under two minutes of demo time." |
| 2:15 | Truck arrives, banner turns green | "Rescued: 1,500 kg, a season's income, saved by temperature data driving logistics." |
| 2:40 | Close | "Temperature data isn't a monitoring feature, it's the routing signal. That's cold chain as a service." |

Reset with **Reset demo** between rehearsals.

## Notes

- Locations (Njoro, Molo, Subukia, Nakuru hub) are illustrative; edit `SEED_ROOMS` and `DEPOT` in `db.py`, then delete `ccaas.db`.
- Base shelf lives (mangoes 336 h, greens 240 h, tomatoes 168 h) are demo values in `SEED_INVENTORY`.
- Healthy rooms also age at 1× per simulated hour, per the blueprint's rule, which is why the green countdowns tick slowly rather than staying frozen.

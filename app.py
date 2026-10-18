"""Streamlit dashboard for the CCaaS demo.

    streamlit run app.py
"""
import time

import pandas as pd
import pydeck as pdk
import streamlit as st

import db
import prsl

st.set_page_config(page_title="CCaaS - Cold-Chain-as-a-Service", page_icon="❄️", layout="wide")
db.init_db()

GREEN, AMBER, RED, GREY = [34, 197, 94], [250, 204, 21], [239, 68, 68], [107, 114, 128]
STATUS_COLOR = {"good": GREEN, "warning": AMBER, "failing": RED}
STATUS_ICON = {"good": "🟢", "warning": "🟡", "failing": "🔴", "spoiled": "⚫"}

st.markdown(
    """
<style>
@keyframes flash { 0%,100% {background:#7f1d1d;} 50% {background:#dc2626;} }
.banner { padding:14px 18px; border-radius:10px; font-size:1.1rem; font-weight:600; color:#fff; margin-bottom:10px; }
.banner small { font-weight:400; font-size:0.95rem; opacity:0.95; }
.banner.flash { animation: flash 1s infinite; }
.banner.warn { background:#b45309; }
.banner.ok { background:#166534; }
.banner.dead { background:#374151; }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- helpers
def fmt_hours(h):
    h = max(0.0, h)
    return f"{int(h // 24)}d {int(h % 24):02d}h {int((h * 60) % 60):02d}m"


def fmt_clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def live_remaining(inv, now, tick_s):
    """Shelf life right now: last DB value minus drain since the last telemetry tick."""
    elapsed = min(max(now - inv["updated_at"], 0.0), 1.5 * tick_s)
    return max(0.0, inv["current_shelf_life"] - elapsed * inv["drain_per_sec"])


def set_slider(key, control_key):
    db.set_control(control_key, st.session_state[key])


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("🎬 Demo controls")
    failure_on = int(float(db.get_control("failure_room", "0"))) == db.FAILURE_ROOM_ID
    if failure_on:
        st.button("🔌 Restore power to Room C", width="stretch",
                  on_click=db.set_control, args=("failure_room", "0"))
    else:
        st.button("⚡ Simulate power failure in Room C", type="primary", width="stretch",
                  on_click=db.set_control, args=("failure_room", str(db.FAILURE_ROOM_ID)))
    st.button("↺ Reset demo", width="stretch", on_click=db.reset_demo)

    st.slider("Sim speed (shelf-life hours per tick)", 0.25, 4.0,
              float(db.get_control("sim_hours_per_tick", "1.0")), 0.25, key="sim_speed",
              on_change=set_slider, args=("sim_speed", "sim_hours_per_tick"),
              help="Accelerated clock so decay is visible in a 3-minute demo.")
    st.slider("Truck ETA (seconds)", 15, 120, int(float(db.get_control("truck_eta_seconds", "45"))), 5,
              key="truck_eta", on_change=set_slider, args=("truck_eta", "truck_eta_seconds"),
              help="Applies to the next dispatch. Lower = more spare shelf life.")
    st.divider()
    st.caption(
        "**PRSL rule (Q10):** decay rate doubles for every 10 °C above 4 °C.\n\n"
        "`multiplier = 2 ^ ((T − 4) / 10)`\n\n"
        "A tomato at 24 °C ages 4× faster; at 30 °C, about 6×."
    )


# ---------------------------------------------------------------- map
def build_map(rooms, inv_by_room, dispatch, now):
    depot_pos = [db.DEPOT["lng"], db.DEPOT["lat"]]
    blink = int(now) % 2 == 0

    room_rows = []
    for r in rooms:
        inv = inv_by_room.get(r["id"])
        spoiled = bool(inv) and not inv["rescued"] and inv["_live"] <= 0
        color = GREY if spoiled else STATUS_COLOR[r["status"]]
        alpha = 140 if (r["status"] == "failing" and not spoiled and blink) else 235
        temp = r["last_temp"] if r["last_temp"] is not None else prsl.OPTIMAL_TEMP_C
        short = r["name"].split(" - ")[0]
        room_rows.append({
            "pos": [r["lng"], r["lat"]], "color": color + [alpha],
            "radius": 5200 if (r["status"] == "failing" and blink) else 4200,
            "label": f"{short}  {temp:.1f}°C",
            "tooltip": f"{r['name']}: {temp:.1f}°C"
                       + (f" | {inv['crop_type']} {fmt_hours(inv['_live'])} left" if inv else ""),
        })
    layers = [
        pdk.Layer("ScatterplotLayer", pd.DataFrame(room_rows), get_position="pos",
                  get_fill_color="color", get_radius="radius", radius_min_pixels=14,
                  stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2, pickable=True),
        pdk.Layer("TextLayer", pd.DataFrame(room_rows), get_position="pos", get_text="label",
                  get_size=16, get_color=[255, 255, 255], get_pixel_offset=[0, -42]),
        pdk.Layer("ScatterplotLayer",
                  pd.DataFrame([{"pos": depot_pos, "tooltip": db.DEPOT["name"]}]),
                  get_position="pos", get_fill_color=[96, 165, 250], get_radius=2200,
                  radius_min_pixels=9, stroked=True, get_line_color=[255, 255, 255],
                  line_width_min_pixels=2, pickable=True),
        pdk.Layer("TextLayer", pd.DataFrame([{"pos": depot_pos, "label": "Depot"}]),
                  get_position="pos", get_text="label", get_size=13,
                  get_color=[191, 219, 254], get_pixel_offset=[0, 24]),
    ]

    if dispatch:
        room = next(r for r in rooms if r["id"] == dispatch["room_id"])
        dest = [room["lng"], room["lat"]]
        if dispatch["status"] == "en_route":
            frac = min(1.0, (now - dispatch["created_at"]) / max(dispatch["eta_seconds"], 1))
        else:
            frac = 1.0
        truck = [depot_pos[0] + (dest[0] - depot_pos[0]) * frac,
                 depot_pos[1] + (dest[1] - depot_pos[1]) * frac]
        lines = pd.DataFrame([
            {"src": depot_pos, "dst": truck, "color": [96, 165, 250, 255]},
            {"src": truck, "dst": dest, "color": [239, 68, 68, 150]},
        ])
        layers += [
            pdk.Layer("LineLayer", lines, get_source_position="src", get_target_position="dst",
                      get_color="color", get_width=5, width_min_pixels=3),
            pdk.Layer("ScatterplotLayer", pd.DataFrame([{"pos": truck, "tooltip": "Truck #1"}]),
                      get_position="pos", get_fill_color=[255, 255, 255], get_radius=2000,
                      radius_min_pixels=11, stroked=True, get_line_color=[37, 99, 235],
                      line_width_min_pixels=4, pickable=True),
            pdk.Layer("TextLayer", pd.DataFrame([{"pos": truck, "label": "TRUCK #1"}]),
                      get_position="pos", get_text="label", get_size=14,
                      get_color=[255, 255, 255], get_pixel_offset=[0, 28]),
        ]

    lats = [r["lat"] for r in rooms] + [db.DEPOT["lat"]]
    lngs = [r["lng"] for r in rooms] + [db.DEPOT["lng"]]
    view = pdk.ViewState(latitude=sum(lats) / len(lats), longitude=sum(lngs) / len(lngs),
                         zoom=9.4, pitch=0)
    return pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto",
                    map_style="dark", tooltip={"text": "{tooltip}"})


# ---------------------------------------------------------------- live view
@st.fragment(run_every=1)
def live():
    now = time.time()
    rooms = db.get_rooms()
    tick_s = float(db.get_control("tick_seconds", "5"))
    inv_by_room = {}
    for inv in db.get_inventory():
        inv["_live"] = live_remaining(inv, now, tick_s)
        inv_by_room[inv["room_id"]] = inv
    dispatch = db.get_latest_dispatch()
    last_t = db.latest_telemetry_time()

    st.title("❄️ Cold-Chain-as-a-Service")
    st.caption("Predictive Remaining Shelf-Life (PRSL) · live telemetry from 3 rural cold rooms")

    if last_t is None or now - last_t > 15:
        st.warning("No fresh telemetry. Start the simulator and engine: `python run_demo.py`")

    # ---- alert banner
    active = [r for r in rooms if r["status"] != "good"]
    if dispatch and dispatch["status"] == "en_route":
        room = next(r for r in rooms if r["id"] == dispatch["room_id"])
        inv = inv_by_room.get(room["id"])
        eta_left = dispatch["created_at"] + dispatch["eta_seconds"] - now
        detail = ""
        if inv:
            at_arrival = max(0.0, inv["_live"] - max(eta_left, 0) * inv["drain_per_sec"])
            to_spoil = inv["_live"] / inv["drain_per_sec"] if inv["drain_per_sec"] > 0 else None
            detail = (f"{inv['crop_type']} ({inv['farmer']}, {inv['quantity_kg']:,.0f} kg) will have "
                      f"<b>{fmt_hours(at_arrival)}</b> of shelf life left on arrival."
                      + (f" Without intervention: spoiled in <b>{fmt_clock(to_spoil)}</b>." if to_spoil else ""))
        st.markdown(
            f'<div class="banner flash">🚨 REROUTE DISPATCH: Truck #1 diverted to {room["name"]} · '
            f'ETA {fmt_clock(eta_left)}<br><small>{detail}</small></div>', unsafe_allow_html=True)
    elif dispatch and dispatch["status"] == "arrived":
        room = next(r for r in rooms if r["id"] == dispatch["room_id"])
        inv = inv_by_room.get(room["id"])
        kg = f"{inv['quantity_kg']:,.0f} kg of {inv['crop_type'].lower()}" if inv else "the harvest"
        st.markdown(
            f'<div class="banner ok">✅ Truck #1 reached {room["name"]}: {kg} rescued with '
            f'{fmt_hours(dispatch["shelf_life_on_arrival"])} of shelf life to spare.</div>',
            unsafe_allow_html=True)
    elif dispatch and dispatch["status"] == "too_late":
        st.markdown('<div class="banner dead">⚫ Truck arrived too late: the harvest had already '
                    'spoiled. Try a shorter truck ETA.</div>', unsafe_allow_html=True)
    elif active:
        names = ", ".join(r["name"].split(" - ")[0] for r in active)
        st.markdown(f'<div class="banner warn">⚠️ Temperature excursion detected: {names}. '
                    'PRSL engine recalculating…</div>', unsafe_allow_html=True)

    # ---- KPIs
    healthy = sum(1 for r in rooms if r["status"] == "good")
    at_risk_kg = sum(i["quantity_kg"] for i in inv_by_room.values()
                     if not i["rescued"] and i["_live"] > 0
                     and next(r for r in rooms if r["id"] == i["room_id"])["status"] != "good")
    rescued_kg = sum(i["quantity_kg"] for i in inv_by_room.values() if i["rescued"])
    k1, k2, k3 = st.columns(3)
    k1.metric("Healthy cold rooms", f"{healthy} / {len(rooms)}")
    k2.metric("Inventory at risk", f"{at_risk_kg:,.0f} kg")
    k3.metric("Harvest rescued", f"{rescued_kg:,.0f} kg")

    # ---- map + room cards
    left, right = st.columns([3, 2])
    with left:
        st.pydeck_chart(build_map(rooms, inv_by_room, dispatch, now), height=520)
    with right:
        for r in rooms:
            inv = inv_by_room.get(r["id"])
            temp = r["last_temp"] if r["last_temp"] is not None else prsl.OPTIMAL_TEMP_C
            spoiled = bool(inv) and not inv["rescued"] and inv["_live"] <= 0
            state = "spoiled" if spoiled else r["status"]
            with st.container(border=True):
                label = {"good": "Healthy", "warning": "Warming", "failing": "FAILING",
                         "spoiled": "SPOILED"}[state]
                st.markdown(f"**{STATUS_ICON[state]} {r['name']}** · {label}")
                c1, c2 = st.columns(2)
                c1.metric("Temperature", f"{temp:.1f} °C",
                          delta=f"{temp - prsl.OPTIMAL_TEMP_C:+.1f} vs 4 °C", delta_color="inverse")
                c2.metric("Decay rate", f"{prsl.calculate_decay_multiplier(temp):.1f}×")
                if inv:
                    frac = min(1.0, inv["_live"] / inv["base_shelf_life_hours"])
                    where = " · ✅ in refrigerated truck" if inv["rescued"] else ""
                    st.caption(f"{inv['crop_type']} · {inv['quantity_kg']:,.0f} kg · {inv['farmer']}{where}")
                    st.progress(frac, text=f"⏳ {fmt_hours(inv['_live'])} shelf life left")

    # ---- telemetry chart
    tel = db.recent_telemetry(per_room=40)
    if tel:
        df = pd.DataFrame(tel)
        df["n"] = df.groupby("room").cumcount()
        wide = df.pivot(index="n", columns="room", values="temperature")
        palette = {"Room A - Njoro": "#22c55e", "Room B - Molo": "#38bdf8", "Room C - Subukia": "#ef4444"}
        st.subheader("Live temperature telemetry (°C)")
        st.line_chart(wide, height=220, color=[palette.get(c, "#9ca3af") for c in wide.columns])


live()

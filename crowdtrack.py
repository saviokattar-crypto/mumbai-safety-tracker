import streamlit as st
import requests
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim
from streamlit_autorefresh import st_autorefresh

# ============================================================
# 1. CONFIG — no layout="wide" so it works on mobile too
# ============================================================
st.set_page_config(page_title="Mumbai Survival Tracker", page_icon="🚉")
st_autorefresh(interval=60000, key="datarefresh")

# ============================================================
# 2. URL-BASED PERSONALIZATION — 3 distinct modes
#    ?user=dhanashri  → Dhanashri (Savio + Mom + Dad contacts)
#    ?user=mom        → Mom       (Savio + Dad contacts)
#    (no param)       → Public    (custom contact entry)
# ============================================================
user_type    = st.query_params.get("user", "").lower()
is_dhanashri = user_type == "dhanashri"
is_mom       = user_type == "mom"
is_personal  = is_dhanashri or is_mom

if is_dhanashri:
    app_caption  = "For Dhanashri 💜"
    user_display = "Dhanashri"
elif is_mom:
    app_caption  = "For Mom 🧡"
    user_display = "Mom"
else:
    app_caption  = "For All Mumbaikars 🌆"
    user_display = "Traveller"

# ============================================================
# 3. EMERGENCY CONTACTS — single source of truth
#    Fill in the XXXXXXXXXX numbers below before deploying
# ============================================================
CONTACTS = {
    "savio":    {"name": "Savio",  "number": "917506397365"},
    "dad":      {"name": "Dad",    "number": "917738005302"},   # Savio's Dad / Mom's husband
    "dhan_mom": {"name": "Mom",    "number": "91XXXXXXXXXX"},   # ← Dhanashri's Mom's number
    "dhan_dad": {"name": "Dad",    "number": "91XXXXXXXXXX"},   # ← Dhanashri's Dad's number
}

def sos_contacts_for_user():
    """Returns list of contact dicts for the current user profile."""
    if is_dhanashri:
        return [CONTACTS["savio"], CONTACTS["dhan_mom"], CONTACTS["dhan_dad"]]
    elif is_mom:
        return [CONTACTS["savio"], CONTACTS["dad"]]
    else:
        return []  # Public: they enter their own contact below

# ============================================================
# 4. STATION DATABASE
# ============================================================
western_line = [
    "Churchgate","Marine Lines","Charni Road","Grant Road","Mumbai Central",
    "Mahalakshmi","Lower Parel","Prabhadevi","Dadar","Matunga Road","Mahim",
    "Bandra","Khar Road","Santa Cruz","Vile Parle","Andheri","Jogeshwari",
    "Ram Mandir","Goregaon","Malad","Kandivali","Borivali","Dahisar",
    "Mira Road","Bhayandar","Naigaon","Vasai Road","Nallasopara","Virar",
    "Vaitarna","Saphale","Kelve Road","Palghar","Umroli","Boisar","Vangaon","Dahanu Road"
]
central_line = [
    "CSMT","Masjid","Sandhurst Road","Byculla","Chinchpokli","Currey Road",
    "Parel","Dadar","Matunga","Sion","Kurla","Vidyavihar","Ghatkopar","Vikhroli",
    "Kanjurmarg","Bhandup","Nahur","Mulund","Thane","Kalwa","Mumbra","Diva",
    "Kopar","Dombivli","Thakurli","Kalyan","Vitthalwadi","Ulhasnagar","Ambernath",
    "Badlapur","Vangani","Shelu","Neral","Bhivpuri Road","Karjat","Palasdari",
    "Kelavli","Dolavli","Lowjee","Khopoli","Shahad","Ambivli","Titwala",
    "Khadavli","Vasind","Asangaon","Atgaon","Thansit","Khardi","Umbarmali","Kasara"
]
harbour_line = [
    "Dockyard Road","Reay Road","Cotton Green","Sewri","Vadala Road","GTB Nagar",
    "Chunabhatti","Kurla","Tilak Nagar","Chembur","Govandi","Mankhurd","Vashi",
    "Sanpada","Juinagar","Nerul","Seawoods","Belapur","Kharghar","Mansarovar",
    "Khandeshwar","Panvel","King's Circle","Mahim","Bandra","Khar Road",
    "Santa Cruz","Vile Parle","Andheri","Jogeshwari","Ram Mandir","Goregaon"
]

FLOOD_PRONE = {
    "Hindmata / Parel":       ["Parel", "Currey Road", "Chinchpokli"],
    "King's Circle / Sion":   ["King's Circle", "Sion", "Matunga"],
    "Kurla / Chunabhatti":    ["Kurla", "Chunabhatti", "Vidyavihar"],
    "Andheri / Milan Subway": ["Andheri", "Jogeshwari", "Vile Parle"],
    "Dadar":                  ["Dadar"],
    "Ghatkopar":              ["Ghatkopar"],
    "Mulund / Thane":         ["Mulund", "Thane"],
    "Bhandup":                ["Bhandup"],
}

mumbai_stations = sorted(list(set(western_line + central_line + harbour_line)))

# ============================================================
# 5. HELPER FUNCTIONS
# ============================================================
def get_line(station):
    lines = []
    if station in western_line: lines.append("🟡 Western")
    if station in central_line: lines.append("🔵 Central")
    if station in harbour_line: lines.append("🟢 Harbour")
    return " / ".join(lines) if lines else "❓ Unknown"

def get_common_line(a, b):
    if a in western_line and b in western_line: return "Western Line", "🟡"
    if a in central_line and b in central_line: return "Central Line", "🔵"
    if a in harbour_line and b in harbour_line: return "Harbour Line", "🟢"
    return "Cross-line (change required)", "🔀"

def get_index(lst, name):
    try: return lst.index(name)
    except ValueError: return 0

def _stop_dist(from_st, to_st):
    """
    Returns (stops, is_cross_line).
    For cross-line journeys (e.g. Bhandup Central → Bandra Western),
    we find the nearest interchange station and sum both legs.
    """
    all_lines = [western_line, central_line, harbour_line]
    # Same-line direct distance
    best = 999
    for line in all_lines:
        if from_st in line and to_st in line:
            d = abs(line.index(from_st) - line.index(to_st))
            best = min(best, d)
    if best < 999:
        return best, False

    # Cross-line: find interchange stations (on both from_line and to_line)
    # Common interchanges: Dadar (W+C), Kurla (C+H), Andheri (W+H), Bandra (W+H)
    interchanges = [
        "Dadar", "Kurla", "Andheri", "Bandra", "Mahim",
        "Goregaon", "Vile Parle", "Santa Cruz", "Khar Road"
    ]
    min_total = 999
    for ic in interchanges:
        for line_a in all_lines:
            for line_b in all_lines:
                if line_a is line_b: continue
                if from_st in line_a and ic in line_a and ic in line_b and to_st in line_b:
                    leg1 = abs(line_a.index(from_st) - line_a.index(ic))
                    leg2 = abs(line_b.index(ic)      - line_b.index(to_st))
                    total = leg1 + leg2
                    if total < min_total:
                        min_total = total
    return (min_total if min_total < 999 else 15), True  # fallback 15 stops

def get_fare(from_st, to_st):
    """
    Mumbai suburban fare slabs — accurate as per current Railway tariff.
    Fares unchanged since 2014 (Western/Central/Harbour lines).
    Returns: (second_class_fare, first_class_fare, distance_band_label)
    """
    if from_st == to_st:
        return "Same station", "", ""
    d, cross = _stop_dist(from_st, to_st)
    if d <= 2:   return "₹5",   "₹50",   "1–5 km"
    if d <= 4:   return "₹10",  "₹100",  "6–12 km"
    if d <= 7:   return "₹15",  "₹145",  "13–20 km"
    if d <= 11:  return "₹20",  "₹200",  "21–30 km"
    if d <= 16:  return "₹25",  "₹240",  "31–45 km"
    if d <= 22:  return "₹30",  "₹290",  "46–60 km"
    return               "₹35+","₹340+", "60+ km"

def get_travel_time(from_st, to_st):
    if from_st == to_st:
        return "Same station"
    d, cross = _stop_dist(from_st, to_st)
    mins = d * 3
    note = " (with change)" if cross else ""
    return f"~{mins} mins{note}"

def rain_to_risk(rain_mm):
    if rain_mm >= 15: return "🔴 EXTREME", 100
    if rain_mm >= 8:  return "🟠 HIGH",    70
    if rain_mm >= 3:  return "🟡 MODERATE", 40
    return "🟢 LOW", 10

def make_sos_msg(crowd_pct, map_link):
    return (
        f"I%20feel%20unsafe.%20Crowd%20is%20at%20{crowd_pct}%25.%20"
        f"My%20location%3A%20{map_link}"
    )

def render_sos_buttons(msg, context="main"):
    """
    Renders SOS WhatsApp buttons.
    - Dhanashri: Savio + Mom + Dad
    - Mom: Savio + Dad
    - Public: their saved custom contact
    context = "main" or "sidebar"
    """
    contacts = sos_contacts_for_user()

    if is_personal:
        for c in contacts:
            label  = f"🚨 Alert {c['name']}"
            wa_url = f"https://wa.me/{c['number']}?text={msg}"
            if context == "sidebar":
                st.sidebar.link_button(label, wa_url, use_container_width=True)
            else:
                st.link_button(label, wa_url, use_container_width=True)
    else:
        # Public user
        cname = st.session_state.get("custom_name", "").strip()
        cno   = st.session_state.get("custom_no", "").strip()
        if cno and len(cno) > 10:
            label  = f"🚨 Alert {cname if cname else 'My Contact'}"
            wa_url = f"https://wa.me/{cno}?text={msg}"
            if context == "sidebar":
                st.sidebar.link_button(label, wa_url, use_container_width=True)
            else:
                st.link_button(label, wa_url, use_container_width=True)
        else:
            if context == "main":
                st.warning("💡 Set your emergency contact below to enable SOS.")

# ============================================================
# 6. CACHED API CALLS — all safe, never crash
# ============================================================
@st.cache_data(ttl=300)
def get_cached_address(lat, lon):
    try:
        geo = Nominatim(user_agent="mumbai_survival_savio")
        loc = geo.reverse(f"{lat}, {lon}", language='en', timeout=5)
        parts = loc.address.split(',')
        short = parts[1].strip() if len(parts) > 1 else parts[0]
        return loc.address, short
    except:
        return "📍 Location found", "Mumbai"

@st.cache_data(ttl=600)
def get_live_rain_data(lat, lon):
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=rain,weathercode"
            f"&forecast_days=1&timezone=Asia%2FKolkata"
        )
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data     = r.json()
            now_hour = datetime.now().hour
            rain_mm  = data["hourly"]["rain"][now_hour]
            wcode    = data["hourly"]["weathercode"][now_hour]
            return float(rain_mm), int(wcode)
    except:
        pass
    return 0.0, 0

@st.cache_data(ttl=600)
def get_cached_weather(lat, lon):
    try:
        res = requests.get(f"https://wttr.in/{lat},{lon}?format=%C+%t&m", timeout=5)
        if res.status_code == 200:
            return res.text.strip()
    except:
        pass
    return "N/A"

# ============================================================
# 7. SESSION STATE INIT — all keys set upfront, no KeyErrors
# ============================================================
_defaults = {
    "sos_popup_dismissed": False,
    "sos_popup_crowd":     0,
    "timer_active":        False,
    "timer_end":           None,
    "timer_contact":       "",
    "timer_cname":         "",
    "custom_name":         "",
    "custom_no":           "91",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 8. HEADER
# ============================================================
st.title("🚉 Mumbai Survival Tracker")
st.caption(f"Engineered by Savio | {app_caption}")

# ============================================================
# 9. JOURNEY SELECTION
# ============================================================
st.subheader("🗺️ Journey")
col_a, col_b = st.columns(2)
with col_a:
    from_st = st.selectbox("From", mumbai_stations, index=get_index(mumbai_stations, "Bhandup"))
with col_b:
    to_st   = st.selectbox("To",   mumbai_stations, index=get_index(mumbai_stations, "Bandra"))

check_crowd_st = st.selectbox("Monitor Crowd At:", mumbai_stations, index=get_index(mumbai_stations, "Dadar"))

line_name, line_emoji = get_common_line(from_st, to_st)

fare_2nd, fare_1st, fare_band = get_fare(from_st, to_st)

# Show all journey info stacked — full labels visible on mobile
st.markdown(f"🛤️ **Route:** {line_emoji} {line_name}")
st.markdown(f"⏱️ **Est. Travel:** {get_travel_time(from_st, to_st)}")

if fare_2nd == "Same station":
    st.info("📍 From and To are the same station.")
else:
    st.markdown(f"🎫 **Second Class (General):** {fare_2nd}")
    st.markdown(f"🥇 **First Class:** {fare_1st}")
    st.caption("💡 Approximate fare — exact amount depends on km distance.")

st.caption(f"From: {get_line(from_st)}  |  To: {get_line(to_st)}")

# ============================================================
# 11. GPS
# ============================================================
st.sidebar.markdown("### 🛰️ Location")
if st.sidebar.button("📍 Activate GPS"):
    st.rerun()

loc = get_geolocation()
now = datetime.now()
current_time = now.strftime("%H:%M")

if loc and isinstance(loc, dict) and 'coords' in loc:
    coords = loc.get('coords', {})
    lat    = coords.get('latitude')
    lon    = coords.get('longitude')

    if lat is None or lon is None:
        st.warning("GPS returned incomplete data. Please tap Activate GPS again.")
        st.stop()

    # All safe data fetching
    address_full, address_short = get_cached_address(lat, lon)
    weather_data                = get_cached_weather(lat, lon)
    rain_mm, _                  = get_live_rain_data(lat, lon)
    rain_risk, _                = rain_to_risk(rain_mm)

    # Map link — defined once, reused everywhere safely
    map_link = f"https://www.google.com/maps?q={lat},{lon}"

    # ---- LIVE STATUS ----
    st.divider()
    st.subheader(f"📍 {address_short}")
    m1, m2, m3 = st.columns(3)
    m1.metric("🌡️ Weather",   weather_data)
    m2.metric("🌧️ Rain Now",  f"{rain_mm:.1f} mm/hr")
    m3.metric("🌊 Flood Risk", rain_risk)
    st.caption(f"📍 {address_full}")

    # ============================================================
    # 12. WATERLOGGING — live rain + hotspot cross-check
    # ============================================================
    st.divider()
    st.subheader("🌊 Waterlogging Risk")

    if rain_mm >= 3:
        st.error(f"🌧️ Active rain: **{rain_mm:.1f} mm/hr** — Checking flood hotspots...")
        route_stations = {from_st, to_st, check_crowd_st}
        route_warned   = False
        for zone, zone_stations in FLOOD_PRONE.items():
            if route_stations.intersection(zone_stations):
                st.error(f"🚨 **{zone}** — Your route passes a known flood zone! Risk: {rain_risk}")
                route_warned = True
        if not route_warned:
            st.warning(f"⚠️ Rain active ({rain_mm:.1f}mm/hr). Your stations aren't known hotspots, but stay cautious.")
        with st.expander("📍 All Mumbai flood hotspots"):
            for zone, zone_stations in FLOOD_PRONE.items():
                st.write(f"**{zone}** → {', '.join(zone_stations)}")
    else:
        st.success(f"✅ No significant rain ({rain_mm:.1f} mm/hr). Waterlogging risk: LOW.")
        st.caption("Live via Open-Meteo · Updates every 10 mins")

    # ============================================================
    # 13. CROWD TRACKING
    # ============================================================
    st.divider()
    st.subheader(f"📊 Crowd: {check_crowd_st}")

    is_peak    = ("07:30" <= current_time <= "09:30") or ("17:00" <= current_time <= "19:30")
    is_mon_fri = now.weekday() in (0, 4)

    crowd_pct = 35
    if is_peak:      crowd_pct += 45
    if rain_mm >= 3: crowd_pct += 15
    if is_mon_fri:   crowd_pct += 10
    crowd_pct = min(crowd_pct, 100)

    # SOS message uses actual crowd %
    sos_msg = make_sos_msg(crowd_pct, map_link)

    st.progress(crowd_pct / 100)
    st.write(f"**Crowd Density: {crowd_pct}%**")
    notes = []
    if is_peak:      notes.append("🔴 Peak hours")
    if is_mon_fri:   notes.append("📅 Mon/Fri rush")
    if rain_mm >= 3: notes.append("🌧️ Rain adding to crowd")
    if notes: st.caption(" · ".join(notes))

    if crowd_pct >= 80:
        st.error(f"🔴 EXTREME RUSH at {check_crowd_st}")
    elif crowd_pct >= 50:
        st.warning(f"🟠 HEAVY RUSH at {check_crowd_st}")
    else:
        st.success(f"🟢 COMFORTABLE at {check_crowd_st}")

    # ============================================================
    # 14. AUTO SOS POPUP — Personal users only, triggers at 90%+
    #     Resets only if crowd drops below 90 and rises again
    # ============================================================
    if is_personal and crowd_pct >= 90:
        if st.session_state.sos_popup_crowd < 90:
            # Just crossed 90 — reset dismiss so popup shows fresh
            st.session_state.sos_popup_dismissed = False
        st.session_state.sos_popup_crowd = crowd_pct

        if not st.session_state.sos_popup_dismissed:
            st.divider()
            with st.container(border=True):
                st.error("🚨 CROWD ALERT — DANGEROUSLY PACKED!")
                st.markdown(
                    f"Crowd at **{check_crowd_st}** just hit **{crowd_pct}%**. "
                    f"Do you want to alert your contacts?"
                )
                render_sos_buttons(sos_msg, context="main")
                if st.button("✅ I'm Safe — Dismiss", key="dismiss_auto_sos"):
                    st.session_state.sos_popup_dismissed = True
                    st.rerun()
    else:
        # Track when crowd is below 90 so popup can reset next time
        st.session_state.sos_popup_crowd = crowd_pct

    # ============================================================
    # 15. MANUAL SOS — Main page, visible on mobile for ALL users
    # ============================================================
    st.divider()
    st.subheader("🆘 Emergency SOS")
    st.write("Feeling unsafe? Tap to alert your contacts instantly:")
    render_sos_buttons(sos_msg, context="main")

    # Public users: contact entry below the SOS section
    if not is_personal:
        with st.expander("👤 Set your emergency contact"):
            st.session_state.custom_name = st.text_input(
                "Contact Name", st.session_state.custom_name, key="main_cname"
            )
            st.session_state.custom_no = st.text_input(
                "WhatsApp No (with country code, e.g. 917XXXXXXXX)",
                st.session_state.custom_no, key="main_cno"
            )

    # ============================================================
    # 16. SIDEBAR SOS MIRROR — quick access without scrolling
    # ============================================================
    st.sidebar.divider()
    st.sidebar.error("⚠️ SOS — Feeling Unsafe?")
    render_sos_buttons(sos_msg, context="sidebar")

    if not is_personal:
        st.sidebar.write("👤 Set emergency contact:")
        st.session_state.custom_name = st.sidebar.text_input(
            "Name", st.session_state.custom_name, key="sb_cname"
        )
        st.session_state.custom_no = st.sidebar.text_input(
            "WhatsApp No (e.g. 917XXXXXXXX)", st.session_state.custom_no, key="sb_cno"
        )

    # ============================================================
    # 17. JOURNEY MAP
    # ============================================================
    st.divider()
    st.subheader("🗺️ Journey Map")
    maps_url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={from_st.replace(' ', '+')}+Station+Mumbai"
        f"&destination={to_st.replace(' ', '+')}+Station+Mumbai"
        f"&travelmode=transit"
    )
    st.link_button("🗺️ Open in Google Maps", maps_url, use_container_width=True)
    iframe_src = (
        f"https://maps.google.com/maps"
        f"?q={to_st.replace(' ', '+')}+Station+Mumbai&output=embed&z=14"
    )
    st.components.v1.iframe(iframe_src, height=250)

    # ============================================================
    # 18. SAFETY TIMER
    # ============================================================
    st.divider()
    st.subheader("⏳ Safety Timer")
    st.caption("Set your journey time. If you don't check in on arrival, an alert prompt will appear.")

    if not st.session_state.timer_active:
        timer_mins = st.slider("Journey duration (minutes)", 5, 120, 30, step=5)

        if is_personal:
            contacts      = sos_contacts_for_user()
            contact_names = [c["name"] for c in contacts]
            contact_nums  = {c["name"]: c["number"] for c in contacts}
            chosen = st.selectbox("Alert who if you don't check in?", contact_names, key="timer_contact_select")
            t_name = chosen
            t_no   = contact_nums[chosen]
        else:
            t_name = st.text_input("Contact name", st.session_state.custom_name or "Near One", key="timer_name")
            t_no   = st.text_input("Their WhatsApp (with country code)", st.session_state.custom_no or "91", key="timer_no")

        if st.button("🚀 Start Timer", type="primary"):
            if t_no and len(str(t_no)) > 10:
                st.session_state.timer_active  = True
                st.session_state.timer_end     = datetime.now() + timedelta(minutes=timer_mins)
                st.session_state.timer_contact = str(t_no)
                st.session_state.timer_cname   = str(t_name)
                st.session_state.timer_total   = timer_mins * 60
                st.rerun()
            else:
                st.error("Please enter a valid WhatsApp number (with country code) first.")

    else:
        end_time  = st.session_state.timer_end
        remaining = (end_time - datetime.now()).total_seconds()
        total_secs = float(st.session_state.get("timer_total", 1800))

        if remaining > 0:
            mins_left = int(remaining // 60)
            secs_left = int(remaining % 60)
            # Safe progress value, clamped 0.0–1.0, no division errors
            progress_val = max(0.0, min(1.0, 1.0 - (remaining / max(total_secs, 1.0))))

            st.success(f"⏱️ Timer running — **{mins_left}m {secs_left}s** left")
            st.progress(progress_val)
            if st.button("✅ I Arrived Safely — Stop Timer"):
                st.session_state.timer_active = False
                st.session_state.timer_end    = None
                st.success("Timer stopped. Stay safe! 🙏")
                st.rerun()
        else:
            # Expired — show alert prompt
            timer_msg = (
                f"I%20started%20my%20journey%20but%20haven%27t%20checked%20in.%20"
                f"My%20last%20known%20location%3A%20{map_link}"
            )
            st.error("⚠️ Timer expired — you haven't checked in!")
            cno   = st.session_state.timer_contact
            cname = st.session_state.timer_cname or "Contact"
            if cno and len(cno) > 10:
                st.link_button(
                    f"🚨 Send Alert to {cname} on WhatsApp",
                    f"https://wa.me/{cno}?text={timer_msg}",
                    use_container_width=True
                )
            if st.button("🔁 Reset Timer"):
                st.session_state.timer_active = False
                st.session_state.timer_end    = None
                st.rerun()

    # ============================================================
    # 19. CONNECTIVITY
    # ============================================================
    st.divider()
    st.subheader("🛺 Get Home")
    col1, col2, col3 = st.columns(3)
    col1.link_button("🚗 Uber",   "https://m.uber.com/ul/?action=setPickup&pickup=my_location", use_container_width=True)
    col2.link_button("🚕 Ola",    "https://book.olacabs.com/",  use_container_width=True)
    col3.link_button("🛵 Rapido", "https://rapido.bike/",       use_container_width=True)

# ============================================================
# GPS NOT READY
# ============================================================
else:
    st.info("🛰️ Searching for GPS...")
    st.warning("Tap **📍 Activate GPS** in the sidebar, or enable Location in browser settings (🔒 in address bar).")

# ============================================================
# 20. FOOTER
# ============================================================
st.divider()
if is_dhanashri:
    st.info("✨ Safe Journey, Dhanashri! Keep your bag in front. You've got this! 💜")
elif is_mom:
    st.info("✨ Safe Journey, Mom! Be careful while boarding. Call Savio if you need anything! 🧡")
else:
    st.info("✨ Safe Journey! Keep your belongings safe and stay alert. 🙏")

st.caption(f"Last sync: {current_time} | Built with ❤️ by Savio | Rain: Open-Meteo | Trains: RapidAPI IRCTC")

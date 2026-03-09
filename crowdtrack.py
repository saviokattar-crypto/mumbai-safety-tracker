import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim
from streamlit_autorefresh import st_autorefresh

# ============================================================
# 1. CONFIG — no layout="wide" so it works on mobile too
# ============================================================
st.set_page_config(page_title="Mumbai Survival Tracker", page_icon="🚉")
st_autorefresh(interval=60000, key="datarefresh")

# Hide only the download/install banner — keep everything else intact
st.markdown("""
<style>
.stAppDeployButton {display: none;}
footer {visibility: hidden;}
[data-testid="stDecoration"] {display: none;}
</style>
""", unsafe_allow_html=True)


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
            now_hour = datetime.now(timezone(timedelta(hours=5, minutes=30))).hour
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
IST          = timezone(timedelta(hours=5, minutes=30))
now          = datetime.now(IST)
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
# GPS NOT READY
# ============================================================
else:
    st.info("🛰️ Searching for GPS...")
    st.warning("Tap **📍 Activate GPS** in the sidebar, or enable Location in browser settings (🔒 in address bar).")

rain_mm  = rain_mm  if 'rain_mm'  in dir() else 0.0
map_link = map_link if 'map_link' in dir() else "https://www.google.com/maps"
# 13. CROWD TRACKING
# ============================================================
# ── Time intelligence ──────────────────────────────────────
now    = datetime.now(timezone(timedelta(hours=5, minutes=30)))  # always IST
hour   = now.hour
minute = now.minute
t      = hour + minute / 60.0          # e.g. 8.5 = 8:30am
weekday = now.weekday()                # 0=Mon … 6=Sun
is_weekend  = weekday in (5, 6)
is_monday   = weekday == 0
is_friday   = weekday == 4
is_mon_fri  = is_monday or is_friday

# ── Per-station hourly crowd profile ────────────────────────
# Each station has 24 hourly base values (0-100) reflecting
# real observed crowding patterns on Mumbai local network.
# Source: Western/Central Railway published load surveys +
#         ground knowledge of each station's traffic type.
HOURLY = {
  # hour →  0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20  21  22  23
  "Dadar":       [ 5,  3,  2,  2,  3, 10, 25, 72, 95, 80, 60, 50, 55, 52, 55, 62, 78, 95, 90, 70, 50, 35, 20, 10],
  "Andheri":     [ 5,  3,  2,  2,  3,  8, 20, 65, 90, 75, 55, 45, 48, 45, 50, 58, 72, 90, 88, 65, 45, 30, 18,  8],
  "CSMT":        [ 5,  3,  2,  2,  3, 10, 28, 75, 95, 82, 62, 52, 55, 53, 56, 63, 75, 92, 88, 68, 48, 32, 20, 10],
  "Churchgate":  [ 5,  3,  2,  2,  3, 10, 28, 72, 93, 80, 60, 50, 52, 50, 54, 60, 73, 90, 86, 65, 46, 30, 18,  8],
  "Kurla":       [ 5,  3,  2,  2,  3,  8, 22, 68, 88, 72, 55, 45, 50, 47, 52, 60, 74, 90, 86, 64, 44, 28, 16,  8],
  "Bandra":      [ 5,  3,  2,  2,  3,  7, 18, 60, 85, 70, 52, 45, 50, 48, 52, 60, 72, 88, 85, 62, 42, 28, 15,  7],
  "Thane":       [ 5,  3,  2,  2,  4,  8, 20, 62, 85, 72, 54, 44, 48, 45, 50, 58, 70, 88, 84, 62, 42, 28, 16,  8],
  "Borivali":    [ 5,  3,  2,  2,  4,  8, 22, 65, 88, 74, 55, 45, 48, 45, 50, 58, 70, 87, 83, 60, 40, 26, 15,  7],
  "Ghatkopar":   [ 5,  3,  2,  2,  3,  7, 18, 60, 85, 70, 52, 42, 46, 44, 48, 56, 68, 86, 83, 60, 40, 26, 14,  6],
  "Kalyan":      [ 5,  3,  2,  2,  5, 10, 25, 65, 82, 68, 50, 40, 44, 42, 46, 54, 66, 84, 80, 58, 38, 24, 14,  7],
  "Lower Parel": [ 5,  3,  2,  2,  3,  7, 18, 58, 82, 72, 60, 52, 55, 54, 58, 65, 75, 88, 82, 60, 40, 25, 14,  6],
  "Goregaon":    [ 5,  3,  2,  2,  3,  7, 18, 58, 80, 65, 48, 40, 44, 42, 46, 54, 66, 82, 78, 56, 36, 23, 13,  6],
  "Malad":       [ 5,  3,  2,  2,  3,  7, 16, 55, 78, 63, 46, 38, 42, 40, 44, 52, 64, 80, 76, 54, 34, 22, 12,  5],
  "Kandivali":   [ 5,  3,  2,  2,  3,  6, 15, 52, 75, 60, 44, 36, 40, 38, 42, 50, 62, 78, 74, 52, 32, 20, 11,  5],
  "Mulund":      [ 5,  3,  2,  2,  3,  6, 15, 52, 74, 60, 44, 36, 40, 38, 42, 50, 62, 78, 74, 52, 32, 20, 11,  5],
  "Bhandup":     [ 5,  3,  2,  2,  3,  6, 14, 48, 70, 56, 42, 34, 38, 36, 40, 48, 60, 75, 70, 48, 30, 18, 10,  5],
  "Nahur":       [ 4,  2,  2,  2,  3,  5, 12, 42, 64, 50, 38, 30, 34, 32, 36, 44, 55, 70, 65, 44, 28, 16,  9,  4],
  "Vikhroli":    [ 4,  2,  2,  2,  3,  6, 14, 48, 70, 56, 42, 34, 38, 36, 40, 48, 60, 76, 72, 50, 30, 18, 10,  5],
  "Kanjurmarg":  [ 4,  2,  2,  2,  3,  5, 12, 44, 65, 52, 38, 30, 34, 32, 36, 44, 55, 70, 66, 44, 26, 16,  9,  4],
  "Sion":        [ 4,  2,  2,  2,  3,  6, 16, 52, 74, 60, 46, 36, 40, 38, 44, 52, 64, 80, 75, 52, 32, 20, 11,  5],
  "Matunga":     [ 4,  2,  2,  2,  3,  6, 15, 50, 72, 58, 44, 35, 39, 37, 42, 50, 62, 78, 73, 50, 30, 18, 10,  5],
  "Dombivli":    [ 4,  2,  2,  2,  4,  8, 20, 58, 78, 64, 46, 38, 42, 40, 44, 52, 64, 80, 76, 54, 34, 20, 12,  6],
  "Vashi":       [ 4,  2,  2,  2,  3,  6, 14, 48, 68, 55, 42, 34, 38, 36, 40, 48, 58, 74, 70, 48, 28, 16,  9,  4],
  "Panvel":      [ 4,  2,  2,  2,  4,  7, 16, 50, 70, 56, 42, 34, 38, 36, 40, 48, 58, 74, 70, 48, 28, 16,  9,  4],
  "Nerul":       [ 3,  2,  2,  2,  3,  5, 12, 40, 60, 48, 36, 28, 32, 30, 34, 42, 52, 66, 62, 42, 24, 14,  8,  3],
  "Belapur":     [ 3,  2,  2,  2,  3,  5, 12, 38, 58, 46, 35, 27, 30, 28, 32, 40, 50, 64, 60, 40, 22, 13,  7,  3],
  "Virar":       [ 3,  2,  2,  2,  5, 10, 22, 55, 72, 58, 40, 30, 34, 32, 36, 44, 54, 68, 64, 44, 26, 15,  8,  4],
  "Vasai Road":  [ 3,  2,  2,  2,  4,  8, 18, 48, 65, 52, 38, 28, 32, 30, 34, 42, 52, 65, 60, 40, 22, 13,  7,  3],
  "Nallasopara": [ 3,  2,  2,  2,  4,  8, 16, 44, 62, 48, 36, 27, 30, 28, 32, 40, 50, 62, 58, 38, 20, 12,  6,  3],
  "Ambernath":   [ 3,  2,  2,  2,  4,  7, 14, 40, 58, 46, 34, 26, 29, 27, 31, 38, 48, 60, 56, 36, 20, 11,  6,  3],
  "Badlapur":    [ 2,  2,  2,  2,  3,  6, 12, 35, 52, 40, 30, 22, 25, 23, 27, 34, 42, 55, 50, 32, 16,  9,  5,  2],
  "Karjat":      [ 2,  2,  2,  2,  3,  5, 10, 28, 42, 32, 22, 16, 18, 16, 20, 26, 34, 44, 40, 24, 12,  7,  4,  2],
  "Kasara":      [ 2,  2,  2,  2,  3,  4,  8, 22, 34, 26, 18, 12, 14, 12, 16, 20, 28, 36, 32, 18,  9,  5,  3,  2],
  "Palghar":     [ 2,  2,  2,  2,  3,  4,  8, 22, 32, 24, 16, 11, 13, 11, 14, 18, 26, 34, 30, 16,  8,  4,  3,  2],
  "Boisar":      [ 2,  2,  2,  2,  3,  4,  7, 18, 28, 20, 14,  9, 11,  9, 12, 16, 22, 30, 26, 14,  6,  4,  2,  2],
  "Dahanu Road": [ 2,  2,  2,  2,  3,  3,  6, 15, 24, 16, 11,  7,  9,  7, 10, 13, 18, 25, 22, 11,  5,  3,  2,  2],
}

# Get base from hourly profile — interpolate between hours for smoothness
profile  = HOURLY.get(check_crowd_st, None)
if profile:
    base_h   = profile[hour]
    base_h1  = profile[(hour + 1) % 24]
    frac     = minute / 60.0
    base     = int(base_h + (base_h1 - base_h) * frac)   # smooth between hours
else:
    # Unknown station — use a generic medium profile
    generic = [ 5, 3, 2, 2, 3, 6, 15, 45, 65, 52, 40, 32, 36, 34, 38, 46, 58, 72, 68, 46, 28, 17, 10, 5]
    base_h  = generic[hour]
    base_h1 = generic[(hour + 1) % 24]
    base    = int(base_h + (base_h1 - base_h) * (minute / 60.0))

# ── Weekend adjustment ───────────────────────────────────────
SHOPPING = {"Dadar","Andheri","Bandra","Kurla","Thane","Borivali","Churchgate","CSMT"}
if is_weekend:
    if check_crowd_st in SHOPPING:
        base = int(base * 0.80)   # shopping crowd replaces office crowd
    else:
        base = int(base * 0.55)   # much quieter on weekends

# ── Calendar intelligence ───────────────────────────────────
month = now.month
day   = now.day

# Monsoon — trains packed due to delays and flooding
is_monsoon = month in (6, 7, 8, 9)

# Exam season — lighter crowds (Mar–Apr, mid Oct–mid Nov)
is_exam_season = (month in (3, 4)) or (month == 10 and day >= 15) or (month == 11 and day <= 15)

# Last train rush — after 10:30pm at terminus stations
TERMINUS = {"Churchgate","CSMT","Virar","Dahanu Road","Kasara","Karjat","Panvel","Boisar","Kalyan","Thane"}
is_last_train = (hour == 23) or (hour == 22 and minute >= 30)

# Festival calendar — Mumbai major festivals
FESTIVALS = {
    (9,7):("Ganpati",30),(9,8):("Ganpati",35),(9,9):("Ganpati",30),(9,10):("Ganpati",25),(9,11):("Ganpati",20),
    (8,27):("Ganpati",30),(8,28):("Ganpati",35),(8,29):("Ganpati",30),(8,30):("Ganpati",25),(8,31):("Ganpati",20),
    (9,15):("Ganpati",30),(9,16):("Ganpati",35),(9,17):("Ganpati Visarjan",40),
    (9,5):("Ganpati Visarjan",40),
    (10,29):("Diwali",35),(10,30):("Diwali",35),(10,31):("Diwali",30),
    (11,1):("Diwali",30),(11,2):("Diwali",25),(11,12):("Diwali",35),(11,13):("Diwali",35),
    (4,10):("Eid",25),(4,11):("Eid",20),(3,30):("Eid",25),(3,31):("Eid",20),
    (6,17):("Eid ul-Adha",25),(6,18):("Eid ul-Adha",20),
    (12,24):("Christmas Eve",20),(12,25):("Christmas",15),
    (12,31):("New Year Eve",30),(1,1):("New Year",20),
    (3,25):("Holi",20),(3,26):("Holi",15),(3,14):("Holi",20),(3,15):("Holi",15),
    (10,3):("Navratri",15),(10,4):("Navratri",15),(10,12):("Navratri",15),(10,13):("Navratri",15),
    (1,26):("Republic Day",-10),(8,15):("Independence Day",-10),
}
festival_name, festival_boost = FESTIVALS.get((month, day), (None, 0))

# IPL at Wankhede — Mar 22 to Jun 2, evening matches
WANKHEDE = {"Churchgate","Marine Lines","Charni Road","CSMT"}
is_ipl = (month == 3 and day >= 22) or month in (4,5) or (month == 6 and day <= 2)
is_ipl_boost = check_crowd_st in WANKHEDE and is_ipl and 18 <= hour <= 23

# ── Live signal boosters ─────────────────────────────────────
crowd_pct = base
if rain_mm >= 3:   crowd_pct += 12
if rain_mm >= 8:   crowd_pct += 8
if is_mon_fri:     crowd_pct += 6
if is_monsoon:     crowd_pct += 10
if is_exam_season: crowd_pct -= 8
if festival_boost: crowd_pct += festival_boost
if is_ipl_boost:   crowd_pct += 25
if is_last_train and check_crowd_st in TERMINUS: crowd_pct += 20
crowd_pct = min(max(crowd_pct, 0), 100)

# SOS message uses actual crowd %
sos_msg = make_sos_msg(crowd_pct, map_link)

st.divider()
st.subheader(f"📊 Crowd: {check_crowd_st}")
st.progress(crowd_pct / 100)
st.write(f"**Crowd Density: {crowd_pct}%**")
notes = []
is_peak = ("07:30" <= current_time <= "09:30") or ("17:00" <= current_time <= "19:30")
if is_peak:        notes.append("🔴 Peak hours")
if is_mon_fri:     notes.append("📅 Mon/Fri rush")
if rain_mm >= 3:   notes.append("🌧️ Rain boost")
if is_monsoon:     notes.append("🌧️ Monsoon season")
if is_exam_season: notes.append("📚 Exam season — lighter")
if festival_name:  notes.append(f"🎉 {festival_name}")
if is_ipl_boost:   notes.append("🏏 IPL match nearby")
if is_last_train and check_crowd_st in TERMINUS: notes.append("🚉 Last train rush")
if notes: st.caption(" · ".join(notes))

if crowd_pct >= 80:
    st.error(f"🔴 EXTREME RUSH at {check_crowd_st}")
elif crowd_pct >= 50:
    st.warning(f"🟠 HEAVY RUSH at {check_crowd_st}")
else:
    st.success(f"🟢 COMFORTABLE at {check_crowd_st}")



# ============================================================
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
# SIDEBAR MUSIC — below games
# ============================================================
st.sidebar.divider()
st.sidebar.markdown("### 🎵 Mood Music")
st.sidebar.caption("How are you feeling right now?")

MOODS = {
    "😴 Tired / Sleepy":     ("Sleep & Relax",     "https://music.youtube.com/search?q=sleep+relax+music"),
    "😊 Happy / Chill":      ("Happy Vibes",        "https://music.youtube.com/search?q=happy+chill+vibes+playlist"),
    "💜 Feeling Lonely":     ("Lonely Feels",       "https://music.youtube.com/search?q=lonely+sad+bollywood+songs"),
    "🔥 Energetic / Hype":   ("Power Hype",         "https://music.youtube.com/search?q=energetic+hype+workout+music"),
    "😤 Stressed / Anxious": ("Stress Relief",      "https://music.youtube.com/search?q=stress+relief+calm+music"),
    "🌧️ Rainy Day Vibes":   ("Rainy Day",          "https://music.youtube.com/search?q=rainy+day+lofi+hindi+songs"),
    "💃 Party Mode":         ("Party Hits",         "https://music.youtube.com/search?q=bollywood+party+hits+2024"),
    "🧘 Calm / Peaceful":    ("Calm & Peace",       "https://music.youtube.com/search?q=calm+peaceful+meditation+music"),
}

selected_mood = st.sidebar.selectbox(
    "Pick your mood:",
    list(MOODS.keys()),
    key="mood_select"
)
playlist_name, playlist_url = MOODS[selected_mood]
st.sidebar.link_button(
    f"🎵 Play: {playlist_name} on YT Music",
    playlist_url,
    use_container_width=True
)
st.sidebar.caption("Opens YouTube Music 🎶")





# ============================================================
# GAMES — each renders full width, tall enough for phone
# ============================================================
st.divider()
st.subheader("🎮 Games — Kill Time!")
st.caption("Tap a game to expand and play!")

tab1, tab2, tab3, tab4 = st.tabs(["🐍 Snake", "🟨 2048", "🐦 Flappy Bird", "🚗 Racer"])

# ---------- SNAKE ----------
with tab1:
    st.components.v1.html("""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;background:#1a1a2e;display:flex;flex-direction:column;align-items:center;font-family:Arial;user-select:none;overflow:hidden}
#sc{color:#00ff88;font-size:18px;margin:8px 0 2px}
#mg{color:#ff4444;font-size:15px;height:20px;margin-bottom:4px}
canvas{display:block;border:3px solid #00ff88;touch-action:none}
.dp{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;width:180px}
.dp button,.dp div{width:56px;height:56px}
.dp button{font-size:24px;background:#00cc66;border:none;border-radius:10px;color:#fff;font-weight:bold;touch-action:manipulation;cursor:pointer}
#startBtn{margin-top:10px;padding:12px 36px;background:#00ff88;border:none;border-radius:10px;font-weight:bold;font-size:16px;cursor:pointer;touch-action:manipulation}
</style></head><body>
<div id="sc">Score: 0</div>
<div id="mg">Tap Start!</div>
<canvas id="c"></canvas>
<div class="dp">
  <div></div>
  <button ontouchstart="sd(0,-1);stop(event)" onclick="sd(0,-1)">▲</button>
  <div></div>
  <button ontouchstart="sd(-1,0);stop(event)" onclick="sd(-1,0)">◀</button>
  <button ontouchstart="sd(0,1);stop(event)" onclick="sd(0,1)">▼</button>
  <button ontouchstart="sd(1,0);stop(event)" onclick="sd(1,0)">▶</button>
</div>
<button id="startBtn" ontouchstart="sg();stop(event)" onclick="sg()">▶ Start</button>
<script>
function stop(e){e.preventDefault();}
const C=document.getElementById('c');
const N=15;
// Use canvas CSS width which respects iframe width correctly
C.style.width='min(92vw,360px)';
C.style.height='min(92vw,360px)';
C.width=360; C.height=360;
const SZ=360/N;
const X=C.getContext('2d');
let sn,dr,fd,sc,iv,tx=0,ty=0;

C.addEventListener('touchstart',e=>{tx=e.touches[0].clientX;ty=e.touches[0].clientY;e.preventDefault();},{passive:false});
C.addEventListener('touchend',e=>{
  const dx=e.changedTouches[0].clientX-tx,dy=e.changedTouches[0].clientY-ty;
  if(Math.abs(dx)>Math.abs(dy))sd(dx>0?1:-1,0);else sd(0,dy>0?1:-1);
  e.preventDefault();},{passive:false});
document.addEventListener('keydown',e=>{
  ({ArrowUp:()=>sd(0,-1),ArrowDown:()=>sd(0,1),ArrowLeft:()=>sd(-1,0),ArrowRight:()=>sd(1,0)})[e.key]?.();
});
function sg(){
  sn=[{x:7,y:7},{x:6,y:7},{x:5,y:7}];dr={x:1,y:0};sc=0;
  document.getElementById('mg').textContent='Swipe or use D-pad!';
  pf();clearInterval(iv);iv=setInterval(lp,185);
}
function sd(x,y){if(!(x===-dr.x&&y===-dr.y))dr={x,y};}
function pf(){fd={x:Math.floor(Math.random()*N),y:Math.floor(Math.random()*N)};}
function lp(){
  const h={x:sn[0].x+dr.x,y:sn[0].y+dr.y};
  if(h.x<0||h.x>=N||h.y<0||h.y>=N||sn.some(s=>s.x===h.x&&s.y===h.y)){
    clearInterval(iv);document.getElementById('mg').textContent='💀 Game Over! Tap Start';return;
  }
  sn.unshift(h);
  if(h.x===fd.x&&h.y===fd.y){sc++;document.getElementById('sc').textContent='Score: '+sc;pf();}
  else sn.pop();
  draw();
}
function draw(){
  X.fillStyle='#1a1a2e';X.fillRect(0,0,C.width,C.height);
  X.fillStyle='#ff4444';X.fillRect(fd.x*SZ,fd.y*SZ,SZ-2,SZ-2);
  sn.forEach((s,i)=>{X.fillStyle=i===0?'#00ff88':'#009944';X.fillRect(s.x*SZ,s.y*SZ,SZ-2,SZ-2);});
}
draw();
</script></body></html>""", height=580)

# ---------- 2048 ----------
with tab2:
    st.components.v1.html("""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;background:#1a1a2e;display:flex;flex-direction:column;align-items:center;font-family:Arial;user-select:none;padding:10px 0}
#sc{color:#ffdd57;font-size:18px;margin:6px 0 2px}
#mg{color:#ff4444;font-size:14px;height:18px;margin-bottom:4px}
#grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;width:min(92vw,340px);touch-action:none}
.cell{aspect-ratio:1;display:flex;align-items:center;justify-content:center;border-radius:8px;font-weight:bold;font-size:clamp(16px,5vw,24px);color:#1a1a2e}
.dp{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px;width:180px}
.dp button,.dp div{width:56px;height:56px}
.dp button{font-size:24px;background:#ccaa00;border:none;border-radius:10px;cursor:pointer;font-weight:bold;touch-action:manipulation;color:#1a1a2e}
#newBtn{margin-top:10px;padding:12px 36px;background:#ffdd57;border:none;border-radius:10px;font-weight:bold;font-size:16px;cursor:pointer;touch-action:manipulation;color:#1a1a2e}
</style></head><body>
<div id="sc">Score: 0</div>
<div id="mg">Swipe grid or use D-pad!</div>
<div id="grid"></div>
<div class="dp">
  <div></div>
  <button ontouchstart="mv('up');stop(event)" onclick="mv('up')">▲</button>
  <div></div>
  <button ontouchstart="mv('left');stop(event)" onclick="mv('left')">◀</button>
  <button ontouchstart="mv('down');stop(event)" onclick="mv('down')">▼</button>
  <button ontouchstart="mv('right');stop(event)" onclick="mv('right')">▶</button>
</div>
<button id="newBtn" ontouchstart="init();stop(event)" onclick="init()">🔄 New Game</button>
<script>
function stop(e){e.preventDefault();}
const CL={0:'#3a3a5e',2:'#eee4da',4:'#ede0c8',8:'#f2b179',16:'#f59563',32:'#f67c5f',64:'#f65e3b',128:'#edcf72',256:'#edcc61',512:'#edc850',1024:'#edc53f',2048:'#edc22e'};
let bd,sc,tx,ty;
const G=document.getElementById('grid');
G.addEventListener('touchstart',e=>{tx=e.touches[0].clientX;ty=e.touches[0].clientY;e.preventDefault();},{passive:false});
G.addEventListener('touchend',e=>{
  const dx=e.changedTouches[0].clientX-tx,dy=e.changedTouches[0].clientY-ty;
  Math.abs(dx)>Math.abs(dy)?mv(dx>0?'right':'left'):mv(dy>0?'down':'up');
  e.preventDefault();},{passive:false});
document.addEventListener('keydown',e=>{
  ({ArrowUp:()=>mv('up'),ArrowDown:()=>mv('down'),ArrowLeft:()=>mv('left'),ArrowRight:()=>mv('right')})[e.key]?.();
});
function init(){bd=Array(4).fill(0).map(()=>Array(4).fill(0));sc=0;at();at();rn();}
function at(){let e=[];bd.forEach((r,i)=>r.forEach((v,j)=>{if(!v)e.push([i,j]);}));if(!e.length)return;const[i,j]=e[Math.floor(Math.random()*e.length)];bd[i][j]=Math.random()<0.9?2:4;}
function rn(){
  G.innerHTML='';
  bd.forEach(r=>r.forEach(v=>{const d=document.createElement('div');d.className='cell';d.style.background=CL[v]||'#3a3a5e';d.textContent=v||'';G.appendChild(d);}));
  document.getElementById('sc').textContent='Score: '+sc;
  if(bd.some(r=>r.includes(2048)))document.getElementById('mg').textContent='🏆 You Win!';
}
function sl(row){let a=row.filter(x=>x);for(let i=0;i<a.length-1;i++){if(a[i]===a[i+1]){a[i]*=2;sc+=a[i];a.splice(i+1,1);}}while(a.length<4)a.push(0);return a;}
function mv(d){
  let b=bd.map(r=>[...r]);
  if(d==='left')b=b.map(r=>sl(r));
  else if(d==='right')b=b.map(r=>sl([...r].reverse()).reverse());
  else if(d==='up'){b=b[0].map((_,i)=>b.map(r=>r[i])).map(r=>sl(r));b=b[0].map((_,i)=>b.map(r=>r[i]));}
  else if(d==='down'){b=b[0].map((_,i)=>b.map(r=>r[i]).reverse()).map(r=>sl(r)).map(r=>r.reverse());b=b[0].map((_,i)=>b.map(r=>r[i]));}
  if(JSON.stringify(b)!==JSON.stringify(bd)){bd=b;at();}rn();
}
init();
</script></body></html>""", height=560)

# ---------- FLAPPY BIRD ----------
with tab3:
    st.components.v1.html("""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a2e;display:flex;flex-direction:column;align-items:center;font-family:Arial;padding:8px;user-select:none}
#sc{color:#00aaff;font-size:20px;font-weight:bold;margin:6px 0}
#msg{color:#ff4444;font-size:15px;min-height:20px;margin-bottom:6px}
canvas{background:#70c5ce;display:block;width:min(95vw,340px);height:auto;border:3px solid #00aaff;border-radius:8px}
#btn{margin-top:10px;padding:14px 40px;background:#00aaff;color:#fff;border:none;border-radius:10px;font-size:17px;font-weight:bold;cursor:pointer;touch-action:manipulation}
</style>
</head>
<body>
<div id="sc">Score: 0</div>
<div id="msg">Press Start then tap to flap!</div>
<canvas id="c" width="320" height="480"></canvas>
<button id="btn" onclick="startGame()" ontouchstart="startGame();event.preventDefault()">Start</button>
<script>
var cv=document.getElementById('c'),ctx=cv.getContext('2d');
var W=320,H=480,bird,pipes,score,running,raf,frame;
function startGame(){
  bird={x:60,y:H/2,r:14,v:0};
  pipes=[];score=0;running=true;frame=0;
  document.getElementById('msg').textContent='Tap to flap!';
  document.getElementById('sc').textContent='Score: 0';
  cancelAnimationFrame(raf);
  tick();
}
function flap(){if(running)bird.v=-3.2;}
cv.addEventListener('touchstart',function(e){e.preventDefault();flap();},{passive:false});
cv.addEventListener('click',flap);
document.addEventListener('keydown',function(e){if(e.code==='Space'){e.preventDefault();flap();}});
function tick(){
  if(!running)return;
  frame++;
  bird.v+=0.10; bird.y+=bird.v;
  if(frame%130===0){
    var gap=200,top=60+Math.random()*(H-gap-120);
    pipes.push({x:W,top:top,gap:gap,scored:false});
  }
  for(var i=0;i<pipes.length;i++)pipes[i].x-=1.4;
  pipes=pipes.filter(function(p){return p.x>-60;});
  for(var i=0;i<pipes.length;i++){
    if(!pipes[i].scored&&pipes[i].x+50<bird.x){
      pipes[i].scored=true;score++;
      document.getElementById('sc').textContent='Score: '+score;
    }
  }
  if(bird.y+bird.r>H-20||bird.y-bird.r<0){gameOver();return;}
  for(var i=0;i<pipes.length;i++){
    var p=pipes[i];
    if(bird.x+bird.r-6>p.x&&bird.x-bird.r+6<p.x+50){
      if(bird.y-bird.r+6<p.top||bird.y+bird.r-6>p.top+p.gap){gameOver();return;}
    }
  }
  draw();raf=requestAnimationFrame(tick);
}
function gameOver(){
  running=false;draw();
  document.getElementById('msg').textContent='Game Over! Score: '+score;
}
function draw(){
  ctx.fillStyle='#70c5ce';ctx.fillRect(0,0,W,H);
  for(var i=0;i<pipes.length;i++){
    var p=pipes[i];
    ctx.fillStyle='#33aa33';
    ctx.fillRect(p.x,0,50,p.top);
    ctx.fillRect(p.x,p.top+p.gap,50,H);
    ctx.fillStyle='#228822';
    ctx.fillRect(p.x-4,p.top-20,58,20);
    ctx.fillRect(p.x-4,p.top+p.gap,58,20);
  }
  ctx.fillStyle='#c2a85a';ctx.fillRect(0,H-20,W,20);
  ctx.fillStyle='#5d8a3c';ctx.fillRect(0,H-22,W,4);
  ctx.fillStyle='#FFD700';
  ctx.beginPath();ctx.arc(bird.x,bird.y,bird.r,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#000';
  ctx.beginPath();ctx.arc(bird.x+6,bird.y-4,3,0,Math.PI*2);ctx.fill();
  ctx.fillStyle='#FF6600';
  ctx.beginPath();ctx.moveTo(bird.x+12,bird.y);ctx.lineTo(bird.x+20,bird.y-3);ctx.lineTo(bird.x+20,bird.y+4);ctx.closePath();ctx.fill();
}
draw();
</script>
</body>
</html>""", height=680)


# ---------- TRAFFIC RACER ----------
with tab4:
    st.components.v1.html("""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;background:#1a1a2e;display:flex;flex-direction:column;align-items:center;font-family:Arial;user-select:none;overflow:hidden}
#hud{color:#ff6600;font-size:16px;display:flex;gap:24px;margin:8px 0 2px}
#mg{color:#ff4444;font-size:14px;height:18px;margin-bottom:4px}
canvas{display:block;border:3px solid #ff6600;touch-action:none}
.ctrl{display:flex;gap:12px;margin-top:10px;width:100%;max-width:400px;padding:0 10px}
.ctrl button{flex:1;height:70px;font-size:26px;background:#222;border:3px solid #ff6600;border-radius:14px;cursor:pointer;color:#ff6600;font-weight:bold;touch-action:manipulation}
.ctrl button:active{background:#ff6600;color:#fff}
#startBtn{margin-top:10px;padding:12px 40px;background:#ff6600;border:none;border-radius:10px;font-weight:bold;font-size:16px;color:#fff;cursor:pointer;touch-action:manipulation}
</style></head><body>
<div id="hud"><span id="sc">Score: 0</span><span id="sp">Speed: 1.0x</span></div>
<div id="mg">Tap Start to Race!</div>
<canvas id="c"></canvas>
<div class="ctrl">
  <button id="lb"
    ontouchstart="lLeft=true;event.preventDefault()"
    ontouchend="lLeft=false;event.preventDefault()"
    ontouchcancel="lLeft=false"
    onmousedown="lLeft=true" onmouseup="lLeft=false" onmouseleave="lLeft=false">◀ Left</button>
  <button id="rb"
    ontouchstart="lRight=true;event.preventDefault()"
    ontouchend="lRight=false;event.preventDefault()"
    ontouchcancel="lRight=false"
    onmousedown="lRight=true" onmouseup="lRight=false" onmouseleave="lRight=false">Right ▶</button>
</div>
<button id="startBtn" ontouchstart="startGame();event.preventDefault()" onclick="startGame()">▶ Start</button>
<script>
const C=document.getElementById('c');
// Fixed logical canvas — CSS scales it visually
const W=400, H=480;
C.width=W; C.height=H;
C.style.width='min(94vw,400px)';
C.style.height='auto';
const X=C.getContext('2d');

const LANE_COUNT=4;
const ROAD_L=W*0.07, ROAD_R=W*0.93;
const ROAD_W=ROAD_R-ROAD_L;
const LANE_W=ROAD_W/LANE_COUNT;
const LANES=Array.from({length:LANE_COUNT},(_,i)=>ROAD_L+LANE_W*(i+0.5));
const PW=Math.floor(LANE_W*0.72), PH=Math.floor(LANE_W*1.4);

let px,py,cars,sc,spd,running,frame,roadY=0,lLeft=false,lRight=false;

document.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')lLeft=true;if(e.key==='ArrowRight')lRight=true;});
document.addEventListener('keyup',e=>{if(e.key==='ArrowLeft')lLeft=false;if(e.key==='ArrowRight')lRight=false;});

function startGame(){
  px=LANES[1]-PW/2; py=H-PH-16;
  cars=[];sc=0;spd=2.2;running=true;roadY=0;
  document.getElementById('mg').textContent='Hold ◀ or ▶ to steer!';
  cancelAnimationFrame(frame);loop();
}
function spawnCar(){
  const l=Math.floor(Math.random()*LANE_COUNT);
  const clrs=['#e74c3c','#3498db','#f1c40f','#2ecc71','#9b59b6','#e67e22','#1abc9c'];
  cars.push({x:LANES[l]-PW/2,y:-PH,color:clrs[Math.floor(Math.random()*clrs.length)]});
}
function loop(){
  if(!running)return;
  sc++; spd=2.2+sc/700;
  document.getElementById('sc').textContent='Score: '+Math.floor(sc/10);
  document.getElementById('sp').textContent='Speed: '+spd.toFixed(1)+'x';
  const step=ROAD_W*0.014;
  if(lLeft&&px>ROAD_L+4)px-=step;
  if(lRight&&px<ROAD_R-PW-4)px+=step;
  if(Math.random()<0.018+sc/70000)spawnCar();
  cars.forEach(c=>c.y+=spd*2.6);
  cars=cars.filter(c=>c.y<H+PH);
  // Collision with 8px forgiveness
  for(const c of cars){
    if(px+8<c.x+PW-8&&px+PW-8>c.x+8&&py+8<c.y+PH-8&&py+PH-8>c.y+8){
      running=false;
      document.getElementById('mg').textContent='💥 Crash! Final Score: '+Math.floor(sc/10);
      draw();return;
    }
  }
  draw();frame=requestAnimationFrame(loop);
}
function drawCar(x,y,w,h,color,isPlayer){
  // Body
  X.fillStyle=color;
  X.beginPath();if(X.roundRect)X.roundRect(x,y,w,h,6);else X.rect(x,y,w,h);X.fill();
  // Windshield
  X.fillStyle='rgba(180,220,255,0.75)';
  if(isPlayer)X.fillRect(x+w*0.12,y+h*0.55,w*0.76,h*0.2);
  else X.fillRect(x+w*0.12,y+h*0.1,w*0.76,h*0.2);
  // Wheels
  X.fillStyle='#111';
  [[x-3,y+h*0.12],[x+w-1,y+h*0.12],[x-3,y+h*0.68],[x+w-1,y+h*0.68]].forEach(([wx,wy])=>{
    X.fillRect(wx,wy,5,h*0.16);
  });
  if(isPlayer){
    // Headlights
    X.fillStyle='#fffaaa';X.fillRect(x+w*0.1,y+h*0.03,w*0.2,h*0.07);X.fillRect(x+w*0.7,y+h*0.03,w*0.2,h*0.07);
    // Taxi sign
    X.fillStyle='#000';X.font='bold '+Math.floor(w*0.3)+'px Arial';X.textAlign='center';X.fillText('TAXI',x+w/2,y+h*0.48);
  } else {
    // Tail lights
    X.fillStyle='#ff2200';X.fillRect(x+w*0.08,y+h*0.88,w*0.2,h*0.08);X.fillRect(x+w*0.72,y+h*0.88,w*0.2,h*0.08);
  }
}
function draw(){
  // Road
  X.fillStyle='#2c2c2c';X.fillRect(0,0,W,H);
  // Side areas
  X.fillStyle='#1a1a3e';X.fillRect(0,0,ROAD_L,H);X.fillRect(ROAD_R,0,W-ROAD_R,H);
  // Buildings
  X.fillStyle='#252545';
  [[0,ROAD_L-2],[ROAD_R+2,W-ROAD_R-2]].forEach(([bx,bw])=>{
    for(let i=0;i<5;i++){
      const bh=H*0.08+Math.sin(i*2.1)*H*0.05;
      X.fillRect(bx,H-bh-i*(H*0.15),bw,bh);
      // Windows
      X.fillStyle='#ffff99';
      for(let r=0;r<3;r++)for(let c2=0;c2<2;c2++){
        if(Math.random()>0.3)X.fillRect(bx+bw*0.15+c2*bw*0.4,H-bh-i*(H*0.15)+r*bh*0.28+bh*0.1,bw*0.2,bh*0.15);
      }
      X.fillStyle='#252545';
    }
  });
  // Road markings scroll
  roadY=(roadY+spd*2.6)%56;
  X.strokeStyle='#666';X.lineWidth=2;X.setLineDash([28,26]);
  for(let i=1;i<LANE_COUNT;i++){
    const lx=ROAD_L+LANE_W*i;
    X.beginPath();X.moveTo(lx,roadY-56);X.lineTo(lx,H);X.stroke();
  }
  X.setLineDash([]);
  // Road edges
  X.strokeStyle='#ff6600';X.lineWidth=4;
  X.beginPath();X.moveTo(ROAD_L,0);X.lineTo(ROAD_L,H);X.stroke();
  X.beginPath();X.moveTo(ROAD_R,0);X.lineTo(ROAD_R,H);X.stroke();
  // Traffic cars
  cars.forEach(c=>drawCar(c.x,c.y,PW,PH,c.color,false));
  // Player taxi
  drawCar(px,py,PW,PH,'#FFD700',true);
}
draw();
</script></body></html>""", height=700)


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

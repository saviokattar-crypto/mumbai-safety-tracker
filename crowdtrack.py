import streamlit as st
import requests
from datetime import datetime
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim
from streamlit_autorefresh import st_autorefresh

# 1. UI & PERFORMANCE SETUP
st.set_page_config(page_title="Mumbai Survival Tracker", page_icon="🚉")
st_autorefresh(interval=60000, key="datarefresh")

# --- URL-BASED PERSONALIZATION ---
query_params = st.query_params
user_type = query_params.get("user", "").lower()

is_dhanashri = user_type == "dhanashri"
is_mom = user_type == "mom"
is_personal = is_dhanashri or is_mom

if is_dhanashri:
    app_caption = "For Dhanashri"
elif is_mom:
    app_caption = "For Mom"
else:
    app_caption = "For All Mumbaikars"
# ---------------------------------

@st.cache_data(ttl=300)
def get_cached_address(lat, lon):
    geolocator = Nominatim(user_agent="mumbai_survival_savio")
    try:
        location_obj = geolocator.reverse(f"{lat}, {lon}", language='en', timeout=5)
        raw_address = location_obj.address
        address_parts = raw_address.split(',')
        short_name = address_parts[1].strip() if len(address_parts) > 1 else address_parts[0]
        return raw_address, short_name
    except:
        return "📍 Location Signal Weak (Mumbai)", "Mumbai"

@st.cache_data(ttl=600)
def get_cached_weather(lat, lon):
    try:
        res = requests.get(f"https://wttr.in/{lat},{lon}?format=%C+%t&m", timeout=5)
        if res.status_code == 200: return res.text
    except:
        pass
    return "Smoke +32°C"

st.title("🚉 Mumbai Survival Tracker")
st.caption(f"Engineered by Savio | {app_caption}")

# 2. FULL STATION DATABASE
western_line = ["Churchgate", "Marine Lines", "Charni Road", "Grant Road", "Mumbai Central", "Mahalakshmi", 
                "Lower Parel", "Prabhadevi", "Dadar", "Matunga Road", "Mahim", "Bandra", "Khar Road", "Santa Cruz", 
                "Vile Parle", "Andheri", "Jogeshwari", "Ram Mandir", "Goregaon", "Malad", "Kandivali", "Borivali", "Dahisar",
                "Mira Road", "Bhayandar", "Naigaon", "Vasai Road", "Nallasopara", "Virar", "Vaitarna", "Saphale", 
                "Kelve Road", "Palghar", "Umroli", "Boisar", "Vangaon", "Dahanu Road"]

central_line = ["CSMT", "Masjid", "Sandhurst Road", "Byculla", "Chinchpokli", "Currey Road", "Parel", "Dadar", "Matunga",
                "Sion", "Kurla", "Vidyavihar", "Ghatkopar", "Vikhroli", "Kanjurmarg", "Bhandup", "Nahur", "Mulund", "Thane",
                "Kalwa", "Mumbra", "Diva", "Kopar", "Dombivli", "Thakurli", "Kalyan", "Vitthalwadi", "Ulhasnagar", "Ambernath", 
                "Badlapur", "Vangani", "Shelu", "Neral", "Bhivpuri Road", "Karjat", "Palasdari", "Kelavli", "Dolavli", "Lowjee", 
                "Khopoli", "Shahad", "Ambivli", "Titwala", "Khadavli", "Vasind", "Asangaon", "Atgaon", "Thansit", "Khardi", 
                "Umbarmali", "Kasara"]

harbour_line = ["Dockyard Road", "Reay Road", "Cotton Green", "Sewri", "Vadala Road", "GTB Nagar", "Chunabhatti", 
                "Kurla", "Tilak Nagar", "Chembur", "Govandi", "Mankhurd", "Vashi", "Sanpada", "Juinagar", "Nerul", 
                "Seawoods", "Belapur", "Kharghar", "Mansarovar", "Khandeshwar", "Panvel", "King's Circle", "Mahim", 
                "Bandra", "Khar Road", "Santa Cruz", "Vile Parle", "Andheri", "Jogeshwari", "Ram Mandir", "Goregaon"]

mumbai_stations = sorted(list(set(western_line + central_line + harbour_line)))

# 3. JOURNEY SELECTION
st.subheader("🗺️ Journey Selection")
def get_index(station_list, default_name):
    try: return station_list.index(default_name)
    except ValueError: return 0

from_st = st.selectbox("From Station", mumbai_stations, index=get_index(mumbai_stations, "Bhandup"))
to_st = st.selectbox("To Station", mumbai_stations, index=get_index(mumbai_stations, "Bandra"))
check_crowd_st = st.selectbox("Monitor Crowd At:", mumbai_stations, index=get_index(mumbai_stations, "Dadar"))

# 4. LIVE DATA FETCHING
st.sidebar.markdown("### 🛰️ Location Control")
if st.sidebar.button("📍 Click to Activate GPS"):
    st.rerun()

loc = get_geolocation()
now = datetime.now()
current_time = now.strftime("%H:%M")

# --- SAFETY CHECK FOR LOCATION ---
if loc and 'coords' in loc:
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
    address_full, address_short = get_cached_address(lat, lon)
    weather_data = get_cached_weather(lat, lon)

    st.divider()
    st.subheader(f"📍 Current Status: {address_short}")
    
    c1, c2 = st.columns(2)
    with c1: st.metric("🌡️ Weather", weather_data)
    with c2:
        next_train = (5 - (now.minute % 5))
        st.metric("🚆 Next Train Approx.", f"{next_train} mins", delta="Live")
    st.markdown(f"**Full Location:** {address_full}")

    # 5. CROWD TRACKING
    st.divider()
    st.subheader(f"📊 Crowd Status: {check_crowd_st}")
    
    crowd_pct = 35 
    is_peak = ("07:30" <= current_time <= "09:30") or ("17:00" <= current_time <= "19:30")
    if is_peak: crowd_pct += 45
    if "Rain" in weather_data or "Storm" in weather_data: crowd_pct += 15
    crowd_pct = min(crowd_pct, 100)

    st.write(f"**Estimated Crowd Density:** {crowd_pct}%")
    st.progress(crowd_pct / 100)

    if crowd_pct >= 80:
        st.error(f"🔴 EXTREME RUSH at {check_crowd_st}")
    elif crowd_pct >= 50:
        st.warning(f"🟠 HEAVY RUSH at {check_crowd_st}")
    else:
        st.success(f"🟢 COMFORTABLE ZONE at {check_crowd_st}")

    # 6. CONNECTIVITY
    st.subheader("🛺 Connectivity")
    col1, col2 = st.columns(2)
    col1.link_button("🚗 Uber", "https://m.uber.com/ul/?action=setPickup&pickup=my_location", use_container_width=True)
    col2.link_button("🚕 Ola", "https://book.olacabs.com/", use_container_width=True)

    # 7. EMERGENCY SOS
    st.sidebar.error("⚠️ EMERGENCY SOS Feeling unsafe")
    map_link = f"https://www.google.com/maps?q={lat},{lon}"
    msg = f"I%20feel%20unsafe.%20Crowd%20is%20at%20{crowd_pct}%.%20My%20location:%20{map_link}"
    
    # 7a. PERSONAL SOS BUTTONS
    if is_personal:
        st.sidebar.link_button("🚨 Alert Savio", f"https://wa.me/917506397365?text={msg}", use_container_width=True)
        
        if is_dhanashri:
            st.sidebar.link_button("🚨 Alert Mom", f"https://wa.me/91XXXXXXXXXX?text={msg}", use_container_width=True)
            st.sidebar.link_button("🚨 Alert Dad", f"https://wa.me/91XXXXXXXXXX?text={msg}", use_container_width=True)
        elif is_mom:
            st.sidebar.link_button("🚨 Alert Dad", f"https://wa.me/917738005302?text={msg}", use_container_width=True)
            st.sidebar.link_button("🚨 Alert Son (Savio)", f"https://wa.me/917506397365?text={msg}", use_container_width=True)
    
    # 7b. CUSTOM SOS FOR NORMAL PEOPLE
    else:
        st.sidebar.divider()
        st.sidebar.write("👤 **Emergency Contact Memory**")
        if 'custom_name' not in st.session_state: st.session_state.custom_name = "Near One"
        if 'custom_no' not in st.session_state: st.session_state.custom_no = "91"
        st.session_state.custom_name = st.sidebar.text_input("Contact Name", st.session_state.custom_name)
        st.session_state.custom_no = st.sidebar.text_input("WhatsApp No (with 91)", st.session_state.custom_no)
        if len(st.session_state.custom_no) > 10:
            st.sidebar.link_button(f"🚨 Alert {st.session_state.custom_name}", f"https://wa.me/{st.session_state.custom_no}?text={msg}", use_container_width=True)

# --- IF LOCATION IS NOT READY YET ---
else:
    st.info("🛰️ **Searching for GPS...**")
    st.warning("If no popup appeared, please click the **📍 Activate GPS** button in the sidebar.")
    st.write("Also check if Location is enabled in your phone's browser settings (Lock 🔒 icon in address bar).")

# 8. JOURNEY REMINDER
st.divider()
if is_dhanashri:
    st.info("✨ **Safe Journey!** Remember to check your surroundings and keep your bag in front. Stay safe, Dhanashri!")
elif is_mom:
    st.info("✨ **Safe Journey, Mom!** Please be careful while boarding the train. Call Savio if you need anything!")
else:
    st.info("✨ **Safe Journey!** Keep your belongings safe and stay alert while boarding.")

st.caption(f"Last sync: {current_time} | Built with ❤️ by Savio")

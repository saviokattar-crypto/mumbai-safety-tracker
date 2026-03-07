import streamlit as st
import requests
from datetime import datetime
from streamlit_js_eval import get_geolocation
from geopy.geocoders import Nominatim
from streamlit_autorefresh import st_autorefresh

# 1. UI SETUP & AUTO-REFRESH (Updates every 2 mins)
st.set_page_config(page_title="Smart Survival Tracker", page_icon="🚉")
st_autorefresh(interval=120000, key="datarefresh")

st.title("🚉 Smart Survival Tracker")
st.write("Custom Built by Savio for Dhanashri")

# 2. GPS & TIME LOGIC
loc = get_geolocation()
now = datetime.now()
current_time = now.strftime("%H:%M")

contacts = {
    "Savio": "917506397365",
    "Dad": "91XXXXXXXXXX",
    "Mom": "91XXXXXXXXXX"
}

if loc:
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
    
    # ADDRESS LOOKUP - High Priority for Mumbai Areas
    geolocator = Nominatim(user_agent="mumbai_safety_tracker_savio")
    try:
        # We try to get the most specific neighborhood name (like Bhattipada)
        location_obj = geolocator.reverse(f"{lat}, {lon}", language='en', timeout=10)
        address_parts = location_obj.raw.get('address', {})
        # Prioritize suburb/neighbourhood for local Mumbai feel
        place_name = address_parts.get('suburb') or address_parts.get('neighbourhood') or address_parts.get('city_district') or "Mumbai"
        address_name = f"{place_name}, Mumbai"
    except Exception:
        address_name = "Detecting Precise Neighborhood..."

    # WEATHER FETCH - Forced to Celsius with '&m'
    try:
        # Added &m for Metric/Celsius units
        weather_res = requests.get(f"https://wttr.in/{lat},{lon}?format=%C+%t&m")
        weather_data = weather_res.text
    except:
        weather_data = "Weather Unavailable"
    
    st.info(f"📍 **Currently At:** {address_name}")
    st.write(f"**Conditions:** {weather_data}")

    # 2.5 DYNAMIC ROUTE DISPLAY
    # Morning: Home to College | Evening: College to Home
    if "05:00" <= current_time <= "12:00":
        route_display = "🏠 Bhandup ➔ Dadar ➔ Bandra 🎓"
        status_msg = "Morning commute to college. Have a great day!"
    else:
        route_display = "🎓 Bandra ➔ Dadar ➔ Bhandup 🏠"
        status_msg = "Heading back home. Stay alert at Dadar!"

    st.subheader(f"Route: {route_display}")
    st.write(f"_{status_msg}_")

    # 3. CROWD & SOS ENGINE
    is_peak = ("07:30" <= current_time <= "09:30") or ("17:00" <= current_time <= "19:30")
    is_rainy = any(word in weather_data.lower() for word in ["rain", "drizzle", "storm"])

    st.divider()
    
    if is_peak and is_rainy:
        st.error("🛑 STATUS: ULTIMATE DANGER")
        st.metric("Crowd Level", "100%", delta="Warzone", delta_color="inverse")
    elif is_peak:
        st.warning("🟠 STATUS: PEAK RUSH")
        st.metric("Crowd Level", "85%", delta="Heavy")
    else:
        st.success("🟢 STATUS: CLEAR ZONE")
        st.metric("Crowd Level", "30%", delta="Safe")

    # 4. THE SOS & SECURITY ENGINE (Sidebar)
    st.sidebar.error("⚠️ SECURITY ALERT")
    if st.sidebar.button("🚨 I FEEL UNSAFE (Send Location)", use_container_width=True):
        map_link = f"https://www.google.com/maps?q={lat},{lon}"
        secure_msg = f"I%20feel%20unsafe.%20My%20current%20location%20is:%20{map_link}"
        for name, num in contacts.items():
            st.sidebar.link_button(f"🚨 Alert {name}", f"https://wa.me/{num}?text={secure_msg}", use_container_width=True)

    if is_peak or is_rainy:
        st.sidebar.divider()
        st.sidebar.info("🚉 Crowd Delay Alert")
        crowd_msg = "Hey,%20I'm%20stuck%20in%20the%20rush%20and%20might%20be%20late."
        for name, num in contacts.items():
            st.sidebar.link_button(f"📲 WhatsApp {name}", f"https://wa.me/{num}?text={crowd_msg}", use_container_width=True)

st.divider()
st.caption(f"Last sync: {current_time} | Built with ❤️ by Savio")

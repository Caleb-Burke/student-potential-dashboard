
import streamlit as st
import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
from branca.colormap import linear
from neighborhoods import neighborhood_tracts

@st.cache_data
def load_data():
    tracts = gpd.read_file("data/tl_2022_39_tract.shp")
    under_18 = pd.read_csv("data/Cinci ,18 by tract.csv")
    low_income = pd.read_csv("data/Cinci less the 50K by tract -percent.csv")
    white_pop = pd.read_csv("data/Cinci white by tract - percent.csv")

    for df in [under_18, low_income, white_pop]:
        df['GeoID'] = df['GeoID'].astype(str)
    tracts['GEOID'] = tracts['GEOID'].astype(str)

    merged = tracts.merge(
        under_18.merge(low_income, on='GeoID').merge(white_pop, on='GeoID'),
        left_on='GEOID', right_on='GeoID'
    )

    merged['People < 18 Years Old'] = pd.to_numeric(merged['People < 18 Years Old'], errors='coerce')
    merged['Percent HHs with Income < $50,000'] = pd.to_numeric(merged['Percent HHs with Income < $50,000'], errors='coerce')
    merged['Percent White Population'] = pd.to_numeric(merged['Percent White Population'], errors='coerce')

    merged['potential_students'] = merged['People < 18 Years Old'] * (merged['Percent HHs with Income < $50,000'] / 100) * 0.2
    merged['potential_white_students'] = merged['potential_students'] * (merged['Percent White Population'] / 100)
    merged['potential_non_white_students'] = merged['potential_students'] * (1 - merged['Percent White Population'] / 100)

    merged = merged.to_crs(epsg=4326)
    merged['centroid'] = merged.geometry.centroid
    merged['latlon'] = merged['centroid'].apply(lambda x: (x.y, x.x))

    tract_mapping = pd.DataFrame([
        {'Neighborhood': n, 'Census Tract': t}
        for n, tracts in neighborhood_tracts.items()
        for t in tracts
    ])
    tract_mapping['Census Tract'] = tract_mapping['Census Tract'].astype(str)
    merged = pd.merge(merged, tract_mapping, left_on='NAME', right_on='Census Tract', how='left')
    merged['Neighborhood'] = merged['Neighborhood'].fillna('Unassigned')
    return merged

def geocode_address(address):
    geolocator = Nominatim(user_agent="student_mapper")
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    return None

st.title("📍 Potential Student Mapper")

address = st.text_input("Enter an address (e.g., 123 Main St, Cincinnati OH)")
radius = st.slider("Select distance radius (miles)", min_value=1, max_value=20, value=3)

map_style = st.radio("Map Style", ["Heatmap", "Satellite"])
view_mode = st.radio("View By", ["Neighborhood", "Tract"])

data = load_data()

if address:
    location = geocode_address(address)
    if location:
        st.success(f"Geocoded location: {location}")
        data['distance_miles'] = data['latlon'].apply(lambda x: geodesic(location, x).miles)
        within = data[data['distance_miles'] <= radius].copy()
    else:
        st.error("Could not geocode address. Showing all data.")
        within = data.copy()
        location = [39.1031, -84.5120]
else:
    st.info("No address entered. Showing all data.")
    within = data.copy()
    location = [39.1031, -84.5120]

if view_mode == "Neighborhood":
    geo = within.dissolve(by='Neighborhood', aggfunc='sum').reset_index()
else:
    geo = within.copy()

# Map setup
if map_style == "Satellite":
    tiles = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    attr = "Tiles © Esri"
else:
    tiles = None
    attr = None

m = folium.Map(location=location, zoom_start=12, tiles=tiles, attr=attr)

if map_style == "Heatmap":
    colormap = linear.OrRd_09.scale(geo["potential_students"].min(), geo["potential_students"].max())
    colormap.caption = "Potential Students"
    colormap.add_to(m)

for _, row in geo.iterrows():
    geojson = folium.GeoJson(
        data=row["geometry"].__geo_interface__,
        style_function=lambda feature, count=row["potential_students"]: {
            "fillColor": colormap(count) if map_style == "Heatmap" else "#3388ff",
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.7
        },
        tooltip=f"{row['Neighborhood'] if 'Neighborhood' in row else row['NAME']}: {int(row['potential_students'])} potential students"
    )
    geojson.add_to(m)

if address and location:
    folium.Marker(location, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(m)

st_folium(m, width=700)

# Table output
st.subheader("Summary Table")
numeric_cols = ['potential_students', 'potential_white_students', 'potential_non_white_students']

if view_mode == "Neighborhood":
    summary = geo[['Neighborhood'] + numeric_cols].copy()
else:
    summary = geo[['NAME'] + numeric_cols].copy()

summary[numeric_cols] = summary[numeric_cols].round(0).astype(int)
st.dataframe(summary)

if st.checkbox("Show full city neighborhood summary"):
    full = data.dissolve(by="Neighborhood", aggfunc="sum").reset_index()
    full[numeric_cols] = full[numeric_cols].round(0).astype(int)
    st.dataframe(full[['Neighborhood'] + numeric_cols])

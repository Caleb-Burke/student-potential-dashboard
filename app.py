
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

map_style = st.radio("Map Style", ["Heatmap", "Street View"])  # simplified naming
view_mode = st.radio("View By", ["Neighborhood", "Tract"])
color_metric = st.radio("Color by", ["Total Students", "White Students", "Non-White Students"])

color_column_map = {
    "Total Students": "potential_students",
    "White Students": "potential_white_students",
    "Non-White Students": "potential_non_white_students"
}
selected_column = color_column_map[color_metric]

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
    # Dissolve only numerical columns and geometry
    group_fields = ['Neighborhood', 'geometry']
    numeric_cols = ['potential_students', 'potential_white_students', 'potential_non_white_students']
    geo = within.groupby('Neighborhood').agg({**{col: 'sum' for col in numeric_cols}, 'geometry': 'first'}).reset_index()
else:
    geo = within.copy()

# Set base map
tiles = "cartodbpositron" if map_style == "Street View" else None
m = folium.Map(location=location, zoom_start=12, tiles=tiles)

# Apply color scale
colormap = linear.OrRd_09.scale(geo[selected_column].min(), geo[selected_column].max())
colormap.caption = color_metric
colormap.add_to(m)

for _, row in geo.iterrows():
    value = row[selected_column]
    geom = row["geometry"]
    label = row.get("Neighborhood", row.get("NAME", "Unknown"))
    geojson = folium.GeoJson(
        data=geom.__geo_interface__,
        style_function=lambda feature, count=value: {
            "fillColor": colormap(count),
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.7
        },
        tooltip=f"{label}: {int(value)} {color_metric.lower()}"
    )
    geojson.add_to(m)

if address and location:
    folium.Marker(location, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(m)

st_folium(m, width=700)

# Table output
st.subheader("Summary Table")
table_cols = ['potential_students', 'potential_white_students', 'potential_non_white_students']
if view_mode == "Neighborhood":
    summary = geo[['Neighborhood'] + table_cols].copy()
else:
    summary = geo[['NAME'] + table_cols].copy()

summary[table_cols] = summary[table_cols].round(0).astype(int)
st.dataframe(summary)

if st.checkbox("Show full city neighborhood summary"):
    full = data.groupby("Neighborhood").agg({col: 'sum' for col in table_cols}).reset_index()
    full[table_cols] = full[table_cols].round(0).astype(int)
    st.dataframe(full)

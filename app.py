
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
    merged['Neighborhood'] = merged['Neighborhood'].fillna(merged['NAME'])  # fallback to tract name
    return merged

def geocode_address(address):
    geolocator = Nominatim(user_agent="student_mapper")
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    return None

# Layout
st.set_page_config(layout="wide")
st.title("📍 Potential Student Mapper")

# Sidebar and input
col1, col2 = st.columns([3, 1])
with col2:
    address = st.text_input("Address", "695 Gest St, Cincinnati OH")
    radius = st.slider("Distance (miles)", 1, 20, 3)
    view_mode = st.radio("View By", ["Neighborhood", "Tract"])
    color_metric = st.radio("Color by", ["Total Students", "White Students", "Non-White Students"])
    overlay_heatmap = st.checkbox("Overlay heatmap", value=True)

# Load and process
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
        st.toast(f"Geocoded: {location}", icon="📍")
        data['distance_miles'] = data['latlon'].apply(lambda x: geodesic(location, x).miles)
        within = data[data['distance_miles'] <= radius].copy()
    else:
        st.warning("Could not geocode address. Showing all data.")
        location = [39.1031, -84.5120]
        within = data.copy()
else:
    location = [39.1031, -84.5120]
    within = data.copy()

# Aggregate
if view_mode == "Neighborhood":
    grouped = within.groupby('Neighborhood')[
        ['potential_students', 'potential_white_students', 'potential_non_white_students']
    ].sum().reset_index()
else:
    grouped = within[['NAME', 'potential_students', 'potential_white_students', 'potential_non_white_students']]
    grouped = grouped.rename(columns={'NAME': 'Neighborhood'})

grouped = grouped.rename(columns={
    'Neighborhood': 'Neighborhood',
    'potential_students': 'Total',
    'potential_white_students': 'White',
    'potential_non_white_students': 'Non-White'
})
grouped[['Total', 'White', 'Non-White']] = grouped[['Total', 'White', 'Non-White']].round(0).astype(int)

# Display metrics side-by-side
col1, col2, col3 = st.columns(3)
col1.metric("Total Potential Students", f"{int(grouped['Total'].sum()):,}")
col2.metric("White", f"{int(grouped['White'].sum()):,}")
col3.metric("Non-White", f"{int(grouped['Non-White'].sum()):,}")

# Map and controls
st.subheader("Map View")
map_col, control_col = st.columns([4, 1])
tiles = "cartodbpositron"
m = folium.Map(location=location, zoom_start=12, tiles=tiles)

if overlay_heatmap:
    colormap = linear.OrRd_09.scale(within[selected_column].min(), within[selected_column].max())
    colormap.caption = color_metric
    colormap.add_to(m)

for _, row in within.iterrows():
    label = row['Neighborhood']
    value = row[selected_column]
    color = colormap(value) if overlay_heatmap else "#3388ff"
    geojson = folium.GeoJson(
        data=row["geometry"].__geo_interface__,
        style_function=lambda feature, count=value: {
            "fillColor": color,
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.7 if overlay_heatmap else 0.2
        },
        tooltip=f"{label}: {int(value)} {color_metric.lower()}"
    )
    geojson.add_to(m)

if address and location:
    folium.Marker(location, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(m)

with map_col:
    st_folium(m, width=900, height=600)

# Data table
st.subheader("Summary Table")
st.dataframe(grouped, use_container_width=True)

if st.checkbox("Show full city summary"):
    full_group = data.groupby('Neighborhood')[[
        'potential_students', 'potential_white_students', 'potential_non_white_students'
    ]].sum().reset_index().rename(columns={
        'Neighborhood': 'Neighborhood',
        'potential_students': 'Total',
        'potential_white_students': 'White',
        'potential_non_white_students': 'Non-White'
    })
    full_group[['Total', 'White', 'Non-White']] = full_group[['Total', 'White', 'Non-White']].round(0).astype(int)
    st.dataframe(full_group, use_container_width=True)


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
    merged = pd.merge(merged, tract_mapping, left_on='NAME', right_on='Census Tract', how='left')
    merged['Neighborhood'] = merged['Neighborhood'].fillna(merged['NAME'])
    return merged

def geocode_address(address):
    geolocator = Nominatim(user_agent="student_mapper")
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    return None

# Layout
st.set_page_config(layout="wide")
st.title("📍 Potential Student Mapper by Neighborhood")

col_main, col_side = st.columns([4, 1])
with col_side:
    address = st.text_input("Enter an address (e.g., 123 Main St, Cincinnati OH)")
    radius = st.slider("Distance (miles)", 1, 20, 3)
    view_mode = st.radio("View By", ["Neighborhood", "Tract"])
    color_metric = st.radio("Color by", ["Total Students", "White Students", "Non-White Students"])
    overlay_heatmap = st.checkbox("Overlay heatmap", value=True)

# Setup
color_column_map = {
    "Total Students": "potential_students",
    "White Students": "potential_white_students",
    "Non-White Students": "potential_non_white_students"
}
selected_column = color_column_map[color_metric]
data = load_data()

# Filter by distance
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

# Aggregate and summarize
if view_mode == "Neighborhood":
    aggregated = within.dissolve(by="Neighborhood", aggfunc="sum", as_index=False)
else:
    aggregated = within.copy()
aggregated = aggregated[['Neighborhood', 'geometry', 'potential_students', 'potential_white_students', 'potential_non_white_students']]
aggregated = aggregated.rename(columns={
    'potential_students': 'Total',
    'potential_white_students': 'White',
    'potential_non_white_students': 'Non-White'
})
aggregated[['Total', 'White', 'Non-White']] = aggregated[['Total', 'White', 'Non-White']].round(0).astype(int)

# Top-level stats
with col_main:
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Potential Students", f"{int(aggregated['Total'].sum()):,}")
    col2.metric("White", f"{int(aggregated['White'].sum()):,}")
    col3.metric("Non-White", f"{int(aggregated['Non-White'].sum()):,}")

    # Map
    tiles = "cartodbpositron"
    m = folium.Map(location=location, zoom_start=12, tiles=tiles)

    if overlay_heatmap:
        colormap = linear.OrRd_09.scale(aggregated[selected_column].min(), aggregated[selected_column].max())
        colormap.caption = color_metric
        colormap.add_to(m)

    for _, row in aggregated.iterrows():
        value = row[selected_column]
        label = row['Neighborhood']
        geojson = folium.GeoJson(
            data=row["geometry"].__geo_interface__,
            style_function=lambda feature, count=value: {
                "fillColor": colormap(count) if overlay_heatmap else "#3388ff",
                "color": "black",
                "weight": 0.5,
                "fillOpacity": 0.7 if overlay_heatmap else 0.2
            },
            tooltip=f"{label}: {int(value)} {color_metric.lower()}"
        )
        geojson.add_to(m)

    if address and location:
        folium.Marker(location, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(m)

    st_folium(m, width=1100, height=600)

# Table
st.subheader("Summary Table")
display_df = aggregated[['Neighborhood', 'Total', 'White', 'Non-White']].sort_values(by='Total', ascending=False).reset_index(drop=True)
st.dataframe(display_df, use_container_width=True)

if st.checkbox("Show full city summary"):
    full_group = data.groupby('Neighborhood')[[
        'potential_students', 'potential_white_students', 'potential_non_white_students'
    ]].sum().reset_index().rename(columns={
        'potential_students': 'Total',
        'potential_white_students': 'White',
        'potential_non_white_students': 'Non-White'
    })
    full_group[['Total', 'White', 'Non-White']] = full_group[['Total', 'White', 'Non-White']].round(0).astype(int)
    full_group = full_group.sort_values(by="Total", ascending=False)
    st.dataframe(full_group, use_container_width=True)

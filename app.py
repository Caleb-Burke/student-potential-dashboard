
import streamlit as st
import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
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
    merged['Neighborhood'] = merged['Neighborhood'].fillna('Unassigned')
    return merged

def geocode_address(address):
    geolocator = Nominatim(user_agent="student_mapper")
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    return None

st.title("📍 Potential Student Mapper by Neighborhood")

address = st.text_input("Enter an address (e.g., 123 Main St, Cincinnati OH)")
radius = st.slider("Select distance radius (miles)", min_value=1, max_value=20, value=3)

if address:
    location = geocode_address(address)
    if location:
        st.success(f"Geocoded location: {location}")

        data = load_data()
        data['distance_miles'] = data['latlon'].apply(lambda x: geodesic(location, x).miles)
        within = data[data['distance_miles'] <= radius].copy()

        grouped = within.groupby('Neighborhood')[[
            'potential_students', 'potential_white_students', 'potential_non_white_students'
        ]].sum().reset_index().sort_values(by='potential_students', ascending=False)

        st.metric("Total Potential Students", f"{int(grouped['potential_students'].sum()):,}")
        st.metric("White", f"{int(grouped['potential_white_students'].sum()):,}")
        st.metric("Non-White", f"{int(grouped['potential_non_white_students'].sum()):,}")

        m = folium.Map(location=location, zoom_start=12)
        folium.Marker(location, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(m)
        for _, row in within.iterrows():
            sim_geo = gpd.GeoSeries(row['geometry']).simplify(tolerance=0.001)
            folium.GeoJson(sim_geo.__geo_interface__,
                           tooltip=f"{row['Neighborhood']} (Tract {row['NAME']}): {int(row['potential_students'])}").add_to(m)
        st_folium(m, width=700)

        st.subheader("Neighborhood Summary")
        numeric_cols = ['potential_students', 'potential_white_students', 'potential_non_white_students']
        grouped[numeric_cols] = grouped[numeric_cols].round(0).astype(int)
        st.dataframe(grouped)

        if st.checkbox("Show full city neighborhood summary"):
            full_data = load_data()
            full_grouped = full_data.groupby('Neighborhood')[numeric_cols].sum().reset_index()
            full_grouped[numeric_cols] = full_grouped[numeric_cols].round(0).astype(int)
            st.dataframe(full_grouped)

    else:
        st.error("Could not geocode address. Please check the input.")

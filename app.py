
import streamlit as st
import geopandas as gpd
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import folium
from streamlit_folium import st_folium
from branca.colormap import linear
from neighborhoods import neighborhood_tracts

# ---------- Data Loading ----------
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

    mapping = pd.DataFrame([(n, t) for n, tracts in neighborhood_tracts.items() for t in tracts],
                           columns=['Neighborhood', 'Census Tract'])
    merged = merged.merge(mapping, left_on='NAME', right_on='Census Tract', how='left')
    merged['Neighborhood'] = merged['Neighborhood'].fillna(merged['NAME'])
    return merged

def geocode_address(address):
    try:
        geolocator = Nominatim(user_agent="student_mapper", timeout=3)
        loc = geolocator.geocode(address)
        return (loc.latitude, loc.longitude) if loc else None
    except:
        return None

# ---------- UI ----------
st.set_page_config(layout="wide")
st.title("📍 Potential Students in Hamilton County")

st.markdown("*Potential students = 20% of kids under 18 from households with less than $50,000 income.*")
st.markdown("**Source: 2020 Census**")

main_col, side_col = st.columns([4,1], gap="large")

with side_col:
    address = st.text_input("Address", "695 Gest St, Cincinnati OH")
    radius = st.slider("Radius (miles)", 1, 20, 3)
    view_mode = st.radio("View Mode", ["Neighborhood", "Tract"])
    color_metric = st.radio("Color Metric", ["Total Students", "White Students", "Non-White Students"])
    overlay_heatmap = st.checkbox("Overlay heatmap", True)

metric_original = {
    "Total Students": "potential_students",
    "White Students": "potential_white_students",
    "Non-White Students": "potential_non_white_students"
}
metric_display = {
    "Total Students": "Total",
    "White Students": "White",
    "Non-White Students": "Non-White"
}

data = load_data()

# ---------- Distance filter ----------
if address:
    loc = geocode_address(address)
    if loc:
        data['distance_miles'] = data['latlon'].apply(lambda x: geodesic(loc, x).miles)
        subset = data[data['distance_miles'] <= radius].copy()
    else:
        st.warning("Could not geocode address; showing all data.")
        loc = [39.1031, -84.5120]
        subset = data.copy()
else:
    loc = [39.1031, -84.5120]
    view_mode = 'Neighborhood'
    subset = data.copy()

# ---------- Aggregation ----------
num_cols = ['potential_students', 'potential_white_students', 'potential_non_white_students']
if view_mode == "Neighborhood":
    geometry_union = subset.groupby('Neighborhood')['geometry'].apply(lambda g: g.union_all())
    sums = subset.groupby('Neighborhood')[num_cols].sum()
    aggregated = gpd.GeoDataFrame(sums.join(geometry_union), geometry='geometry').reset_index()
else:
    aggregated = subset[['Neighborhood', 'geometry'] + num_cols].copy()

# rename for display
aggregated = aggregated.rename(columns={
    'potential_students': 'Total',
    'potential_white_students': 'White',
    'potential_non_white_students': 'Non-White'
})

# ---------- Metrics ----------
with main_col:
    m1, m2, m3 = st.columns(3)
    m1.metric("Total", f"{int(aggregated['Total'].sum()):,}")
    m2.metric("White", f"{int(aggregated['White'].sum()):,}")
    m3.metric("Non-White", f"{int(aggregated['Non-White'].sum()):,}")

    # ---------- Map ----------
    fmap = folium.Map(location=loc, zoom_start=12, tiles="cartodbpositron")

    if overlay_heatmap:
        value_col = metric_display[color_metric]
        cmap = linear.OrRd_09.scale(aggregated[value_col].min(), aggregated[value_col].max())
        cmap.caption = color_metric
        cmap.add_to(fmap)
    else:
        value_col = None

    for _, row in aggregated.iterrows():
        tooltip_value = row[metric_display[color_metric]]
        tooltip = f"{row['Neighborhood']}: {int(tooltip_value)} {color_metric.lower()}"
        style_fn = lambda feature, val=tooltip_value: {
            "fillColor": cmap(val) if overlay_heatmap else "#3388ff",
            "color": "black",
            "weight": 0.5,
            "fillOpacity": 0.7 if overlay_heatmap else 0.2
        }
        folium.GeoJson(row['geometry'].__geo_interface__, style_function=style_fn, tooltip=tooltip).add_to(fmap)

    if address and loc:
        folium.Marker(loc, tooltip="Entered Address", icon=folium.Icon(color='red')).add_to(fmap)

    st_folium(fmap, width=1100, height=600)

# ---------- Table ----------
st.subheader("Summary Table")
display_df = aggregated[['Neighborhood', 'Total', 'White', 'Non-White']].sort_values(by='Total', ascending=False).reset_index(drop=True)
st.dataframe(display_df.round(0).astype({'Total': int, 'White': int, 'Non-White': int}), use_container_width=True)

if st.checkbox("Show full city summary"):
    city = data.groupby('Neighborhood')[num_cols].sum().reset_index()
    city = city.rename(columns={
        'potential_students': 'Total',
        'potential_white_students': 'White',
        'potential_non_white_students': 'Non-White'
    }).sort_values(by='Total', ascending=False)
    st.dataframe(city, use_container_width=True)

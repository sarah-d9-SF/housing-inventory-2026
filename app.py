import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point
from pathlib import Path

# --- Page config ---
st.set_page_config(page_title="SF Housing Production", layout="wide")

# --- Neighborhood mapping: sub-districts → GeoJSON parent neighborhoods ---
NEIGHBORHOOD_MAP = {
    "East SoMa (EN)": "South of Market",
    "Western SoMa (EN)": "South of Market",
    "Central SoMa": "South of Market",
    "Mission (EN)": "Mission",
    "Showplace Square/Potrero Hill (EN)": "Potrero Hill",
    "Central Waterfront (EN)": "Potrero Hill",
    "Market and Octavia": "Hayes Valley",
    "Rincon Hill": "Financial District/South Beach",
    "Transit Center District": "Financial District/South Beach",
}

HERE = Path(__file__).parent

# --- Load data ---
@st.cache_data
def load_housing_data():
    df = pd.read_csv(HERE / "Housing_Production_-_2005-present_20260527.csv")

    # Map sub-districts to parent neighborhoods
    df["Neighborhood"] = df["Analysis Neighborhood"].replace(NEIGHBORHOOD_MAP)

    # Parse year from Latest Completion Date, fall back to BMR Reporting Year
    df["Year"] = pd.to_datetime(df["Latest Completion Date"], errors="coerce").dt.year
    df["Year"] = df["Year"].fillna(pd.to_numeric(df["BMR Reporting Year"], errors="coerce"))

    # Ensure numeric columns
    for col in ["Net Units Completed", "Market Rate", "Affordable Units",
                "ADU/Legalization Units", "Extremely Low Income",
                "Very Low Income", "Low Income", "Moderate Income"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df

@st.cache_data
def load_geodata():
    gdf = gpd.read_file(HERE / "Analysis_Neighborhoods_20260527.geojson")
    gdf = gdf[["nhood", "geometry"]].copy()
    return gdf

df = load_housing_data()
gdf = load_geodata()

# --- Sidebar ---
st.sidebar.title("Filters")
year_min, year_max = 2005, 2025
year_range = st.sidebar.slider("Completion Year Range", year_min, year_max, (year_min, year_max))

st.sidebar.markdown("---")
st.sidebar.markdown(
    "Click any neighborhood on the map to see its housing production breakdown."
)

# --- Filter and aggregate ---
filtered = df[
    (df["Year"] >= year_range[0]) & (df["Year"] <= year_range[1])
]

agg = (
    filtered.groupby("Neighborhood")
    .agg(
        Net_Units=("Net Units Completed", "sum"),
        Market_Rate=("Market Rate", "sum"),
        Affordable=("Affordable Units", "sum"),
        ADU=("ADU/Legalization Units", "sum"),
        Extremely_Low=("Extremely Low Income", "sum"),
        Very_Low=("Very Low Income", "sum"),
        Low=("Low Income", "sum"),
        Moderate=("Moderate Income", "sum"),
    )
    .reset_index()
    .rename(columns={"Neighborhood": "nhood"})
)

# Merge stats into geodataframe
gdf_map = gdf.merge(agg, on="nhood", how="left")
for col in ["Net_Units", "Market_Rate", "Affordable", "ADU",
            "Extremely_Low", "Very_Low", "Low", "Moderate"]:
    gdf_map[col] = gdf_map[col].fillna(0).astype(int)

# --- Build Folium map ---
m = folium.Map(location=[37.757, -122.44], zoom_start=12, tiles="CartoDB positron")

# Choropleth: color by net units completed
folium.Choropleth(
    geo_data=gdf_map.__geo_interface__,
    data=gdf_map,
    columns=["nhood", "Net_Units"],
    key_on="feature.properties.nhood",
    fill_color="YlOrRd",
    fill_opacity=0.65,
    line_opacity=0.4,
    legend_name="Net Units Completed",
    nan_fill_color="lightgray",
    highlight=True,
).add_to(m)

# Transparent overlay for tooltips and click detection
folium.GeoJson(
    gdf_map.__geo_interface__,
    style_function=lambda _: {
        "fillOpacity": 0,
        "color": "#555",
        "weight": 0.5,
    },
    highlight_function=lambda _: {
        "fillOpacity": 0.15,
        "color": "#222",
        "weight": 2,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["nhood", "Net_Units", "Market_Rate", "Affordable", "ADU"],
        aliases=["Neighborhood", "Net Units", "Market Rate", "Affordable", "ADUs"],
        localize=True,
        sticky=True,
    ),
).add_to(m)

# --- Layout ---
st.title("SF Housing Production 2005–2025")
st.caption(
    f"Showing completions from **{year_range[0]}** to **{year_range[1]}**. "
    f"Source: SF Planning Housing Inventory."
)

col_map, col_stats = st.columns([3, 2])

with col_map:
    map_result = st_folium(m, width=700, height=520, returned_objects=["last_clicked"])

with col_stats:
    # Detect clicked neighborhood via point-in-polygon
    clicked_nhood = None
    if map_result and map_result.get("last_clicked"):
        lat = map_result["last_clicked"]["lat"]
        lng = map_result["last_clicked"]["lng"]
        point = Point(lng, lat)
        match = gdf_map[gdf_map.geometry.contains(point)]
        if not match.empty:
            clicked_nhood = match.iloc[0]["nhood"]

    if clicked_nhood:
        row = gdf_map[gdf_map["nhood"] == clicked_nhood].iloc[0]
        st.subheader(row["nhood"])
        st.metric("Net Units Completed", f"{row['Net_Units']:,}")

        c1, c2 = st.columns(2)
        c1.metric("Market Rate", f"{row['Market_Rate']:,}")
        c2.metric("Affordable", f"{row['Affordable']:,}")
        st.metric("ADU / Legalization Units", f"{row['ADU']:,}")

        if row["Affordable"] > 0:
            st.markdown("**Affordable unit breakdown:**")
            breakdown = {
                "Extremely Low Income": row["Extremely_Low"],
                "Very Low Income": row["Very_Low"],
                "Low Income": row["Low"],
                "Moderate Income": row["Moderate"],
            }
            for label, val in breakdown.items():
                if val > 0:
                    st.write(f"- {label}: **{val:,}**")
    else:
        # Citywide totals when nothing is selected
        st.subheader("Citywide Totals")
        st.caption("Click a neighborhood on the map for details.")
        net = int(filtered["Net Units Completed"].sum())
        mkt = int(filtered["Market Rate"].sum())
        aff = int(filtered["Affordable Units"].sum())
        adu = int(filtered["ADU/Legalization Units"].sum())

        st.metric("Net Units Completed", f"{net:,}")
        c1, c2 = st.columns(2)
        c1.metric("Market Rate", f"{mkt:,}")
        c2.metric("Affordable", f"{aff:,}")
        st.metric("ADU / Legalization Units", f"{adu:,}")

        if aff > 0:
            st.markdown("**Affordable unit breakdown:**")
            aff_breakdown = {
                "Extremely Low Income": int(filtered["Extremely Low Income"].sum()),
                "Very Low Income": int(filtered["Very Low Income"].sum()),
                "Low Income": int(filtered["Low Income"].sum()),
                "Moderate Income": int(filtered["Moderate Income"].sum()),
            }
            for label, val in aff_breakdown.items():
                if val > 0:
                    st.write(f"- {label}: **{val:,}**")

import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
import altair as alt
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

    # Split ADU/Legalization Units into true ADUs vs legalizations
    is_legalization = df["Description"].str.contains("legali", case=False, na=False)
    has_adu = df["ADU/Legalization Units"] > 0
    df["Legalization_Units"] = df["ADU/Legalization Units"].where(has_adu & is_legalization, 0)
    df["True_ADU_Units"] = df["ADU/Legalization Units"].where(has_adu & ~is_legalization, 0)

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
        True_ADU=("True_ADU_Units", "sum"),
        Legalizations=("Legalization_Units", "sum"),
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
for col in ["Net_Units", "Market_Rate", "Affordable", "ADU", "True_ADU", "Legalizations",
            "Extremely_Low", "Very_Low", "Low", "Moderate"]:
    gdf_map[col] = gdf_map[col].fillna(0).astype(int)

# --- Build Folium map ---
m = folium.Map(location=[37.757, -122.44], zoom_start=12, tiles="CartoDB positron")

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

folium.GeoJson(
    gdf_map.__geo_interface__,
    style_function=lambda _: {"fillOpacity": 0, "color": "#555", "weight": 0.5},
    highlight_function=lambda _: {"fillOpacity": 0.15, "color": "#222", "weight": 2},
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
        st.caption(f"Totals for {year_range[0]}–{year_range[1]}")
        st.metric("Net Units Completed", f"{row['Net_Units']:,}")

        c1, c2 = st.columns(2)
        c1.metric("Market Rate", f"{row['Market_Rate']:,}")
        c2.metric("Affordable", f"{row['Affordable']:,}")
        st.metric("ADU / Legalization Units", f"{row['ADU']:,}")
        e1, e2 = st.columns(2)
        e1.metric("↳ True ADUs", f"{row['True_ADU']:,}")
        e2.metric("↳ Legalizations", f"{row['Legalizations']:,}")

        if row["Affordable"] > 0:
            st.markdown("**Affordable unit breakdown:**")
            for label, val in [
                ("Extremely Low Income", row["Extremely_Low"]),
                ("Very Low Income", row["Very_Low"]),
                ("Low Income", row["Low"]),
                ("Moderate Income", row["Moderate"]),
            ]:
                if val > 0:
                    st.write(f"- {label}: **{val:,}**")
    else:
        st.subheader("Citywide Totals")
        st.caption(f"Totals for {year_range[0]}–{year_range[1]} · Click a neighborhood for details.")
        net = int(filtered["Net Units Completed"].sum())
        mkt = int(filtered["Market Rate"].sum())
        aff = int(filtered["Affordable Units"].sum())
        adu = int(filtered["ADU/Legalization Units"].sum())
        true_adu = int(filtered["True_ADU_Units"].sum())
        legalizations = int(filtered["Legalization_Units"].sum())

        st.metric("Net Units Completed", f"{net:,}")
        c1, c2 = st.columns(2)
        c1.metric("Market Rate", f"{mkt:,}")
        c2.metric("Affordable", f"{aff:,}")
        st.metric("ADU / Legalization Units", f"{adu:,}")
        e1, e2 = st.columns(2)
        e1.metric("↳ True ADUs", f"{true_adu:,}")
        e2.metric("↳ Legalizations", f"{legalizations:,}")

        if aff > 0:
            st.markdown("**Affordable unit breakdown:**")
            for label, val in [
                ("Extremely Low Income", int(filtered["Extremely Low Income"].sum())),
                ("Very Low Income", int(filtered["Very Low Income"].sum())),
                ("Low Income", int(filtered["Low Income"].sum())),
                ("Moderate Income", int(filtered["Moderate Income"].sum())),
            ]:
                if val > 0:
                    st.write(f"- {label}: **{val:,}**")

# --- Bar chart: units by year ---
st.markdown("---")
if clicked_nhood:
    chart_title = f"Units completed per year — {clicked_nhood}"
    chart_data = filtered[filtered["Neighborhood"] == clicked_nhood]
else:
    chart_title = "Units completed per year — Citywide"
    chart_data = filtered

year_agg = (
    chart_data.groupby("Year")
    .agg(**{
        "Market Rate": ("Market Rate", "sum"),
        "Affordable": ("Affordable Units", "sum"),
    })
    .reset_index()
    .melt("Year", var_name="Type", value_name="Units")
)
year_agg["Year"] = year_agg["Year"].astype(int)

chart = (
    alt.Chart(year_agg)
    .mark_bar()
    .encode(
        x=alt.X("Year:O", title="Year"),
        y=alt.Y("Units:Q", title="Net Units"),
        color=alt.Color(
            "Type:N",
            scale=alt.Scale(
                domain=["Market Rate", "Affordable"],
                range=["#4e79a7", "#f28e2b"],
            ),
            legend=alt.Legend(title=""),
        ),
        tooltip=["Year:O", "Type:N", "Units:Q"],
    )
    .properties(title=chart_title, height=250)
)

st.altair_chart(chart, use_container_width=True)

# --- Planning District Rankings ---
st.markdown("---")
st.subheader(f"Planning District Rankings — {year_range[0]}–{year_range[1]}")

# Aggregate by planning district, keeping only clean "N - Name" entries
district_agg = (
    filtered[filtered["Planning Dist."].str.match(r"^\d+ - ", na=False)]
    .groupby("Planning Dist.")
    .agg(
        Net_Units=("Net Units Completed", "sum"),
        Market_Rate=("Market Rate", "sum"),
        Affordable=("Affordable Units", "sum"),
        ADU=("ADU/Legalization Units", "sum"),
    )
    .reset_index()
    .sort_values("Net_Units", ascending=False)
    .reset_index(drop=True)
)
district_agg.insert(0, "Rank", range(1, len(district_agg) + 1))

# Rename for clean Altair field names
district_chart_df = district_agg.rename(columns={
    "Planning Dist.": "District",
    "Net_Units": "Net Units",
    "Market_Rate": "Market Rate",
    "Affordable": "Affordable",
    "ADU": "ADUs",
})

# Horizontal bar chart
bar = (
    alt.Chart(district_chart_df)
    .mark_bar()
    .encode(
        x=alt.X("Net Units:Q", title="Net Units Completed"),
        y=alt.Y("District:N", sort="-x", title=None),
        color=alt.Color(
            "District:N",
            scale=alt.Scale(scheme="tableau20"),
            legend=None,
        ),
        opacity=alt.condition(
            alt.datum.District == "11 - Bernal Heights",
            alt.value(1.0),
            alt.value(0.75),
        ),
        tooltip=[
            alt.Tooltip("District:N", title="District"),
            alt.Tooltip("Net Units:Q", title="Net Units"),
            alt.Tooltip("Market Rate:Q", title="Market Rate"),
            alt.Tooltip("Affordable:Q", title="Affordable"),
            alt.Tooltip("ADUs:Q", title="ADUs"),
        ],
    )
    .properties(height=420)
)
st.altair_chart(bar, use_container_width=True)

# Summary table
st.markdown("**Full ranking table**")
st.dataframe(district_chart_df, use_container_width=True, hide_index=True)

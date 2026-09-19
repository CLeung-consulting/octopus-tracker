import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, timezone

# --- Page Setup ---
st.set_page_config(page_title="Octopus 24h Tracker", layout="wide", page_icon="⚡")
st.title("⚡ Octopus Energy: 24h Rates & Consumption Tracker")

# --- Default Constants ---
DEFAULT_PRODUCT = "AGILE-24-10-01"
DEFAULT_ELEC_TARIFF = f"E-1R-{DEFAULT_PRODUCT}-A"

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("🔑 Credentials & Settings")
    st.markdown("Get these details from your **Octopus Online Account** page.")
    
    api_key = st.text_input("Octopus API Key", type="password", help="Found under Account Settings -> Developer Details")
    mpan = st.text_input("Electricity MPAN", help="21-digit Electricity Meter Point Administration Number")
    serial_number = st.text_input("Meter Serial Number", help="Found on your physical meter or bill")
    
    st.divider()
    st.header("⚙️ Tariff Settings")
    product_code = st.text_input("Product Code", value=DEFAULT_PRODUCT)
    elec_tariff_code = st.text_input("Electricity Tariff Code", value=DEFAULT_ELEC_TARIFF)
    show_vat = st.checkbox("Include VAT (5%)", value=True)
    
    refresh_button = st.button("🔄 Refresh Data")

# --- Helper Functions ---
@st.cache_data(ttl=900)
def fetch_unit_rates(product_code: str, tariff_code: str, period_from: str) -> pd.DataFrame:
    """Fetch public electricity unit rates from Octopus REST API."""
    url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/"
    params = {"period_from": period_from, "page_size": 100}
    
    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        results = res.json().get("results", [])
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df["interval_start"] = pd.to_datetime(df["valid_from"], utc=True)
        return df.sort_values("interval_start").reset_index(drop=True)
    except Exception as e:
        st.error(f"Error fetching unit rates: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=900)
def fetch_consumption(api_key: str, mpan: str, serial_number: str, period_from: str) -> pd.DataFrame:
    """Fetch private half-hourly consumption data using HTTP Basic Auth."""
    url = f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}/meters/{serial_number}/consumption/"
    params = {"period_from": period_from, "page_size": 100, "order_by": "period"}
    
    try:
        # Octopus API uses API key as the username with no password
        res = requests.get(url, params=params, auth=(api_key, ""), timeout=10)
        res.raise_for_status()
        results = res.json().get("results", [])
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
        df["consumption_kwh"] = df["consumption"].astype(float)
        return df.sort_values("interval_start").reset_index(drop=True)
    except Exception as e:
        st.error(f"Error fetching consumption data: {e}")
        return pd.DataFrame()

# --- App Logic ---
now = datetime.now(timezone.utc)
period_from = (now - timedelta(hours=24)).isoformat()

# Fetch Unit Rates (Public)
df_rates = fetch_unit_rates(product_code, elec_tariff_code, period_from)

# Fetch Consumption (Private)
df_usage = pd.DataFrame()
if api_key and mpan and serial_number:
    with st.spinner("Fetching meter consumption data..."):
        df_usage = fetch_consumption(api_key, mpan, serial_number, period_from)
else:
    st.info("💡 Enter your API Key, MPAN, and Serial Number in the sidebar to display meter consumption.")

if not df_rates.empty:
    rate_col = "value_inc_vat" if show_vat else "value_exc_vat"
    df_rates["rate_p_kwh"] = df_rates[rate_col]

    # --- Data Merging & Cost Calculation ---
    if not df_usage.empty:
        # Merge consumption and rate data on matching 30-minute intervals
        df_merged = pd.merge(df_rates, df_usage, on="interval_start", how="inner")
        df_merged["est_cost_p"] = df_merged["consumption_kwh"] * df_merged["rate_p_kwh"]
    else:
        df_merged = df_rates

    # --- KPI Metrics Row ---
    col1, col2, col3, col4 = st.columns(4)
    current_rate = df_rates["rate_p_kwh"].iloc[-1]
    col1.metric("Latest Rate", f"{current_rate:.2f} p/kWh")
    col2.metric("24h Max Rate", f"{df_rates['rate_p_kwh'].max():.2f} p/kWh")
    
    if not df_usage.empty:
        total_kwh = df_merged["consumption_kwh"].sum()
        total_cost_gbp = (df_merged["est_cost_p"].sum()) / 100
        col3.metric("Total Usage (24h)", f"{total_kwh:.2f} kWh")
        col4.metric("Est. Energy Cost", f"£{total_cost_gbp:.2f}")

    st.markdown("---")

    # --- Dual-Axis Trend Chart ---
    st.subheader("📈 24-Hour Rates vs. Usage Trend")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Line Chart: Unit Rate
    fig.add_trace(
        go.Scatter(
            x=df_rates["interval_start"],
            y=df_rates["rate_p_kwh"],
            name="Unit Rate (p/kWh)",
            line=dict(color="#00d2c6", width=3),
            mode="lines+markers"
        ),
        secondary_y=False
    )

    # Bar Chart: Consumption
    if not df_usage.empty:
        fig.add_trace(
            go.Bar(
                x=df_merged["interval_start"],
                y=df_merged["consumption_kwh"],
                name="Consumption (kWh)",
                marker_color="rgba(255, 90, 95, 0.6)",
            ),
            secondary_y=True
        )

    # Chart Layout Config
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Time"
    )
    
    fig.update_yaxes(title_text=f"Rate (p/kWh {'inc VAT' if show_vat else 'exc VAT'})", secondary_y=False)
    if not df_usage.empty:
        fig.update_yaxes(title_text="Usage (kWh)", secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)

    # --- Detailed Table Section ---
    st.subheader("📋 Half-Hourly Data Breakdowns")
    
    if not df_usage.empty:
        table_df = df_merged[["interval_start", "rate_p_kwh", "consumption_kwh", "est_cost_p"]].copy()
        table_df.columns = ["Interval Start", "Rate (p/kWh)", "Usage (kWh)", "Cost (Pence)"]
        table_df["Cost (Pence)"] = table_df["Cost (Pence)"].round(2)
    else:
        table_df = df_rates[["interval_start", "rate_p_kwh"]].copy()
        table_df.columns = ["Interval Start", "Rate (p/kWh)"]
        
    table_df["Interval Start"] = table_df["Interval Start"].dt.strftime("%Y-%m-%d %H:%M UTC")
    
    st.dataframe(table_df, use_container_width=True, hide_index=True)

else:
    st.warning("No rate data received. Please verify product code and tariff settings.")

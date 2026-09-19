import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, timezone

# --- Page Setup ---
st.set_page_config(page_title="Octopus 8-Day Regional Tracker", layout="wide", page_icon="⚡")
st.title("⚡ Octopus Energy: 8-Day Regional Rate & Usage Tracker")

# --- Default Product Codes ---
DEFAULT_ELEC_PRODUCT = "AGILE-24-10-01"  # Agile Electricity
DEFAULT_GAS_PRODUCT = "VAR-22-11-01"     # Flexible Gas (or SILVER-24-10-01 for Tracker)

# --- Helper Functions ---
@st.cache_data(ttl=3600)
def get_region_code_from_postcode(postcode: str) -> str:
    """Lookup Octopus Grid Supply Point (GSP) region code (e.g., 'A', 'C', 'H') from UK Postcode."""
    if not postcode.strip():
        return "A"  # Default fallback
    
    formatted_postcode = postcode.strip().replace(" ", "").upper()
    url = f"https://api.octopus.energy/v1/industry/grid-supply-points/?postcode={formatted_postcode}"
    
    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        results = res.json().get("results", [])
        if results:
            group_id = results[0].get("group_id", "_A")
            return group_id.replace("_", "")
    except Exception as e:
        st.warning(f"Could not resolve region for postcode '{postcode}'. Defaulting to region 'A'. Error: {e}")
    return "A"

@st.cache_data(ttl=900)
def fetch_unit_rates(product_code: str, tariff_code: str, fuel_type: str, period_from: str) -> pd.DataFrame:
    """Fetch unit rates with pagination from public REST API."""
    url = f"https://api.octopus.energy/v1/products/{product_code}/{fuel_type}-tariffs/{tariff_code}/standard-unit-rates/"
    params = {"period_from": period_from, "page_size": 1500}
    
    all_results = []
    try:
        while url:
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
            all_results.extend(data.get("results", []))
            url = data.get("next")  # Pagination handling
            params = None  
            
        if not all_results:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_results)
        df["interval_start"] = pd.to_datetime(df["valid_from"], utc=True)
        return df.sort_values("interval_start").reset_index(drop=True)
    except Exception as e:
        st.error(f"Error fetching {fuel_type} rates ({tariff_code}): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=900)
def fetch_consumption(api_key: str, mpan: str, serial_number: str, period_from: str) -> pd.DataFrame:
    """Fetch electricity consumption using Basic Auth."""
    url = f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}/meters/{serial_number}/consumption/"
    params = {"period_from": period_from, "page_size": 1500, "order_by": "period"}
    
    all_results = []
    try:
        while url:
            res = requests.get(url, params=params, auth=(api_key, ""), timeout=10)
            res.raise_for_status()
            data = res.json()
            all_results.extend(data.get("results", []))
            url = data.get("next")
            params = None
            
        if not all_results:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_results)
        df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
        df["consumption_kwh"] = df["consumption"].astype(float)
        return df.sort_values("interval_start").reset_index(drop=True)
    except Exception as e:
        st.error(f"Error fetching consumption: {e}")
        return pd.DataFrame()

# --- Sidebar Inputs ---
with st.sidebar:
    st.header("📍 Location & Regional Tariff")
    
    # Location Input
    postcode_input = st.text_input(
        "UK Postcode", 
        value="AL1 3UU", 
        help="Used to dynamically query your DNO regional tariff group (e.g., Region A, C, H)"
    )
    
    # Resolve region code automatically from postcode
    region_letter = get_region_code_from_postcode(postcode_input)
    st.success(f"Detected Location Region: **Region {region_letter}**")
    
    st.divider()
    
    # Tariff Product Inputs
    st.header("⚙️ Fuel Products")
    col_prod1, col_prod2 = st.columns(2)
    with col_prod1:
        elec_product_code = st.text_input("Elec Product", value=DEFAULT_ELEC_PRODUCT)
    with col_prod2:
        gas_product_code = st.text_input("Gas Product", value=DEFAULT_GAS_PRODUCT)
    
    # Build regional tariff strings
    elec_tariff_code = f"E-1R-{elec_product_code}-{region_letter}"
    gas_tariff_code = f"G-1R-{gas_product_code}-{region_letter}"
    
    show_vat = st.checkbox("Include VAT (5%)", value=True)
    
    st.divider()
    
    # Optional Account Meter Credentials
    st.header("🔑 Meter Credentials (Optional)")
    api_key = st.text_input("API Key", type="password", help="Found under Octopus Developer Settings")
    mpan = st.text_input("Electricity MPAN")
    serial_number = st.text_input("Meter Serial Number")
    
    st.button("🔄 Refresh Data")

# --- Application Main Logic ---
now = datetime.now(timezone.utc)
period_from = (now - timedelta(days=8)).isoformat()  # Updated to last 8 days

with st.spinner(f"Fetching 8 days of electricity & gas rates for Region {region_letter}..."):
    df_elec = fetch_unit_rates(elec_product_code, elec_tariff_code, "electricity", period_from)
    df_gas = fetch_unit_rates(gas_product_code, gas_tariff_code, "gas", period_from)

df_usage = pd.DataFrame()
if api_key and mpan and serial_number:
    with st.spinner("Fetching 8 days of consumption data..."):
        df_usage = fetch_consumption(api_key, mpan, serial_number, period_from)

rate_col = "value_inc_vat" if show_vat else "value_exc_vat"

if not df_elec.empty:
    df_elec["rate_p_kwh"] = df_elec[rate_col]
    
    # Top KPI Bar
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current Elec Rate", f"{df_elec['rate_p_kwh'].iloc[-1]:.2f} p/kWh")
    col2.metric("8-Day Avg Rate", f"{df_elec['rate_p_kwh'].mean():.2f} p/kWh")
    col3.metric("8-Day Min Rate", f"{df_elec['rate_p_kwh'].min():.2f} p/kWh")
    col4.metric("8-Day Max Rate", f"{df_elec['rate_p_kwh'].max():.2f} p/kWh")
    
    st.markdown("---")

    # --- Trend Chart Section ---
    st.subheader(f"📈 8-Day Electricity & Gas Rates ({postcode_input.upper()} - Region {region_letter})")
    
    combined_data = []
    df_elec["Fuel"] = "Electricity"
    combined_data.append(df_elec)
    
    if not df_gas.empty:
        df_gas["rate_p_kwh"] = df_gas[rate_col]
        df_gas["Fuel"] = "Gas"
        combined_data.append(df_gas)
        
    df_rates_combined = pd.concat(combined_data, ignore_index=True)

    fig_rates = px.line(
        df_rates_combined,
        x="interval_start",
        y="rate_p_kwh",
        color="Fuel",
        labels={"interval_start": "Time (UTC)", "rate_p_kwh": "Unit Rate (p/kWh)"},
        color_discrete_map={"Electricity": "#00d2c6", "Gas": "#ff5a5f"}
    )
    fig_rates.update_layout(hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_rates, use_container_width=True)

    # --- Usage & Cost Chart (If Meter Credentials Provided) ---
    if not df_usage.empty:
        st.subheader("📊 8-Day Electricity Usage vs. Unit Rate")
        df_merged = pd.merge(df_elec, df_usage, on="interval_start", how="inner")
        df_merged["est_cost_p"] = df_merged["consumption_kwh"] * df_merged["rate_p_kwh"]

        fig_usage = make_subplots(specs=[[{"secondary_y": True}]])
        fig_usage.add_trace(
            go.Scatter(x=df_merged["interval_start"], y=df_merged["rate_p_kwh"], name="Rate (p/kWh)", line=dict(color="#00d2c6")),
            secondary_y=False
        )
        fig_usage.add_trace(
            go.Bar(x=df_merged["interval_start"], y=df_merged["consumption_kwh"], name="Usage (kWh)", marker_color="rgba(255, 90, 95, 0.5)"),
            secondary_y=True
        )
        fig_usage.update_layout(hovermode="x unified", margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_usage, use_container_width=True)

    # --- Data Table Section ---
    st.subheader("📋 Raw Rate Breakdown (Last 8 Days)")
    display_df = df_rates_combined[["Fuel", "interval_start", "rate_p_kwh"]].copy()
    display_df.columns = ["Fuel Type", "Interval Start (UTC)", "Rate (p/kWh)"]
    display_df["Interval Start (UTC)"] = display_df["Interval Start (UTC)"].dt.strftime("%Y-%m-%d %H:%M")
    
    st.dataframe(display_df, use_container_width=True, hide_index=True)

else:
    st.warning("No rate data returned. Please verify your postcode and electricity product code.")

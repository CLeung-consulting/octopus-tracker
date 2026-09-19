import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- Streamlit Page Setup ---
st.set_page_config(page_title="Octopus 24h Unit Rates", layout="wide", page_icon="⚡")
st.title("⚡ Octopus Energy: 24-Hour Rate Tracker")

# --- Default Constants ---
# Common Product: AGILE-24-10-01 (Agile Octopus) or VAR-22-11-01 (Flexible)
DEFAULT_PRODUCT = "AGILE-24-10-01"
DEFAULT_ELEC_TARIFF = f"E-1R-{DEFAULT_PRODUCT}-A"  # Region 'A' = Eastern England (adjust as needed)
DEFAULT_GAS_TARIFF = f"G-1R-{DEFAULT_PRODUCT}-A"

# --- Sidebar Configuration ---
with st.sidebar:
    st.header("⚙️ Settings")
    st.markdown("Find product & tariff codes in your Octopus account details.")
    
    product_code = st.text_input("Product Code", value=DEFAULT_PRODUCT)
    elec_tariff_code = st.text_input("Electricity Tariff Code", value=DEFAULT_ELEC_TARIFF)
    gas_tariff_code = st.text_input("Gas Tariff Code", value=DEFAULT_GAS_TARIFF)
    
    show_vat = st.checkbox("Include VAT (5%)", value=True)
    refresh_button = st.button("🔄 Refresh Data")

# --- Helper Functions ---
@st.cache_data(ttl=900)  # Cache results for 15 minutes to respect API rates
def fetch_octopus_rates(product_code: str, tariff_code: str, fuel_type: str, period_from: str) -> pd.DataFrame:
    """Fetch unit rates from the public Octopus Energy REST API."""
    url = f"https://api.octopus.energy/v1/products/{product_code}/{fuel_type}-tariffs/{tariff_code}/standard-unit-rates/"
    params = {
        "period_from": period_from,
        "page_size": 100
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("results", [])
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        # Parse ISO timestamps to datetime
        df["valid_from"] = pd.to_datetime(df["valid_from"])
        df["valid_to"] = pd.to_datetime(df["valid_to"])
        
        # Sort chronologically
        df = df.sort_values("valid_from").reset_index(drop=True)
        return df
        
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching {fuel_type} rates: {e}")
        return pd.DataFrame()

# --- Main App Execution ---
# Define timeframe for the last 24 hours
now = datetime.now(timezone.utc)
period_from = (now - timedelta(hours=24)).isoformat()

with st.spinner("Fetching electricity and gas rates..."):
    df_elec = fetch_octopus_rates(product_code, elec_tariff_code, "electricity", period_from)
    df_gas = fetch_octopus_rates(product_code, gas_tariff_code, "gas", period_from)

# Process rates based on VAT preference
rate_col = "value_inc_vat" if show_vat else "value_exc_vat"

combined_data = []

if not df_elec.empty:
    df_elec["Fuel"] = "Electricity"
    df_elec["Rate (p/kWh)"] = df_elec[rate_col]
    combined_data.append(df_elec)

if not df_gas.empty:
    df_gas["Fuel"] = "Gas"
    df_gas["Rate (p/kWh)"] = df_gas[rate_col]
    combined_data.append(df_gas)

if combined_data:
    df_combined = pd.concat(combined_data, ignore_index=True)

    # --- Trend Chart Section ---
    st.subheader("📈 Unit Rates (Past 24 Hours)")
    
    fig = px.line(
        df_combined,
        x="valid_from",
        y="Rate (p/kWh)",
        color="Fuel",
        markers=True,
        labels={"valid_from": "Time", "Rate (p/kWh)": "Unit Rate (p/kWh)"},
        color_discrete_map={"Electricity": "#00d2c6", "Gas": "#ff5a5f"}
    )
    
    fig.update_layout(
        xaxis_title="Time",
        yaxis_title=f"Price (p/kWh {'inc. VAT' if show_vat else 'exc. VAT'})",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=30, b=20)
    )
    
    st.plotly_chart(fig, use_container_width=True)

    # --- Metric KPI Summaries ---
    col1, col2, col3, col4 = st.columns(4)
    if not df_elec.empty:
        col1.metric("Current Elec Rate", f"{df_elec['Rate (p/kWh)'].iloc[-1]:.2f} p/kWh")
        col2.metric("Max Elec (24h)", f"{df_elec['Rate (p/kWh)'].max():.2f} p/kWh")
    if not df_gas.empty:
        col3.metric("Current Gas Rate", f"{df_gas['Rate (p/kWh)'].iloc[-1]:.2f} p/kWh")
        col4.metric("Avg Gas (24h)", f"{df_gas['Rate (p/kWh)'].mean():.2f} p/kWh")

    st.markdown("---")

    # --- Data Table Section ---
    st.subheader("📋 Detailed Rate Data")
    
    # Format dataframe for clean table presentation
    display_df = df_combined[["Fuel", "valid_from", "valid_to", "Rate (p/kWh)"]].copy()
    display_df.columns = ["Fuel Type", "Valid From", "Valid To", "Rate (p/kWh)"]
    display_df["Valid From"] = display_df["Valid From"].dt.strftime("%Y-%m-%d %H:%M")
    display_df["Valid To"] = display_df["Valid To"].dt.strftime("%Y-%m-%d %H:%M")
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

else:
    st.warning("No rate data returned. Check your Product and Tariff codes in the sidebar.")

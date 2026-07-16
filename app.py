import os
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Precision Patterns Screener", layout="wide", page_icon="📊")

DATA_DIR = Path(__file__).parent / "data"

SOURCES = {
    "Stocks · Daily":  "stocks_Daily.csv",
    "Stocks · Weekly": "stocks_Weekly.csv",
    "Stocks · 4H":     "stocks_4H.csv",
    "ETF Settoriali":  "etf_sector.csv",
}

STATUS_EMOJI = {
    "BREAKOUT": "🚀 BREAKOUT",
    "FORMING": "🕐 FORMING",
    "CONFIRMED": "🔻 CONFIRMED",
    "PENDING": "⏳ PENDING",
}


@st.cache_data(ttl=1800)
def load_csv(filename: str) -> pd.DataFrame | None:
    path = DATA_DIR / filename
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        return df if not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def tv_symbol(ticker: str) -> str:
    # BRK-B -> BRK.B per TradingView
    return ticker.replace("-", ".")


# ================= SIDEBAR =================

st.sidebar.title("📊 Precision Patterns")

source_name = st.sidebar.radio("Universo", list(SOURCES.keys()))
df = load_csv(SOURCES[source_name])

if df is None:
    st.warning("⚠️ Nessun dato ancora disponibile. Lancia prima la GitHub Action per generare i CSV in `data/`.")
    st.stop()

if df.empty:
    st.info("Nessun pattern trovato nell'ultimo run per questo universo.")
    st.stop()

run_date = df["Run_Date"].iloc[0] if "Run_Date" in df.columns else "n/d"
st.sidebar.caption(f"🗓️ Ultimo run: **{run_date}**")
st.sidebar.divider()

# --- Filtri ---
min_score = st.sidebar.slider("Best Score minimo", 0, 100, 40, step=5)

all_status = ["BREAKOUT", "FORMING", "CONFIRMED", "PENDING"]
sel_status = st.sidebar.multiselect("Status pattern", all_status, default=all_status)

pattern_type = st.sidebar.radio("Tipo pattern", ["Tutti", "Solo Cup & Handle", "Solo Double Top"])

rsi_range = st.sidebar.slider("RSI", 0, 100, (0, 100))

# ================= FILTERING =================

fdf = df.copy()

ch_in = fdf["CH_Status"].isin(sel_status) if "CH_Status" in fdf else False
dt_in = fdf["DT_Status"].isin(sel_status) if "DT_Status" in fdf else False

if pattern_type == "Solo Cup & Handle":
    fdf = fdf[fdf["CH_Status"].notna() & ch_in]
elif pattern_type == "Solo Double Top":
    fdf = fdf[fdf["DT_Status"].notna() & dt_in]
else:
    fdf = fdf[ch_in | dt_in]

fdf = fdf[fdf["Best_Score"] >= min_score]
fdf = fdf[(fdf["RSI"] >= rsi_range[0]) & (fdf["RSI"] <= rsi_range[1])]
fdf = fdf.sort_values("Best_Score", ascending=False).reset_index(drop=True)

# ================= HEADER =================

st.title(f"{source_name}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Setup filtrati", len(fdf))
c2.metric("Cup & Handle", int(fdf["CH_Status"].notna().sum()))
c3.metric("Double Top", int(fdf["DT_Status"].notna().sum()))
c4.metric("Score ≥ 70", int((fdf["Best_Score"] >= 70).sum()))

st.divider()

# ================= TABLE =================

show = fdf.copy()
show["TradingView"] = "https://www.tradingview.com/chart/?symbol=" + show["Ticker"].map(tv_symbol)
show["CH_Status"] = show["CH_Status"].map(STATUS_EMOJI).fillna("—")
show["DT_Status"] = show["DT_Status"].map(STATUS_EMOJI).fillna("—")

cols_front = ["Ticker", "Best_Score", "Prezzo", "RSI", "CH_Status", "CH_Score", "DT_Status", "DT_Score", "TradingView"]
cols_rest = [c for c in show.columns if c not in cols_front]
show = show[cols_front + cols_rest]

st.dataframe(
    show,
    column_config={
        "TradingView": st.column_config.LinkColumn("Chart", display_text="📈 Apri"),
        "Best_Score": st.column_config.ProgressColumn("Best Score", min_value=0, max_value=100, format="%d"),
        "CH_Score": st.column_config.NumberColumn("CH Score"),
        "DT_Score": st.column_config.NumberColumn("DT Score"),
    },
    use_container_width=True,
    hide_index=True,
    height=450,
)

# ================= QUICK CHART =================

st.divider()
st.subheader("🔍 Quick chart")

if len(fdf) > 0:
    sel = st.selectbox("Ticker", fdf["Ticker"].tolist())

    if st.button("Carica grafico", type="primary"):
        import yfinance as yf

        with st.spinner(f"Scarico {sel}..."):
            hist = yf.download(sel, period="1y", interval="1d", auto_adjust=True, progress=False)

        if hist is None or hist.empty:
            st.error("Dati non disponibili per questo ticker.")
        else:
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.droplevel(1)

            fig = go.Figure(go.Candlestick(
                x=hist.index, open=hist["Open"], high=hist["High"],
                low=hist["Low"], close=hist["Close"], name=sel,
            ))

            row = fdf[fdf["Ticker"] == sel].iloc[0]
            if pd.notna(row.get("CH_Rim")):
                fig.add_hline(y=row["CH_Rim"], line_dash="dash", line_color="green",
                              annotation_text=f"C&H Rim {row['CH_Rim']}")
            if pd.notna(row.get("DT_Neckline")):
                fig.add_hline(y=row["DT_Neckline"], line_dash="dash", line_color="red",
                              annotation_text=f"DT Neckline {row['DT_Neckline']}")

            fig.update_layout(height=550, xaxis_rangeslider_visible=False,
                              margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)

    st.link_button(f"Apri {sel} su TradingView ↗",
                   f"https://www.tradingview.com/chart/?symbol={tv_symbol(sel)}")

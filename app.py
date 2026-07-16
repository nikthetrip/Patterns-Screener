import time
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
    return ticker.replace("-", ".")


# =====================================================
# PREZZI (chart): yfinance con retry -> fallback Stooq
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_history(ticker: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        for attempt in range(2):
            try:
                hist = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=True)
                if hist is not None and not hist.empty:
                    if isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = hist.columns.droplevel(1)
                    return hist[["Open", "High", "Low", "Close"]].dropna()
            except Exception:
                pass
            time.sleep(1 + attempt)
    except Exception:
        pass

    try:
        stooq_sym = ticker.lower() + ".us"
        url = f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d"
        hist = pd.read_csv(url, parse_dates=["Date"], index_col="Date")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            hist = hist[["Open", "High", "Low", "Close"]].dropna()
            return hist.last("365D") if len(hist) > 0 else None
    except Exception:
        pass

    return None


# =====================================================
# FONDAMENTALI (yfinance .info + bilanci)
# =====================================================

def _safe_div(a, b):
    try:
        if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
            return None
        return a / b
    except Exception:
        return None


def _find_row(df: pd.DataFrame, names: list[str]):
    """Cerca una riga del bilancio per nome (yfinance cambia label tra versioni)."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_fundamentals(ticker: str) -> dict:
    out = {
        "name": None, "sector": None, "industry": None, "summary": None,
        "market_cap": None, "pe": None, "ps": None,
        "equity_ratio": None, "earning_power": None,
        "fcf": None, "fcf_yield": None, "fcf_growth_yoy": None,
        "is_fund": False, "error": None,
    }
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)

        info = {}
        for attempt in range(2):
            try:
                info = tk.info or {}
                if info:
                    break
            except Exception:
                time.sleep(1 + attempt)

        if not info:
            out["error"] = "info non disponibile"
            return out

        out["name"] = info.get("longName") or info.get("shortName")
        out["sector"] = info.get("sector")
        out["industry"] = info.get("industry")
        out["summary"] = info.get("longBusinessSummary")
        out["market_cap"] = info.get("marketCap")
        out["pe"] = info.get("trailingPE")
        out["ps"] = info.get("priceToSalesTrailing12Months")
        out["is_fund"] = info.get("quoteType") in ("ETF", "MUTUALFUND")

        if out["is_fund"]:
            # per gli ETF i fondamentali aziendali non hanno senso
            out["summary"] = out["summary"] or info.get("description")
            return out

        # --- Bilanci ---
        try:
            bs = tk.balance_sheet
        except Exception:
            bs = None
        try:
            cf = tk.cashflow
        except Exception:
            cf = None
        try:
            fin = tk.financials
        except Exception:
            fin = None

        # Equity ratio = Total Equity / Total Assets (ultimo esercizio)
        equity = _find_row(bs, ["Stockholders Equity", "Total Stockholder Equity",
                                "Common Stock Equity", "Total Equity Gross Minority Interest"])
        assets = _find_row(bs, ["Total Assets"])
        if equity is not None and assets is not None and len(equity) > 0 and len(assets) > 0:
            out["equity_ratio"] = _safe_div(float(equity.iloc[0]), float(assets.iloc[0]))

        # Earning power (Graham) = EBIT / Total Assets
        ebit = _find_row(fin, ["EBIT", "Operating Income"])
        if ebit is not None and assets is not None and len(ebit) > 0 and len(assets) > 0:
            out["earning_power"] = _safe_div(float(ebit.iloc[0]), float(assets.iloc[0]))

        # FCF: preferisci la riga del cashflow, fallback su info
        fcf_row = _find_row(cf, ["Free Cash Flow"])
        fcf_now = None
        if fcf_row is not None and len(fcf_row) > 0 and not pd.isna(fcf_row.iloc[0]):
            fcf_now = float(fcf_row.iloc[0])
            if len(fcf_row) > 1 and not pd.isna(fcf_row.iloc[1]) and fcf_row.iloc[1] != 0:
                prev = float(fcf_row.iloc[1])
                # crescita YoY significativa solo se il FCF precedente era positivo
                if prev > 0:
                    out["fcf_growth_yoy"] = (fcf_now - prev) / prev
        if fcf_now is None:
            fcf_now = info.get("freeCashflow")

        out["fcf"] = fcf_now
        out["fcf_yield"] = _safe_div(fcf_now, out["market_cap"])

    except Exception as e:
        out["error"] = str(e)

    return out


def fmt_pct(x, decimals=1):
    return f"{x * 100:.{decimals}f}%" if x is not None and not pd.isna(x) else "n/d"


def fmt_num(x, decimals=1):
    return f"{x:.{decimals}f}" if x is not None and not pd.isna(x) else "n/d"


def fmt_cap(x):
    if x is None or pd.isna(x):
        return "n/d"
    if x >= 1e12:
        return f"{x / 1e12:.2f} T$"
    if x >= 1e9:
        return f"{x / 1e9:.1f} B$"
    return f"{x / 1e6:.0f} M$"


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

# ================= TABLE (con selezione riga) =================

st.caption("👆 Clicca su una riga per vedere info societarie, fondamentali e grafico.")

show = fdf.copy()
show["TradingView"] = "https://www.tradingview.com/chart/?symbol=" + show["Ticker"].map(tv_symbol)
show["CH_Status"] = show["CH_Status"].map(STATUS_EMOJI).fillna("—")
show["DT_Status"] = show["DT_Status"].map(STATUS_EMOJI).fillna("—")

cols_front = ["Ticker", "Best_Score", "Prezzo", "RSI", "CH_Status", "CH_Score", "DT_Status", "DT_Score", "TradingView"]
cols_rest = [c for c in show.columns if c not in cols_front]
show = show[cols_front + cols_rest]

selection = st.dataframe(
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
    on_select="rerun",
    selection_mode="single-row",
)

# --- Ticker selezionato: dalla riga cliccata, fallback selectbox ---
sel = None
sel_rows = selection.selection.rows if selection and selection.selection else []
if sel_rows:
    sel = fdf.iloc[sel_rows[0]]["Ticker"]

if sel is None:
    st.info("Nessuna riga selezionata — scegli un ticker qui sotto oppure clicca in tabella.")
    sel = st.selectbox("Ticker", fdf["Ticker"].tolist())

row = fdf[fdf["Ticker"] == sel].iloc[0]

# ================= INFO SOCIETARIE + FONDAMENTALI =================

st.divider()

with st.spinner(f"Carico dati {sel}..."):
    fund = fetch_fundamentals(sel)

title_name = fund["name"] or sel
st.subheader(f"🏢 {title_name}  ·  {sel}")

if fund["sector"] or fund["industry"]:
    st.caption(" · ".join(x for x in [fund["sector"], fund["industry"]] if x))

if fund["summary"]:
    # descrizione breve: primi ~2 periodi
    sentences = fund["summary"].split(". ")
    short = ". ".join(sentences[:2]).strip()
    if not short.endswith("."):
        short += "."
    st.markdown(short)
    if len(sentences) > 2:
        with st.expander("Descrizione completa"):
            st.write(fund["summary"])
elif fund["error"]:
    st.caption(f"Info societarie non disponibili al momento ({fund['error']}).")

if fund["is_fund"]:
    m1, m2 = st.columns(2)
    m1.metric("AUM / Market Cap", fmt_cap(fund["market_cap"]))
    m2.metric("P/E (holdings)", fmt_num(fund["pe"]))
    st.caption("Strumento di tipo fondo/ETF: i fondamentali aziendali non sono applicabili.")
else:
    m1, m2, m3 = st.columns(3)
    m1.metric("Market Cap", fmt_cap(fund["market_cap"]))
    m2.metric("P/E (trailing)", fmt_num(fund["pe"]))
    m3.metric("P/S (ttm)", fmt_num(fund["ps"]))

    m4, m5, m6 = st.columns(3)
    m4.metric("Equity ratio", fmt_pct(fund["equity_ratio"]),
              help="Patrimonio netto / Totale attivo — solidità patrimoniale")
    m5.metric("Earning power", fmt_pct(fund["earning_power"]),
              help="EBIT / Totale attivo (Graham) — redditività del capitale investito")
    m6.metric("FCF yield", fmt_pct(fund["fcf_yield"]),
              help="Free Cash Flow / Market Cap")

    m7, m8, _ = st.columns(3)
    m7.metric("FCF growth YoY", fmt_pct(fund["fcf_growth_yoy"]),
              delta=fmt_pct(fund["fcf_growth_yoy"]) if fund["fcf_growth_yoy"] is not None else None,
              help="Variazione del Free Cash Flow rispetto all'esercizio precedente (n/d se il FCF precedente era negativo)")
    m8.metric("FCF (ultimo FY)", fmt_cap(fund["fcf"]))

# ================= CHART (automatica) =================

st.divider()
st.subheader(f"📈 Chart · {sel}")

with st.spinner(f"Scarico prezzi {sel}..."):
    hist = fetch_history(sel)

if hist is None or hist.empty:
    st.error("Dati prezzo non disponibili per questo ticker (Yahoo e Stooq non raggiungibili). "
             "Usa il link TradingView qui sotto.")
else:
    fig = go.Figure(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"], name=sel,
    ))

    if pd.notna(row.get("CH_Rim")):
        fig.add_hline(y=float(row["CH_Rim"]), line_dash="dash", line_color="#26a69a",
                      annotation_text=f"C&H Rim {row['CH_Rim']}")
    if pd.notna(row.get("DT_Neckline")):
        fig.add_hline(y=float(row["DT_Neckline"]), line_dash="dash", line_color="#ef5350",
                      annotation_text=f"DT Neckline {row['DT_Neckline']}")

    fig.update_layout(height=550, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Dati EOD; se caricati da Stooq possono differire leggermente da Yahoo "
               "(dividend adjustment). I livelli Rim/Neckline provengono dallo screener.")

st.link_button(f"Apri {sel} su TradingView ↗",
               f"https://www.tradingview.com/chart/?symbol={tv_symbol(sel)}")

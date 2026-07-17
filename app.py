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
    "Sector ETFs":     "etf_sector.csv",
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


# Yahoo exchange code -> TradingView prefix
_TV_EXCHANGE = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NASDAQ": "NASDAQ",
    "NYQ": "NYSE", "NYSE": "NYSE",
    "ASE": "AMEX", "AMEX": "AMEX", "PCX": "AMEX", "PSE": "AMEX",  # NYSE Arca -> AMEX on TV
    "BTS": "AMEX", "CBOE": "CBOE",
}


def tv_financials_url(ticker: str, exchange: str | None) -> str:
    sym = tv_symbol(ticker).replace(".", "-")  # /symbols/ paths use dashes
    prefix = _TV_EXCHANGE.get(exchange or "", None)
    if prefix:
        return f"https://www.tradingview.com/symbols/{prefix}-{sym}/financials-income-statement/"
    return f"https://www.tradingview.com/symbols/{sym}/financials-income-statement/"


# =====================================================
# PRICE HISTORY (chart): yfinance w/ retry -> Stooq fallback
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
# FUNDAMENTALS (yfinance .info + statements)
# =====================================================

def _safe_div(a, b):
    try:
        if a is None or b is None or pd.isna(a) or pd.isna(b) or b == 0:
            return None
        return a / b
    except Exception:
        return None


def _find_row(df: pd.DataFrame, names: list[str]):
    """Find a statement row by label (yfinance labels vary across versions)."""
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
        "market_cap": None, "pe": None, "fwd_pe": None, "ps": None,
        "roe": None, "lt_debt": None,
        "equity_ratio": None, "earning_power": None,
        "fcf": None, "fcf_yield": None, "fcf_growth_yoy": None,
        "exchange": None, "next_earnings": None,
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
            out["error"] = "info unavailable"
            return out

        out["name"] = info.get("longName") or info.get("shortName")
        out["sector"] = info.get("sector")
        out["industry"] = info.get("industry")
        out["summary"] = info.get("longBusinessSummary")
        out["market_cap"] = info.get("marketCap")
        out["pe"] = info.get("trailingPE")
        out["fwd_pe"] = info.get("forwardPE")
        out["ps"] = info.get("priceToSalesTrailing12Months")
        out["roe"] = info.get("returnOnEquity")
        out["exchange"] = info.get("exchange")
        out["is_fund"] = info.get("quoteType") in ("ETF", "MUTUALFUND")

        # Next earnings date
        try:
            cal = tk.calendar
            ed = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
            elif cal is not None and hasattr(cal, "loc") and "Earnings Date" in getattr(cal, "index", []):
                ed = cal.loc["Earnings Date"]
            if ed is not None:
                if isinstance(ed, (list, tuple)) and len(ed) > 0:
                    ed = ed[0]
                elif hasattr(ed, "iloc") and len(ed) > 0:
                    ed = ed.iloc[0]
                out["next_earnings"] = str(pd.Timestamp(ed).date())
        except Exception:
            pass

        if out["is_fund"]:
            out["summary"] = out["summary"] or info.get("description")
            return out

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

        # Equity ratio = Total Equity / Total Assets (latest FY)
        equity = _find_row(bs, ["Stockholders Equity", "Total Stockholder Equity",
                                "Common Stock Equity", "Total Equity Gross Minority Interest"])
        assets = _find_row(bs, ["Total Assets"])
        if equity is not None and assets is not None and len(equity) > 0 and len(assets) > 0:
            out["equity_ratio"] = _safe_div(float(equity.iloc[0]), float(assets.iloc[0]))

        # Long term debt (latest FY)
        ltd = _find_row(bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
        if ltd is not None and len(ltd) > 0 and not pd.isna(ltd.iloc[0]):
            out["lt_debt"] = float(ltd.iloc[0])

        # Earning power (Graham) = EBIT / Total Assets
        ebit = _find_row(fin, ["EBIT", "Operating Income"])
        if ebit is not None and assets is not None and len(ebit) > 0 and len(assets) > 0:
            out["earning_power"] = _safe_div(float(ebit.iloc[0]), float(assets.iloc[0]))

        # FCF: prefer cashflow statement row, fallback to info
        fcf_row = _find_row(cf, ["Free Cash Flow"])
        fcf_now = None
        if fcf_row is not None and len(fcf_row) > 0 and not pd.isna(fcf_row.iloc[0]):
            fcf_now = float(fcf_row.iloc[0])
            if len(fcf_row) > 1 and not pd.isna(fcf_row.iloc[1]) and fcf_row.iloc[1] != 0:
                prev = float(fcf_row.iloc[1])
                if prev > 0:  # YoY growth only meaningful on a positive base
                    out["fcf_growth_yoy"] = (fcf_now - prev) / prev
        if fcf_now is None:
            fcf_now = info.get("freeCashflow")

        out["fcf"] = fcf_now
        out["fcf_yield"] = _safe_div(fcf_now, out["market_cap"])

    except Exception as e:
        out["error"] = str(e)

    return out


def fmt_pct(x, decimals=1):
    return f"{x * 100:.{decimals}f}%" if x is not None and not pd.isna(x) else "n/a"


def fmt_num(x, decimals=1):
    return f"{x:.{decimals}f}" if x is not None and not pd.isna(x) else "n/a"


def fmt_cap(x):
    if x is None or pd.isna(x):
        return "n/a"
    if x >= 1e12:
        return f"{x / 1e12:.2f} T$"
    if x >= 1e9:
        return f"{x / 1e9:.1f} B$"
    return f"{x / 1e6:.0f} M$"


# =====================================================
# ANNUAL FINANCIAL HISTORY (yfinance statements)
# Note: yfinance exposes ~4-5 fiscal years max
# =====================================================

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_financial_history(ticker: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)

        try:
            fin = tk.income_stmt
        except Exception:
            fin = None
        try:
            bs = tk.balance_sheet
        except Exception:
            bs = None
        try:
            cf = tk.cashflow
        except Exception:
            cf = None

        revenue = _find_row(fin, ["Total Revenue", "Operating Revenue"])
        net_inc = _find_row(fin, ["Net Income", "Net Income Common Stockholders"])
        debt    = _find_row(bs, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"])
        fcf     = _find_row(cf, ["Free Cash Flow"])

        if revenue is None and debt is None and fcf is None:
            return None

        frames = {}
        for name, series in [("Revenue", revenue), ("NetIncome", net_inc),
                             ("Debt", debt), ("FCF", fcf)]:
            if series is not None:
                s = series.dropna()
                s.index = pd.to_datetime(s.index).year
                frames[name] = s

        if not frames:
            return None

        hist = pd.DataFrame(frames)
        hist = hist[~hist.index.duplicated(keep="first")].sort_index()

        if "Revenue" in hist.columns and "NetIncome" in hist.columns:
            hist["NetMargin_%"] = hist["NetIncome"] / hist["Revenue"] * 100

        return hist if not hist.empty else None
    except Exception:
        return None


# =====================================================
# ETF DATA (yfinance funds_data + info)
# =====================================================

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_etf_data(ticker: str) -> dict:
    out = {
        "name": None, "summary": None, "aum": None, "pe": None,
        "expense_ratio": None, "top_holdings": None, "sector_weights": None,
        "category": None, "error": None,
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

        out["name"] = info.get("longName") or info.get("shortName")
        out["summary"] = info.get("longBusinessSummary") or info.get("description")
        out["aum"] = info.get("totalAssets")
        out["pe"] = info.get("trailingPE")
        out["category"] = info.get("category")
        er = info.get("netExpenseRatio")
        if er is None:
            er = info.get("annualReportExpenseRatio")
        # Yahoo returns expense ratio sometimes as 0.35 (percent) sometimes 0.0035
        if er is not None:
            out["expense_ratio"] = er / 100 if er > 0.5 else er

        try:
            fd = tk.funds_data
            if fd is not None:
                try:
                    th = fd.top_holdings
                    if th is not None and not th.empty:
                        out["top_holdings"] = th.head(10)
                except Exception:
                    pass
                try:
                    sw = fd.sector_weightings
                    if sw:
                        out["sector_weights"] = sw
                except Exception:
                    pass
                if not out["summary"]:
                    try:
                        out["summary"] = fd.description
                    except Exception:
                        pass
        except Exception:
            pass

        if not info and out["top_holdings"] is None:
            out["error"] = "data unavailable"
    except Exception as e:
        out["error"] = str(e)
    return out


# ================= SIDEBAR =================

st.sidebar.title("📊 Precision Patterns")

source_name = st.sidebar.radio("Universe", list(SOURCES.keys()))
df = load_csv(SOURCES[source_name])

if df is None:
    st.warning("⚠️ No data available yet. Run the GitHub Action first to generate the CSV files in `data/`.")
    st.stop()

if df.empty:
    st.info("No patterns found in the latest run for this universe.")
    st.stop()

run_date = df["Run_Date"].iloc[0] if "Run_Date" in df.columns else "n/a"
st.sidebar.caption(f"🗓️ Last run: **{run_date}**")
st.sidebar.divider()

min_score = st.sidebar.slider("Minimum Best Score", 0, 100, 40, step=5)

all_status = ["BREAKOUT", "FORMING", "CONFIRMED", "PENDING"]
sel_status = st.sidebar.multiselect("Pattern status", all_status, default=all_status)

pattern_type = st.sidebar.radio("Pattern type", ["All", "Cup & Handle only", "Double Top only"])

rsi_range = st.sidebar.slider("RSI", 0, 100, (0, 100))

max_bars_since = st.sidebar.slider(
    "Max bars since signal", 0, 30, 30,
    help="Keep only patterns whose status changed within the last N bars "
         "(uses CH/DT Bars_Since; 30 = no filter)")

# ================= FILTERING =================

fdf = df.copy()

ch_in = fdf["CH_Status"].isin(sel_status) if "CH_Status" in fdf else False
dt_in = fdf["DT_Status"].isin(sel_status) if "DT_Status" in fdf else False

if pattern_type == "Cup & Handle only":
    fdf = fdf[fdf["CH_Status"].notna() & ch_in]
elif pattern_type == "Double Top only":
    fdf = fdf[fdf["DT_Status"].notna() & dt_in]
else:
    fdf = fdf[ch_in | dt_in]

fdf = fdf[fdf["Best_Score"] >= min_score]
fdf = fdf[(fdf["RSI"] >= rsi_range[0]) & (fdf["RSI"] <= rsi_range[1])]

# Recency filter: keep a row if at least one active pattern is recent enough.
# 30 = slider at max = filter disabled.
if max_bars_since < 30:
    ch_bs = pd.to_numeric(fdf.get("CH_Bars_Since"), errors="coerce")
    dt_bs = pd.to_numeric(fdf.get("DT_Bars_Since"), errors="coerce")
    ch_recent = ch_bs.notna() & (ch_bs <= max_bars_since)
    dt_recent = dt_bs.notna() & (dt_bs <= max_bars_since)
    fdf = fdf[ch_recent | dt_recent]

fdf = fdf.sort_values("Best_Score", ascending=False).reset_index(drop=True)

# ================= HEADER =================

st.title(f"{source_name}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Filtered setups", len(fdf))
c2.metric("Cup & Handle", int(fdf["CH_Status"].notna().sum()))
c3.metric("Double Top", int(fdf["DT_Status"].notna().sum()))
c4.metric("Score ≥ 70", int((fdf["Best_Score"] >= 70).sum()))

st.divider()

# ================= TABLE (row selection) =================

try:
    from datetime import datetime, timezone
    mtime = (DATA_DIR / SOURCES[source_name]).stat().st_mtime
    upd = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    st.caption(f"🗓️ Last update: **{run_date}** · data refreshed {upd}")
except Exception:
    st.caption(f"🗓️ Last update: **{run_date}**")

show = fdf.copy()
show["Chart"] = "https://www.tradingview.com/chart/?symbol=" + show["Ticker"].map(tv_symbol)
show["CH_Status"] = show["CH_Status"].map(STATUS_EMOJI).fillna("—")
show["DT_Status"] = show["DT_Status"].map(STATUS_EMOJI).fillna("—")

# Pattern-detail columns hidden from the table (kept in CSV and used by the chart)
HIDE_COLS = ["CH_Rim", "CH_Depth_%", "CH_Cup_Bars", "CH_Handle_Bars", "CH_Handle_Retr_%",
             "DT_Neckline", "DT_Diff_%", "DT_Valley_%", "DT_Sep_Bars",
             "ATR14", "ATR_%", "CH_PriorRise_ATR"]
show = show.drop(columns=[c for c in HIDE_COLS if c in show.columns])

# Fixed column order (as per reference layout); missing columns are skipped
COL_ORDER = ["Ticker", "Best_Score", "Chart", "Timeframe", "Prezzo", "RSI", "Volume Ratio",
             "CH_Status", "CH_Score", "CH_Bars_Since", "CH_PriorRise_%",
             "DT_Status", "DT_Score", "DT_Bars_Since",
             "Perf_1Y_%", "Perf_3Y_%", "Perf_5Y_%", "Run_Date"]
ordered = [c for c in COL_ORDER if c in show.columns]
extras = [c for c in show.columns if c not in ordered]
show = show[ordered + extras]

selection = st.dataframe(
    show,
    column_config={
        "Chart": st.column_config.LinkColumn("Chart", display_text="📈 Open"),
        "Best_Score": st.column_config.ProgressColumn("Best Score", min_value=0, max_value=100, format="%d"),
        "Prezzo": st.column_config.NumberColumn("Price"),
        "CH_Score": st.column_config.NumberColumn("CH Score"),
        "DT_Score": st.column_config.NumberColumn("DT Score"),
        "Perf_1Y_%": st.column_config.NumberColumn("Perf 1Y %", format="%.1f"),
        "Perf_3Y_%": st.column_config.NumberColumn("Perf 3Y %", format="%.1f"),
        "Perf_5Y_%": st.column_config.NumberColumn("Perf 5Y %", format="%.1f"),
        "CH_PriorRise_%": st.column_config.NumberColumn(
            "Prior Rise %", format="%.1f",
            help="Rise into the left rim over the prior 50 bars — O'Neil wants ≥30%"),
    },
    use_container_width=True,
    hide_index=True,
    height=450,
    on_select="rerun",
    selection_mode="single-row",
)

# --- Selected ticker: from clicked row, selectbox fallback ---
sel = None
sel_rows = selection.selection.rows if selection and selection.selection else []
if sel_rows:
    sel = fdf.iloc[sel_rows[0]]["Ticker"]

if sel is None:
    st.info("No row selected — pick a ticker below or click a row in the table.")
    sel = st.selectbox("Ticker", fdf["Ticker"].tolist())

row = fdf[fdf["Ticker"] == sel].iloc[0]

# ================= INFO SECTION (Stocks vs ETFs) =================

st.divider()

IS_ETF_UNIVERSE = source_name == "Sector ETFs"

if IS_ETF_UNIVERSE:
    # ---------------- ETF DEDICATED SECTION ----------------
    with st.spinner(f"Loading {sel} data..."):
        etf = fetch_etf_data(sel)

    title_name = etf["name"] or sel
    st.subheader(f"🧺 {title_name}  ·  {sel}")
    if etf["category"]:
        st.caption(etf["category"])

    if etf["summary"]:
        sentences = etf["summary"].split(". ")
        short = ". ".join(sentences[:2]).strip()
        if not short.endswith("."):
            short += "."
        st.markdown(short)
        if len(sentences) > 2:
            with st.expander("Full description"):
                st.write(etf["summary"])
    elif etf["error"]:
        st.caption(f"ETF info currently unavailable ({etf['error']}).")

    # --- ETF metrics: AUM, P/E, Expense ratio ---
    e1, e2, e3 = st.columns(3)
    e1.metric("AUM", fmt_cap(etf["aum"]))
    e2.metric("P/E (holdings)", fmt_num(etf["pe"]),
              help="Weighted trailing P/E of the underlying holdings")
    e3.metric("Expense ratio", fmt_pct(etf["expense_ratio"], 2),
              help="Annual fund operating expenses")

    # --- Holdings & exposure ---
    h1, h2 = st.columns(2)

    with h1:
        st.markdown("##### Top 10 holdings")
        th = etf["top_holdings"]
        if th is not None and len(th) > 0:
            th_show = th.copy().reset_index()
            # normalize column names across yfinance versions
            cols = {c.lower(): c for c in th_show.columns}
            pct_col = next((th_show[c] for c in th_show.columns
                            if "percent" in c.lower() or "weight" in c.lower()), None)
            if pct_col is not None:
                th_show["Weight %"] = (pct_col * 100).round(2)
            keep = [c for c in th_show.columns
                    if c.lower() in ("symbol", "holding name", "name", "index")] +                    (["Weight %"] if "Weight %" in th_show.columns else [])
            th_show = th_show[keep] if keep else th_show
            st.dataframe(th_show, use_container_width=True, hide_index=True, height=390)
        else:
            st.caption("Holdings data not available for this ETF.")

    with h2:
        st.markdown("##### Sector exposure")
        sw = etf["sector_weights"]
        if sw:
            sw_df = pd.DataFrame(
                {"Sector": [k.replace("_", " ").title() for k in sw.keys()],
                 "Weight %": [round(v * 100, 1) for v in sw.values()]}
            ).sort_values("Weight %", ascending=True)
            figsw = go.Figure(go.Bar(
                x=sw_df["Weight %"], y=sw_df["Sector"], orientation="h",
                marker_color="#5b7cfa",
                text=sw_df["Weight %"].map(lambda v: f"{v}%"), textposition="outside",
            ))
            figsw.update_layout(height=390, margin=dict(l=10, r=40, t=10, b=10),
                                xaxis_title="%")
            st.plotly_chart(figsw, use_container_width=True)
        else:
            st.caption("Sector exposure not available for this ETF.")

    st.caption("🌍 Geographic exposure is not available via free Yahoo Finance data — "
               "see the etf.com page below for full country breakdown and the underlying index.")

    st.link_button(f"📄 {sel} on etf.com (underlying index, exposure) ↗",
                   f"https://www.etf.com/{sel}")

else:
    # ---------------- STOCK SECTION (unchanged) ----------------
    with st.spinner(f"Loading {sel} data..."):
        fund = fetch_fundamentals(sel)

    title_name = fund["name"] or sel
    st.subheader(f"🏢 {title_name}  ·  {sel}")

    if fund["sector"] or fund["industry"]:
        st.caption(" · ".join(x for x in [fund["sector"], fund["industry"]] if x))

    if fund["summary"]:
        sentences = fund["summary"].split(". ")
        short = ". ".join(sentences[:2]).strip()
        if not short.endswith("."):
            short += "."
        st.markdown(short)
        if len(sentences) > 2:
            with st.expander("Full description"):
                st.write(fund["summary"])
    elif fund["error"]:
        st.caption(f"Company info currently unavailable ({fund['error']}).")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Market Cap", fmt_cap(fund["market_cap"]))
    m2.metric("P/E (trailing)", fmt_num(fund["pe"]))
    m3.metric("P/E (forward)", fmt_num(fund["fwd_pe"]),
              help="Price / expected next-12-months earnings (analyst estimates)")
    m4.metric("P/S (ttm)", fmt_num(fund["ps"]))

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("ROE", fmt_pct(fund["roe"]),
              help="Return on Equity — net income / shareholders' equity")
    m6.metric("Equity ratio", fmt_pct(fund["equity_ratio"]),
              help="Shareholders' equity / total assets — balance sheet strength")
    m7.metric("Earning power", fmt_pct(fund["earning_power"]),
              help="EBIT / total assets (Graham) — return on invested capital")
    m8.metric("Long term debt", fmt_cap(fund["lt_debt"]),
              help="Long-term debt (latest fiscal year)")

    m9, m10, m11, m12 = st.columns(4)
    m9.metric("FCF yield", fmt_pct(fund["fcf_yield"]),
              help="Free Cash Flow / Market Cap")
    m10.metric("FCF growth YoY", fmt_pct(fund["fcf_growth_yoy"]),
               delta=fmt_pct(fund["fcf_growth_yoy"]) if fund["fcf_growth_yoy"] is not None else None,
               help="Free Cash Flow change vs previous fiscal year (n/a if prior-year FCF was negative)")
    m11.metric("FCF (latest FY)", fmt_cap(fund["fcf"]))
    m12.metric("Next earnings", fund["next_earnings"] or "n/a",
               help="Next scheduled earnings report date (Yahoo Finance)")

    st.link_button("📄 Financial statements on TradingView ↗",
                   tv_financials_url(sel, fund["exchange"]))

    # ---- Financial history charts ----
    fh = fetch_financial_history(sel)
    if fh is not None and not fh.empty:
        st.markdown("##### 📊 Financial history (annual)")
        g1, g2 = st.columns(2)

        with g1:
            fig1 = go.Figure()
            if "Revenue" in fh.columns:
                fig1.add_bar(x=fh.index, y=fh["Revenue"], name="Revenue",
                             marker_color="#5b7cfa")
            if "NetIncome" in fh.columns:
                fig1.add_bar(x=fh.index, y=fh["NetIncome"], name="Net income",
                             marker_color="#4dd0e1")
            if "NetMargin_%" in fh.columns:
                fig1.add_scatter(x=fh.index, y=fh["NetMargin_%"], name="Net margin %",
                                 mode="lines+markers", yaxis="y2",
                                 line=dict(color="#f59e0b", width=2))
            fig1.update_layout(
                title="Growth & Profitability",
                barmode="group", height=380,
                yaxis=dict(title="USD"),
                yaxis2=dict(title="%", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=-0.25),
                margin=dict(l=10, r=10, t=45, b=10),
            )
            st.plotly_chart(fig1, use_container_width=True)

        with g2:
            fig2 = go.Figure()
            if "Debt" in fh.columns:
                fig2.add_bar(x=fh.index, y=fh["Debt"], name="Debt",
                             marker_color="#ec6a9c")
            if "FCF" in fh.columns:
                fig2.add_bar(x=fh.index, y=fh["FCF"], name="Free cash flow",
                             marker_color="#26c6da")
            fig2.update_layout(
                title="Financial health",
                barmode="group", height=380,
                yaxis=dict(title="USD"),
                legend=dict(orientation="h", y=-0.25),
                margin=dict(l=10, r=10, t=45, b=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.caption("Annual figures from Yahoo Finance statements. "
                   "Note: free data covers only the last ~4 fiscal years, "
                   "not the full 10-year history shown by paid providers.")

# ================= CHART (automatic) =================

st.divider()
st.subheader(f"📈 Chart · {sel}")

with st.spinner(f"Fetching {sel} prices..."):
    hist = fetch_history(sel)

if hist is None or hist.empty:
    st.error("Price data unavailable for this ticker (Yahoo and Stooq unreachable). "
             "Use the TradingView link below.")
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
    st.caption("EOD data; when loaded from Stooq it may differ slightly from Yahoo "
               "(dividend adjustment). Rim/Neckline levels come from the screener.")

st.link_button(f"Open {sel} on TradingView ↗",
               f"https://www.tradingview.com/chart/?symbol={tv_symbol(sel)}")

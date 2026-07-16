# ==============================================
# USA STOCK SCREENER EOD - VERSIONE 4
# Multi-timeframe: Daily / Weekly / 4H
# Versione GitHub Actions: output CSV in data/
# ==============================================

import os
import time
import io

import yfinance as yf
import pandas as pd
import numpy as np
import requests

from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator

from datetime import datetime

# ==============================================
# PARAMETRI PATTERN (detection loose, come Pine)
# ==============================================

PIV_LEN_CH       = 5
RIM_TOL_PCT      = 3.0
MIN_DEPTH_PCT    = 6.0
MAX_DEPTH_PCT    = 40.0
MIN_CUP_BARS     = 25
MAX_CUP_BARS     = 200
CENTER_BOTTOM    = True
MIN_HANDLE_BARS  = 3
MAX_HANDLE_BARS  = 40
MAX_HANDLE_RETR  = 50.0

PIV_LEN_DT       = 5
PEAK_TOL_PCT     = 3.0
MIN_VALLEY_PCT   = 10.0
MIN_SEP_BARS     = 12
MAX_SEP_BARS     = 120
USE_APEX         = True
USE_TREND        = True
TREND_LOOKBACK   = 50
TREND_RISE_PCT   = 10.0

RECENT_BARS      = 10

# Soglie BOOK (score)
BOOK_MIN_D    = 12.0
BOOK_MAX_D    = 33.0
BOOK_MIN_CUP  = 35
BOOK_MAX_RETR = 33.0
BOOK_MIN_HND  = 5
BOOK_HND_VOL  = 1.0
BOOK_VOL_MULT = 1.4

DT_TIGHT_PCT  = 1.5
DT_DEEP_PCT   = 15.0
DT_SWEET_LO   = 20
DT_SWEET_HI   = 65
DT_BKD_VOL    = 1.4

# ==============================================
# TIMEFRAMES
# ==============================================

TIMEFRAMES = {
    "Daily":  {"interval": "1d",  "period": "2y",   "resample": None,  "recent_bars": 10, "min_bars": 250},
    "Weekly": {"interval": "1wk", "period": "5y",   "resample": None,  "recent_bars": 4,  "min_bars": 150},
    "4H":     {"interval": "1h",  "period": "720d", "resample": "4h",  "recent_bars": 30, "min_bars": 250},
}

# ==============================================
# LISTA TITOLI (S&P 500)
# ==============================================

try:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers, timeout=15)
    resp.raise_for_status()
    sp500_table = pd.read_html(io.StringIO(resp.text))
    sp500_df = sp500_table[0]
    tickers = sp500_df['Symbol'].tolist()
    tickers = [t.replace('.', '-') for t in tickers]
    print(f"Caricati {len(tickers)} ticker S&P 500 da Wikipedia.")
except Exception as e:
    print(f"Errore Wikipedia: {e}. Uso la lista statica.")
    tickers = [
        "MMM","AOS","ABT","ABBV","ACN","ADBE","AMD","AES","AFL","A","APD","ABNB","AKAM","ALB","ARE",
        "ALGN","ALLE","LNT","ALL","GOOGL","GOOG","MO","AMZN","AMCR","AEE","AEP","AXP","AIG","AMT","AWK",
        "AMP","AME","AMGN","APH","ADI","ANSS","AON","APA","APO","AAPL","AMAT","APTV","ACGL","ADM","ANET",
        "AJG","AIZ","T","ATO","ADSK","ADP","AZO","AVB","AVY","AXON","BKR","BALL","BAC","BAX","BDX","BRK-B",
        "BBY","TECH","BIIB","BLK","BX","BK","BA","BKNG","BWA","BSX","BMY","AVGO","BR","BRO","BF-B","BLDR",
        "BG","BXP","CHRW","CDNS","CZR","CPT","CPB","COF","CAH","KMX","CCL","CARR","CAT","CBOE","CBRE",
        "CDW","CE","COR","CNC","CNP","CF","CRL","SCHW","CHTR","CVX","CMG","CB","CHD","CI","CINF","CTAS",
        "CSCO","C","CFG","CLX","CME","CMS","KO","CTSH","COIN","CL","CMCSA","CAG","COP","ED","STZ","CEG",
        "COO","CPRT","GLW","CPAY","CTVA","CSGP","COST","CTRA","CRWD","CCI","CSX","CMI","CVS","DHR","DRI",
        "DVA","DAY","DECK","DE","DELL","DAL","DVN","DXCM","FANG","DLR","DFS","DG","DLTR","D","DPZ","DOV",
        "DOW","DHI","DTE","DUK","DD","EMN","ETN","EBAY","ECL","EIX","EW","EA","ELV","EMR","ENPH","ETR",
        "EOG","EPAM","EQT","EFX","EQIX","EQR","ERIE","ESS","EL","EG","EVRG","ES","EXC","EXPE","EXPD","EXR",
        "XOM","FFIV","FDS","FICO","FAST","FRT","FDX","FIS","FITB","FSLR","FE","FI","FMC","F","FTNT","FTV",
        "FOXA","FOX","BEN","FCX","GRMN","IT","GE","GEHC","GEV","GEN","GNRC","GD","GIS","GM","GPC","GILD",
        "GPN","GL","GDDY","GS","HAL","HIG","HAS","HCA","DOC","HSIC","HSY","HES","HPE","HLT","HOLX","HD",
        "HON","HRL","HST","HWM","HPQ","HUBB","HUM","HBAN","HII","IBM","IEX","IDXX","ITW","INCY","IR",
        "PODD","INTC","ICE","IFF","IP","IPG","INTU","ISRG","IVZ","INVH","IQV","IRM","JBHT","JBL","JKHY",
        "J","JNJ","JCI","JPM","JNPR","K","KVUE","KDP","KEY","KEYS","KMB","KIM","KMI","KKR","KLAC","KHC",
        "KR","LHX","LH","LRCX","LW","LVS","LDOS","LEN","LII","LLY","LIN","LYV","LKQ","LMT","L","LOW","LULU",
        "LYB","MTB","MPC","MKTX","MAR","MMC","MLM","MAS","MA","MTCH","MKC","MCD","MCK","MDT","MRK","META",
        "MET","MTD","MGM","MCHP","MU","MSFT","MAA","MRNA","MHK","MOH","TAP","MDLZ","MPWR","MNST","MCO",
        "MS","MOS","MSI","MSCI","NDAQ","NTAP","NFLX","NEM","NWSA","NWS","NEE","NKE","NI","NDSN","NSC","NTRS",
        "NOC","NCLH","NRG","NUE","NVDA","NVR","NXPI","ORLY","OXY","ODFL","OMC","ON","OKE","ORCL","OTIS",
        "PCAR","PKG","PLTR","PANW","PARA","PH","PAYX","PAYC","PYPL","PNR","PEP","PFE","PCG","PM","PSX",
        "PNW","PNC","POOL","PPG","PPL","PFG","PG","PGR","PLD","PRU","PEG","PTC","PSA","PHM","QRVO","PWR",
        "QCOM","DGX","RL","RJF","RTX","O","REG","REGN","RF","RSG","RMD","RVTY","ROK","ROL","ROP","ROST",
        "RCL","SPGI","CRM","SBAC","SLB","STX","SRE","NOW","SHW","SPG","SWKS","SJM","SW","SNA","SOLV","SO",
        "LUV","SWK","SBUX","STT","STLD","STE","SYK","SMCI","SYF","SNPS","SYY","TMUS","TROW","TTWO","TPR",
        "TRGP","TGT","TEL","TDY","TFX","TER","TSLA","TXN","TPL","TXT","TMO","TJX","TKO","TSCO","TT","TDG",
        "TRV","TRMB","TFC","TYL","TSN","USB","UBER","UDR","ULTA","UNP","UAL","UPS","URI","UNH","UHS","VLO",
        "VTR","VLTO","VRSN","VRSK","VZ","VRTX","VTRS","VICI","V","VST","VMC","WRB","GWW","WAB","WBA","WMT",
        "DIS","WBD","WM","WAT","WEC","WFC","WELL","WST","WDC","WY","WMB","WTW","WYNN","XEL","XYL","YUM",
        "ZBRA","ZBH","ZTS"
    ]
    print(f"Utilizzata la lista statica di {len(tickers)} ticker.")


# ==============================================
# DOWNLOAD DATI (con retry anti rate-limit)
# ==============================================

def download_data(ticker, interval="1d", period="2y", resample=None, retries=3):
    for attempt in range(retries):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False)
            if df.empty:
                raise ValueError("empty")
            df.dropna(inplace=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            if resample is not None:
                df = df.resample(resample, origin="start").agg({
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                }).dropna()

            return df
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return None


def add_indicators(df):
    close = df["Close"]
    df["EMA50"]  = EMAIndicator(close, window=50).ema_indicator()
    df["EMA200"] = EMAIndicator(close, window=200).ema_indicator()
    df["RSI"]    = RSIIndicator(close, window=14).rsi()
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["VOL_AVG50"] = df["Volume"].rolling(50).mean()
    df["VOL_RATIO"] = df["Volume"] / df["VOL_AVG20"]
    return df


# ==============================================
# PERFORMANCE PREZZO 1/3/5 ANNI
# (download extra solo per i ticker con pattern)
# ==============================================

_perf_cache = {}

def get_performance(ticker):
    """Ritorna (perf_1y, perf_3y, perf_5y) in %, None se non calcolabile."""
    if ticker in _perf_cache:
        return _perf_cache[ticker]

    perfs = (None, None, None)
    try:
        h = yf.download(ticker, period="5y", interval="1wk",
                        auto_adjust=True, progress=False)
        if h is not None and not h.empty:
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.droplevel(1)
            close = h["Close"].dropna()
            if len(close) > 0:
                last = float(close.iloc[-1])
                last_date = close.index[-1]

                def perf_years(y):
                    target = last_date - pd.DateOffset(years=y)
                    past = close[close.index <= target]
                    if len(past) == 0:
                        return None
                    base = float(past.iloc[-1])
                    return round((last / base - 1) * 100, 1) if base > 0 else None

                perfs = (perf_years(1), perf_years(3), perf_years(5))
    except Exception:
        pass

    _perf_cache[ticker] = perfs
    return perfs


def pivot_highs(high, low, pivlen):
    n = len(high)
    piv = []
    h = high.values
    for i in range(pivlen, n - pivlen):
        window = h[i - pivlen: i + pivlen + 1]
        if h[i] == window.max() and (window == h[i]).sum() == 1:
            piv.append((i, h[i]))
    return piv


def avg_vol_around(volume, idx, k=2):
    n = len(volume)
    lo = max(0, idx - k)
    hi = min(n - 1, idx + k)
    seg = volume.iloc[lo:hi + 1]
    return seg.mean() if len(seg) > 0 else np.nan


# ==============================================
# CUP & HANDLE
# ==============================================

def detect_cup_handle(df, recent_bars=RECENT_BARS):
    if len(df) < MIN_CUP_BARS + PIV_LEN_CH + 5:
        return None

    high = df["High"].reset_index(drop=True)
    low  = df["Low"].reset_index(drop=True)
    close = df["Close"].reset_index(drop=True)
    n = len(close)
    last_idx = n - 1

    pivots = pivot_highs(high, low, PIV_LEN_CH)
    if len(pivots) < 2:
        return None

    for j in range(len(pivots) - 1, -1, -1):
        right_idx, right_val = pivots[j]
        if last_idx - right_idx > MAX_HANDLE_BARS + 5:
            continue

        for i in range(j - 1, -1, -1):
            left_idx, left_val = pivots[i]
            span = right_idx - left_idx
            if span > MAX_CUP_BARS:
                break
            if span < MIN_CUP_BARS:
                continue
            if abs(right_val - left_val) / left_val * 100 > RIM_TOL_PCT:
                continue

            segment_low  = low.iloc[left_idx:right_idx + 1]
            segment_high = high.iloc[left_idx + 1:right_idx]
            bottom_idx_rel = segment_low.values.argmin()
            bottom_idx = left_idx + bottom_idx_rel
            bottom_val = segment_low.iloc[bottom_idx_rel]

            rim = max(left_val, right_val)
            depth_pct = (rim - bottom_val) / rim * 100
            if not (MIN_DEPTH_PCT <= depth_pct <= MAX_DEPTH_PCT):
                continue
            if not segment_high.empty and segment_high.max() > rim:
                continue
            if CENTER_BOTTOM:
                if not (left_idx + span * 0.2 <= bottom_idx <= right_idx - span * 0.2):
                    continue

            handle_bars = last_idx - right_idx
            if handle_bars < 0:
                continue
            handle_low = right_val if handle_bars == 0 else low.iloc[right_idx + 1:last_idx + 1].min()

            cup_depth = rim - bottom_val
            retr_pct = (rim - handle_low) / cup_depth * 100 if cup_depth > 0 else 999

            if retr_pct > MAX_HANDLE_RETR or handle_bars > MAX_HANDLE_BARS or close.iloc[last_idx] < bottom_val:
                continue

            last_close = close.iloc[last_idx]

            if last_close > rim and handle_bars >= MIN_HANDLE_BARS:
                breakout_idx = None
                for k in range(right_idx + MIN_HANDLE_BARS, last_idx + 1):
                    if close.iloc[k] > rim:
                        breakout_idx = k
                        break
                if breakout_idx is not None and (last_idx - breakout_idx) <= recent_bars:
                    return {
                        "status": "BREAKOUT",
                        "rim": rim, "depth_pct": depth_pct, "cup_bars": span,
                        "handle_bars": breakout_idx - right_idx,
                        "handle_retr_pct": retr_pct,
                        "bars_since": last_idx - breakout_idx,
                        "left_idx": left_idx, "right_idx": right_idx,
                        "breakout_idx": breakout_idx, "last_idx": last_idx,
                    }
            elif last_close <= rim:
                return {
                    "status": "FORMING",
                    "rim": rim, "depth_pct": depth_pct, "cup_bars": span,
                    "handle_bars": handle_bars, "handle_retr_pct": retr_pct,
                    "bars_since": handle_bars,
                    "left_idx": left_idx, "right_idx": right_idx,
                    "breakout_idx": None, "last_idx": last_idx,
                }
    return None


# ==============================================
# DOUBLE TOP
# ==============================================

def detect_double_top(df, recent_bars=RECENT_BARS):
    if len(df) < MIN_SEP_BARS + PIV_LEN_DT + 5:
        return None

    high = df["High"].reset_index(drop=True)
    low  = df["Low"].reset_index(drop=True)
    close = df["Close"].reset_index(drop=True)
    volume = df["Volume"].reset_index(drop=True)
    n = len(close)
    last_idx = n - 1

    pivots = pivot_highs(high, low, PIV_LEN_DT)
    if len(pivots) < 2:
        return None

    for j in range(len(pivots) - 1, -1, -1):
        t2_idx, t2_val = pivots[j]
        if last_idx - t2_idx > MAX_SEP_BARS + recent_bars:
            continue

        for i in range(j - 1, -1, -1):
            t1_idx, t1_val = pivots[i]
            sep = t2_idx - t1_idx
            if sep > MAX_SEP_BARS:
                break
            if sep < MIN_SEP_BARS:
                continue

            hi_top = max(t1_val, t2_val)
            if abs(t1_val - t2_val) / hi_top * 100 > PEAK_TOL_PCT:
                continue

            mid_low_seg  = low.iloc[t1_idx + 1:t2_idx]
            mid_high_seg = high.iloc[t1_idx + 1:t2_idx]
            if mid_low_seg.empty:
                continue

            neckline = mid_low_seg.min()
            valley_pct = (hi_top - neckline) / hi_top * 100
            if valley_pct < MIN_VALLEY_PCT:
                continue
            if not mid_high_seg.empty and mid_high_seg.max() > hi_top:
                continue

            if USE_APEX or USE_TREND:
                lkb = min(TREND_LOOKBACK, t1_idx)
                if lkb <= 0:
                    continue
                prior_hi = high.iloc[t1_idx - lkb:t1_idx].max()
                prior_lo = low.iloc[t1_idx - lkb:t1_idx].min()
                if USE_APEX and t1_val < prior_hi:
                    continue
                if USE_TREND:
                    if prior_lo <= 0:
                        continue
                    if (t1_val - prior_lo) / prior_lo * 100 < TREND_RISE_PCT:
                        continue

            lo_top = min(t1_val, t2_val)
            last_close = close.iloc[last_idx]

            invalidated = (close.iloc[t2_idx + 1:last_idx + 1] > lo_top).any()
            if invalidated:
                continue

            v1 = avg_vol_around(volume, t1_idx)
            v2 = avg_vol_around(volume, t2_idx)
            vchg = (v2 / v1 - 1) * 100 if (v1 and v1 > 0 and not np.isnan(v2)) else np.nan

            if last_close < neckline:
                confirm_idx = None
                for k in range(t2_idx, last_idx + 1):
                    if close.iloc[k] < neckline:
                        confirm_idx = k
                        break
                if confirm_idx is not None and (last_idx - confirm_idx) <= recent_bars:
                    return {
                        "status": "CONFIRMED", "neckline": neckline,
                        "diff_pct": abs(t1_val - t2_val) / hi_top * 100,
                        "valley_pct": valley_pct, "sep_bars": sep,
                        "bars_since": last_idx - confirm_idx,
                        "t1_idx": t1_idx, "t2_idx": t2_idx,
                        "confirm_idx": confirm_idx, "last_idx": last_idx,
                        "vchg": vchg,
                    }
            else:
                if (last_idx - t2_idx) > MAX_SEP_BARS:
                    continue
                return {
                    "status": "PENDING", "neckline": neckline,
                    "diff_pct": abs(t1_val - t2_val) / hi_top * 100,
                    "valley_pct": valley_pct, "sep_bars": sep,
                    "bars_since": last_idx - t2_idx,
                    "t1_idx": t1_idx, "t2_idx": t2_idx,
                    "confirm_idx": None, "last_idx": last_idx,
                    "vchg": vchg,
                }
    return None


# ==============================================
# BOOK SCORE
# ==============================================

def score_cup_handle(df, ch):
    if ch is None:
        return None

    close = df["Close"].reset_index(drop=True)
    volume = df["Volume"].reset_index(drop=True)
    vol_avg50 = df["VOL_AVG50"].reset_index(drop=True)

    right_idx = ch["right_idx"]
    end_idx = ch["breakout_idx"] if ch["breakout_idx"] is not None else ch["last_idx"]
    handle_bars = end_idx - right_idx
    live = ch["status"] == "FORMING"

    v_depth = 1 if BOOK_MIN_D <= ch["depth_pct"] <= BOOK_MAX_D else 0
    v_cupl  = 1 if ch["cup_bars"] >= BOOK_MIN_CUP else 0
    v_retr  = 1 if ch["handle_retr_pct"] <= BOOK_MAX_RETR else 0
    v_hndl  = -1 if (live and handle_bars < BOOK_MIN_HND) else (1 if handle_bars >= BOOK_MIN_HND else 0)

    hnd_x = np.nan
    wedge_ok = -1
    if handle_bars > 1:
        hnd_slice_vol = volume.iloc[right_idx + 1:end_idx + 1]
        v50_now = vol_avg50.iloc[end_idx]
        if len(hnd_slice_vol) > 0 and v50_now and v50_now > 0 and not np.isnan(v50_now):
            hnd_x = hnd_slice_vol.mean() / v50_now

        half = right_idx + max(1, handle_bars // 2)
        first = close.iloc[right_idx + 1:half + 1]
        second = close.iloc[half + 1:end_idx + 1]
        if len(first) > 0 and len(second) > 0:
            wedge_ok = 0 if second.mean() > first.mean() else 1

    v_hvol = -1 if np.isnan(hnd_x) else (1 if hnd_x <= BOOK_HND_VOL else 0)

    if live:
        v_bkv = -1
    else:
        v50_now = vol_avg50.iloc[end_idx]
        bk_x = volume.iloc[end_idx] / v50_now if (v50_now and v50_now > 0) else np.nan
        v_bkv = -1 if np.isnan(bk_x) else (1 if bk_x >= BOOK_VOL_MULT else 0)

    weights = [(v_depth, 12), (v_cupl, 8), (v_retr, 20), (v_hndl, 8), (v_hvol, 15), (wedge_ok, 12), (v_bkv, 25)]
    earned = sum(w for v, w in weights if v == 1)
    denom  = sum(w for v, w in weights if v >= 0)
    return round(earned * 100.0 / denom) if denom > 0 else 0


def score_double_top(df, dt):
    if dt is None:
        return None

    volume = df["Volume"].reset_index(drop=True)
    vol_avg50 = df["VOL_AVG50"].reset_index(drop=True)

    v_vchg  = -1 if np.isnan(dt["vchg"]) else (1 if dt["vchg"] <= 0 else 0)
    v_tight = 1 if dt["diff_pct"] <= DT_TIGHT_PCT else 0
    v_deep  = 1 if dt["valley_pct"] >= DT_DEEP_PCT else 0
    v_sweet = 1 if DT_SWEET_LO <= dt["sep_bars"] <= DT_SWEET_HI else 0

    weights = [(v_vchg, 25), (v_tight, 15), (v_deep, 15), (v_sweet, 15)]

    if dt["status"] == "CONFIRMED":
        c_idx = dt["confirm_idx"]
        v50_now = vol_avg50.iloc[c_idx]
        bkd_x = volume.iloc[c_idx] / v50_now if (v50_now and v50_now > 0) else np.nan
        v_bkdv = -1 if np.isnan(bkd_x) else (1 if bkd_x >= DT_BKD_VOL else 0)
        weights.append((v_bkdv, 30))

    earned = sum(w for v, w in weights if v == 1)
    denom  = sum(w for v, w in weights if v >= 0)
    return round(earned * 100.0 / denom) if denom > 0 else 0


# ==============================================
# MOTORE PRINCIPALE — loop sui timeframes
# ==============================================

def run_screener(tf_name, cfg):
    results = []
    min_bars = cfg["min_bars"]
    recent_bars = cfg["recent_bars"]

    print(f"\n=== Analisi timeframe: {tf_name} ===")
    for idx, ticker in enumerate(tickers):
        if idx % 50 == 0:
            print(f"  ... {idx}/{len(tickers)}")

        df = download_data(ticker, interval=cfg["interval"],
                           period=cfg["period"], resample=cfg["resample"])
        if df is None or len(df) < min_bars:
            continue

        df = add_indicators(df)

        ch = detect_cup_handle(df, recent_bars=recent_bars)
        dt = detect_double_top(df, recent_bars=recent_bars)
        if ch is None and dt is None:
            continue

        ch_score = score_cup_handle(df, ch)
        dt_score = score_double_top(df, dt)

        perf_1y, perf_3y, perf_5y = get_performance(ticker)

        row = {
            "Ticker": ticker,
            "Timeframe": tf_name,
            "Prezzo": round(float(df["Close"].iloc[-1]), 2),
            "RSI": round(float(df["RSI"].iloc[-1]), 2),
            "Volume Ratio": round(float(df["VOL_RATIO"].iloc[-1]), 2),

            "CH_Status": ch["status"] if ch else None,
            "CH_Score": ch_score,
            "CH_Rim": round(ch["rim"], 2) if ch else None,
            "CH_Depth_%": round(ch["depth_pct"], 1) if ch else None,
            "CH_Cup_Bars": ch["cup_bars"] if ch else None,
            "CH_Handle_Bars": ch["handle_bars"] if ch else None,
            "CH_Handle_Retr_%": round(ch["handle_retr_pct"], 1) if ch else None,
            "CH_Bars_Since": ch["bars_since"] if ch else None,

            "DT_Status": dt["status"] if dt else None,
            "DT_Score": dt_score,
            "DT_Neckline": round(dt["neckline"], 2) if dt else None,
            "DT_Diff_%": round(dt["diff_pct"], 1) if dt else None,
            "DT_Valley_%": round(dt["valley_pct"], 1) if dt else None,
            "DT_Sep_Bars": dt["sep_bars"] if dt else None,
            "DT_Bars_Since": dt["bars_since"] if dt else None,

            "Perf_1Y_%": perf_1y,
            "Perf_3Y_%": perf_3y,
            "Perf_5Y_%": perf_5y,

            "Best_Score": max([s for s in [ch_score, dt_score] if s is not None], default=0),
        }
        results.append(row)
        print(f"  [OK] {ticker}: CH={row['CH_Status']} DT={row['DT_Status']} Best={row['Best_Score']}")

    return pd.DataFrame(results)


# ==============================================
# ESECUZIONE — un CSV per timeframe in data/
# ==============================================

os.makedirs("data", exist_ok=True)
run_date = datetime.now().strftime("%Y-%m-%d")

for tf_name, cfg in TIMEFRAMES.items():
    results_df = run_screener(tf_name, cfg)

    if not results_df.empty:
        results_df.sort_values("Best_Score", ascending=False, inplace=True)
        results_df["Run_Date"] = run_date

    out = f"data/stocks_{tf_name}.csv"
    results_df.to_csv(out, index=False)
    print(f"[{tf_name}] Salvato {out} — {len(results_df)} titoli con pattern.")

print("\nAnalisi completata su tutti i timeframe.")

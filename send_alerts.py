# ==============================================
# TELEGRAM ALERTS
# Legge i CSV generati dagli screener e invia
# alert SOLO per:
#  - Cup & Handle in BREAKOUT (bars_since <= 1)
#  - Double Top in PENDING, secondo top appena
#    confermato (bars_since <= PIVLEN+1 = 6; il
#    pivot richiede 5 barre per essere confermato)
# Dedup via data/alerts_state.json (committato).
# Secrets richiesti (GitHub Actions):
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# ==============================================

import os
import json
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

# --- Soglie alert ---
CH_BREAKOUT_MAX_BARS = 1   # breakout: evento immediato

# Il secondo top (T2) e' rilevabile solo PIVLEN barre dopo il massimo
# (conferma del pivot, identica al Pine che stampa "T2?" in quel momento).
# Alert quindi nella finestra [PIVLEN, PIVLEN + max delay]:
#   bars_since = 5 -> T2 stampato ora; = 6 -> stampato 1 barra fa.
DT_PIVLEN            = 5
DT_MAX_DETECT_DELAY  = 1
DTZ_TOUCH_MAX_BARS   = 1     # tocco della zona T2: alert entro 1 barra
SEND_T2_CONFIRMED    = True  # False per silenziare l'alert alla conferma pivot
STATE_EXPIRY_DAYS    = 15  # dopo N giorni un segnale puo' ri-allertare

SOURCES = {
    "Stocks Daily":  "data/stocks_Daily.csv",
    "Stocks Weekly": "data/stocks_Weekly.csv",
    "Stocks 4H":     "data/stocks_4H.csv",
    "Sector ETFs":   "data/etf_sector.csv",
}

STATE_FILE = "data/alerts_state.json"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


def now_stamps():
    utc = datetime.now(timezone.utc)
    rome = utc + timedelta(hours=2)  # CEST; in inverno (CET) sara' +1
    return utc.strftime("%Y-%m-%d %H:%M UTC"), rome.strftime("%Y-%m-%d %H:%M")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    # elimina voci scadute
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STATE_EXPIRY_DAYS)).isoformat()
    state = {k: v for k, v in state.items() if v >= cutoff}
    os.makedirs("data", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    return state


def tg_send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID mancanti: alert non inviato.")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                return True
            print(f"[WARN] Telegram HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[WARN] Telegram error: {e}")
        time.sleep(2 * (attempt + 1))
    return False


def tv_link(ticker):
    return f"https://www.tradingview.com/chart/?symbol={ticker.replace('-', '.')}"


def collect_alerts():
    alerts = []
    for universe, path in SOURCES.items():
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty:
            continue

        for _, row in df.iterrows():
            ticker = row.get("Ticker")
            tf = row.get("Timeframe", "Daily")  # gli ETF non hanno la colonna

            # --- C&H BREAKOUT appena avvenuto ---
            ch_status = row.get("CH_Status")
            ch_bs = pd.to_numeric(row.get("CH_Bars_Since"), errors="coerce")
            if ch_status == "BREAKOUT" and pd.notna(ch_bs) and ch_bs <= CH_BREAKOUT_MAX_BARS:
                alerts.append({
                    "key": f"{universe}|{tf}|{ticker}|CH_BREAKOUT",
                    "universe": universe, "tf": tf, "ticker": ticker,
                    "kind": "🚀 <b>C&amp;H BREAKOUT</b>",
                    "score": row.get("CH_Score"),
                    "detail": f"rim {row.get('CH_Rim')} · depth {row.get('CH_Depth_%')}% · {int(ch_bs)}b ago",
                })

            # --- DT secondo top appena confermato (PENDING fresco) ---
            dt_status = row.get("DT_Status")
            dt_bs = pd.to_numeric(row.get("DT_Bars_Since"), errors="coerce")
            # --- Tocco zona T2 (anticipato, prima della conferma pivot) ---
            dtz_status = row.get("DTZ_Status")
            dtz_bs = pd.to_numeric(row.get("DTZ_Bars_Since"), errors="coerce")
            if dtz_status == "TOUCH" and pd.notna(dtz_bs) and dtz_bs <= DTZ_TOUCH_MAX_BARS:
                t1v = row.get("DTZ_T1")
                alerts.append({
                    "key": f"{universe}|{tf}|{ticker}|DTZ|{t1v}",
                    "universe": universe, "tf": tf, "ticker": ticker,
                    "kind": "🎯 <b>DT ZONE TOUCH — potential T2</b>",
                    "score": None,
                    "detail": f"T1 {t1v} · valley {row.get('DTZ_Valley_%')}% · sep {row.get('DTZ_Sep_Bars')}b · unconfirmed",
                })

            if SEND_T2_CONFIRMED and dt_status == "PENDING" and pd.notna(dt_bs) \
                    and DT_PIVLEN <= dt_bs <= DT_PIVLEN + DT_MAX_DETECT_DELAY:
                printed_ago = int(dt_bs) - DT_PIVLEN  # 0 = T2 stampato in questa barra
                when = "now" if printed_ago == 0 else f"{printed_ago}b ago"
                alerts.append({
                    "key": f"{universe}|{tf}|{ticker}|DT_PENDING",
                    "universe": universe, "tf": tf, "ticker": ticker,
                    "kind": "⏳ <b>DOUBLE TOP — T2 printed</b>",
                    "score": row.get("DT_Score"),
                    "detail": f"T2 printed {when} · neckline {row.get('DT_Neckline')} · valley {row.get('DT_Valley_%')}%",
                })
    return alerts


def main():
    utc_str, rome_str = now_stamps()
    state = load_state()
    alerts = collect_alerts()

    fresh = [a for a in alerts if a["key"] not in state]
    print(f"Segnali candidati: {len(alerts)} · nuovi (non gia' inviati): {len(fresh)}")

    if fresh:
        lines = [f"📊 <b>Precision Patterns</b> — run {rome_str} (Rome) · {utc_str}", ""]
        for a in fresh:
            score = f" · score {int(a['score'])}" if pd.notna(a.get("score")) else ""
            lines.append(
                f"{a['kind']} — <a href=\"{tv_link(a['ticker'])}\">{a['ticker']}</a> "
                f"[{a['universe']} · {a['tf']}]{score}\n{a['detail']}"
            )
            lines.append("")
        ok = tg_send("\n".join(lines).strip())
        if ok:
            now_iso = datetime.now(timezone.utc).isoformat()
            for a in fresh:
                state[a["key"]] = now_iso
            print(f"Inviati {len(fresh)} alert.")
        else:
            print("[WARN] invio fallito: lo stato non viene aggiornato (ritentera' al prossimo run).")
    else:
        print("Nessun nuovo segnale da inviare.")

    save_state(state)


if __name__ == "__main__":
    main()

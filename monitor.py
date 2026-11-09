#!/usr/bin/env python3
"""Monitor de preços LATAM: Uberlândia (UDI) -> Amsterdã (AMS).

Ida: 21/01/2027 | Volta: 30/01/2027 ou 31/01/2027.
Fonte de dados: SerpApi (Google Flights), filtrando a cia LATAM.
Histórico em SQLite; alerta (Telegram e/ou e-mail) quando o preço cai
ou fica abaixo do preço-alvo.
"""
import json
import os
import smtplib
import sqlite3
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import requests

BASE = Path(__file__).parent
DB_PATH = BASE / "prices.db"

ORIGIN = "UDI"
DEST = "AMS"
OUTBOUND = "2027-01-21"
RETURNS = ["2027-01-30", "2027-01-31"]
CURRENCY = "BRL"
AIRLINE_CODE = "LA"          # código IATA da LATAM (também aceita JJ no filtro local)
AIRLINE_NAME = "LATAM"

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
TARGET_PRICE = float(os.getenv("TARGET_PRICE", "0"))  # 0 = só alerta em queda
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at TEXT NOT NULL,
            outbound TEXT NOT NULL,
            inbound TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT NOT NULL,
            airlines TEXT,
            stops INTEGER,
            details TEXT
        )"""
    )
    return con


def fetch(return_date):
    params = {
        "engine": "google_flights",
        "departure_id": ORIGIN,
        "arrival_id": DEST,
        "outbound_date": OUTBOUND,
        "return_date": return_date,
        "type": "1",  # ida e volta
        "currency": CURRENCY,
        "hl": "pt",
        "gl": "br",
        "include_airlines": AIRLINE_CODE,
        "api_key": SERPAPI_KEY,
    }
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("error") and "hasn't returned any results" not in data["error"]:
        raise RuntimeError(data["error"])
    return data


def best_latam_offer(data):
    """Menor oferta em que todos os trechos são operados/vendidos pela LATAM."""
    offers = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    candidates = []
    for o in offers:
        legs = o.get("flights", [])
        if not legs or "price" not in o:
            continue
        # aceita itinerário se ao menos um trecho for LATAM (ex.: codeshare/parceiros)
        if not any(AIRLINE_NAME.lower() in (l.get("airline", "")).lower() for l in legs):
            continue
        candidates.append(o)
    if not candidates:
        return None
    return min(candidates, key=lambda o: o["price"])


def summarize(offer):
    legs = offer["flights"]
    airlines = sorted({l.get("airline", "?") for l in legs})
    route = " > ".join(
        [legs[0]["departure_airport"]["id"]] + [l["arrival_airport"]["id"] for l in legs]
    )
    return {
        "price": float(offer["price"]),
        "airlines": ", ".join(airlines),
        "stops": len(legs) - 1,
        "details": json.dumps(
            {
                "route": route,
                "total_duration_min": offer.get("total_duration"),
                "flights": [l.get("flight_number") for l in legs],
            },
            ensure_ascii=False,
        ),
    }


def previous_best(con, inbound):
    row = con.execute(
        "SELECT MIN(price) FROM prices WHERE outbound=? AND inbound=?",
        (OUTBOUND, inbound),
    ).fetchone()
    return row[0]


def last_price(con, inbound):
    row = con.execute(
        "SELECT price FROM prices WHERE outbound=? AND inbound=? ORDER BY id DESC LIMIT 1",
        (OUTBOUND, inbound),
    ).fetchone()
    return row[0] if row else None


def notify(msg):
    print("\n[ALERTA]\n" + msg)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg},
            timeout=30,
        )
    if SMTP_HOST and EMAIL_TO:
        m = EmailMessage()
        m["Subject"] = "✈️ LATAM UDI→AMS: alerta de preço"
        m["From"] = SMTP_USER or EMAIL_TO
        m["To"] = EMAIL_TO
        m.set_content(msg)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(m)


def fmt(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    if not SERPAPI_KEY:
        sys.exit("Defina SERPAPI_KEY (veja .env.example).")
    con = db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    alerts = []

    for ret in RETURNS:
        try:
            offer = best_latam_offer(fetch(ret))
        except Exception as e:  # noqa: BLE001
            print(f"[{ret}] erro: {e}")
            continue
        if not offer:
            print(f"[{ret}] nenhuma oferta LATAM encontrada.")
            continue

        s = summarize(offer)
        prev_last = last_price(con, ret)
        prev_best = previous_best(con, ret)
        con.execute(
            "INSERT INTO prices (checked_at,outbound,inbound,price,currency,airlines,stops,details)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now, OUTBOUND, ret, s["price"], CURRENCY, s["airlines"], s["stops"], s["details"]),
        )
        con.commit()

        print(f"[{ret}] {fmt(s['price'])} | {s['airlines']} | {s['stops']} parada(s)")

        reasons = []
        if prev_last is not None and s["price"] < prev_last:
            reasons.append(f"caiu de {fmt(prev_last)}")
        if prev_best is not None and s["price"] < prev_best:
            reasons.append("novo MENOR preço histórico")
        if TARGET_PRICE and s["price"] <= TARGET_PRICE:
            reasons.append(f"abaixo do alvo ({fmt(TARGET_PRICE)})")
        if reasons:
            alerts.append(
                f"✈️ LATAM {ORIGIN}→{DEST}\n"
                f"Ida {OUTBOUND} | Volta {ret}\n"
                f"Preço: {fmt(s['price'])} ({'; '.join(reasons)})\n"
                f"{s['airlines']} • {s['stops']} parada(s)"
            )

    if alerts:
        notify("\n\n".join(alerts))
    con.close()


if __name__ == "__main__":
    main()

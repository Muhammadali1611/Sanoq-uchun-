# -*- coding: utf-8 -*-
"""
site_analysis.py — SAYT (CP Sklad index.html) HISOB MANTIG'INING PYTHON NUSXASI
===============================================================================
Saytdagi analyzeClientProduct() / statusOf() funksiyalari AYNAN ko'chirilgan,
shuning uchun guruhga boradigan raqamlar saytdagi raqamlar bilan 1:1 mos.

Hodisalar (bitta klent + bitta tovar uchun):
  initial  — boshlang'ich qoldiq (initialStock)
  delivery — biz klentga bergan yuk (sales)  -> qoldiqni OSHIRADI
  count    — agent sanog'i (counts)          -> haqiqiy qoldiq

Davr (interval): ikki kuzatuv (boshlang'ich/sanoq) orasida
  sotdi = oldingi qoldiq + berilgan yuk - yangi sanoq

Saytdagi kodni o'zgartirsangiz — shu faylni ham moslang.
"""
import datetime as dt

# Saytdagi konstantalar bilan bir xil (index.html: LOW_STOCK, FAST_COVER, ...)
LOW_STOCK = 30        # har bir mahsulotdan klentda kamida shuncha turishi kerak
FAST_COVER = 15
SLOW_COVER = 45
STUCK_DAYS = 21       # shuncha kun sotuv bo'lmasa -> turib qolgan

STATUS_LBL = {
    "tez": "🟢 Tez", "sekin": "🟠 Sekin", "turgan": "🔴 Turib qolgan",
    "normal": "⚪ Normal", "yangi": "🔵 Yangi",
}
_TYPE_ORD = {"initial": 0, "delivery": 1, "count": 2}


# ---------------------------------------------------------------------------
# Yordamchi
# ---------------------------------------------------------------------------
def uz_now() -> dt.datetime:
    """O'zbekiston vaqti (UTC+5, DST yo'q) — server qaysi zonada bo'lsa ham."""
    return dt.datetime.utcnow() + dt.timedelta(hours=5)


def today() -> str:
    return uz_now().strftime("%Y-%m-%d")


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _same(a, b) -> bool:
    """JS dagi `==` kabi: 67 == "67" -> True."""
    return a is not None and b is not None and str(a) == str(b)


def _t(r) -> str:
    """JS: dt(r) — saralash kaliti 'YYYY-MM-DD HH:MM'."""
    t = r.get("time")
    return f"{r.get('date')} {t}" if t else f"{r.get('date')} 00:00"


def days_between(a: str, b: str) -> int:
    """JS: Math.round((new Date(b)-new Date(a))/86400000)."""
    try:
        da = dt.date.fromisoformat(str(a)[:10])
        db = dt.date.fromisoformat(str(b)[:10])
        return (db - da).days
    except Exception:
        return 0


def fmt(n) -> str:
    """Butun son, mingliklar bo'shliq bilan: 12 500."""
    return f"{round(n or 0):,}".replace(",", " ")


def fmt1(n) -> str:
    v = round((n or 0) * 10) / 10
    return f"{v:g}"


def ddmm(date_str: str) -> str:
    try:
        return dt.date.fromisoformat(date_str[:10]).strftime("%d.%m")
    except Exception:
        return str(date_str or "")


# ---------------------------------------------------------------------------
# Asosiy tahlil — saytdagi analyzeClientProduct() nusxasi
# ---------------------------------------------------------------------------
def analyze_client_product(blob: dict, client_id, product_id, upto: str = None,
                           today_str: str = None) -> dict:
    upto = upto or "9999-12-31"
    today_str = today_str or today()

    init = next((s for s in blob.get("initialStock", [])
                 if _same(s.get("clientId"), client_id) and _same(s.get("productId"), product_id)), None)
    sales = [s for s in blob.get("sales", [])
             if _same(s.get("clientId"), client_id) and _same(s.get("productId"), product_id)
             and str(s.get("date") or "") <= upto]
    counts = [c for c in blob.get("counts", [])
              if _same(c.get("clientId"), client_id) and _same(c.get("productId"), product_id)
              and str(c.get("date") or "") <= upto]

    ev = []
    if init:
        ev.append({"t": _t(init), "date": init.get("date"), "time": init.get("time"),
                   "type": "initial", "qty": _num(init.get("qty")), "id": init.get("id")})
    for s in sales:
        ev.append({"t": _t(s), "date": s.get("date"), "time": s.get("time"),
                   "type": "delivery", "qty": _num(s.get("qty")), "id": s.get("id")})
    for c in counts:
        ev.append({"t": _t(c), "date": c.get("date"), "time": c.get("time"),
                   "type": "count", "qty": _num(c.get("qty")), "id": c.get("id"),
                   "agentId": c.get("agentId")})
    # JS sort barqaror (stable) — Python sort ham barqaror
    ev.sort(key=lambda e: (e["t"], _TYPE_ORD[e["type"]]))

    book = 0.0
    sold = 0.0
    delivered = 0.0
    started = False
    for e in ev:
        if e["type"] == "initial":
            book = e["qty"]
            started = True
        elif e["type"] == "delivery":
            book += e["qty"]
            delivered += e["qty"]
            started = True
        else:  # count
            if started:
                diff = e["qty"] - book
                if diff < -0.001:
                    sold += -diff
                elif diff > 0.001:
                    delivered += diff
            book = e["qty"]
            started = True

    # Davrlar — kuzatuvlar orasidagi aniq tahlil
    intervals = []
    prev_obs = None
    pend = 0.0
    pend_from = pend_to = None
    for e in ev:
        if e["type"] == "initial":
            prev_obs = {"date": e["date"], "time": e["time"], "qty": e["qty"]}
            pend, pend_from, pend_to = 0.0, None, None
        elif e["type"] == "delivery":
            pend += e["qty"]
            if not pend_from:
                pend_from = e["date"]
            pend_to = e["date"]
        else:
            if prev_obs or pend > 0:
                start_qty = prev_obs["qty"] if prev_obs else 0.0
                start_date = prev_obs["date"] if prev_obs else (pend_from or e["date"])
                raw = start_qty + pend - e["qty"]
                dys = max(days_between(start_date, e["date"]), 0)
                intervals.append({
                    "from": start_date,
                    "fromT": prev_obs["time"] if prev_obs else "",
                    "to": e["date"], "toT": e["time"],
                    "startQty": start_qty, "delivered": pend,
                    "delivFrom": pend_from, "delivTo": pend_to,
                    "endQty": e["qty"],
                    "sold": raw if raw > 0 else 0.0, "rawSold": raw,
                    "days": dys, "daily": (raw / dys) if (dys > 0 and raw > 0) else 0.0,
                    "countId": e["id"], "hasPrev": prev_obs is not None,
                })
            prev_obs = {"date": e["date"], "time": e["time"], "qty": e["qty"]}
            pend, pend_from, pend_to = 0.0, None, None

    last_sale_date = None
    for iv in intervals:
        if iv["sold"] > 0.001:
            last_sale_date = iv["to"]

    obs_count = (1 if init else 0) + len(counts)
    current = book
    first_date = ev[0]["date"] if ev else None
    last_date = ev[-1]["date"] if ev else None
    span = max(days_between(first_date, last_date), 0) if first_date else 0
    per_day = (sold / span) if span > 0 else 0.0
    cover = (current / per_day) if per_day > 0 else None
    if last_sale_date:
        days_since_last_sale = days_between(last_sale_date, today_str)
    else:
        days_since_last_sale = days_between(first_date, today_str) if first_date else 0

    return {
        "clientId": client_id, "productId": product_id,
        "init": _num(init.get("qty")) if init else 0.0,
        "sold": sold, "delivered": delivered, "current": current,
        "perDay": per_day, "monthly": per_day * 30, "cover": cover, "span": span,
        "obsCount": obs_count, "firstDate": first_date, "lastDate": last_date,
        "lastSaleDate": last_sale_date, "daysSinceLastSale": days_since_last_sale,
        "intervals": intervals,
    }


def status_of(a: dict) -> str:
    """Saytdagi statusOf() nusxasi."""
    if a["obsCount"] < 2:
        if a["current"] > 0 and a["daysSinceLastSale"] >= STUCK_DAYS:
            return "turgan"
        return "yangi"
    if a["current"] > 0 and a["daysSinceLastSale"] >= STUCK_DAYS:
        return "turgan"
    if a["cover"] is not None:
        if a["cover"] <= FAST_COVER:
            return "tez"
        if a["cover"] >= SLOW_COVER:
            return "sekin"
    return "normal"


def client_products(blob: dict, client_id) -> list:
    ids = []
    for key in ("initialStock", "sales", "counts"):
        for r in blob.get(key, []):
            if _same(r.get("clientId"), client_id) and r.get("productId") not in ids:
                ids.append(r.get("productId"))
    return ids


def analyze_client(blob: dict, client_id, today_str: str = None) -> dict:
    """Saytdagi analyzeClient() ning soddalashtirilgan nusxasi."""
    prods = [analyze_client_product(blob, client_id, pid, today_str=today_str)
             for pid in client_products(blob, client_id)]
    per_day = sum(p["perDay"] for p in prods)
    current = sum(p["current"] for p in prods)
    return {
        "prods": prods,
        "sold": sum(p["sold"] for p in prods),
        "delivered": sum(p["delivered"] for p in prods),
        "current": current,
        "perDay": per_day,
        "monthly": per_day * 30,
        "cover": (current / per_day) if per_day > 0 else None,
    }


# ---------------------------------------------------------------------------
# Lug'atlar
# ---------------------------------------------------------------------------
def maps(blob: dict):
    clients = {str(c.get("id")): c for c in blob.get("clients", []) if isinstance(c, dict)}
    products = {str(p.get("id")): p for p in blob.get("products", []) if isinstance(p, dict)}
    return clients, products


def month_totals(blob: dict, client_id, month_prefix: str):
    """Shu oy: klentga berilgan yuk va sanoqlar bo'yicha sotilgani."""
    delivered = sum(_num(s.get("qty")) for s in blob.get("sales", [])
                    if _same(s.get("clientId"), client_id)
                    and str(s.get("date") or "").startswith(month_prefix))
    sold = 0.0
    for pid in client_products(blob, client_id):
        a = analyze_client_product(blob, client_id, pid)
        sold += sum(iv["sold"] for iv in a["intervals"]
                    if str(iv["to"] or "").startswith(month_prefix))
    return delivered, sold

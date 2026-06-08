"""
Tahlil moduli.
Faqat qoldiqlar asosida sotilgan / yangi yuk / sotuv tezligi hisoblanadi.

Mantiq (ketma-ket ikki sanash orasida, har bir tovar uchun):
    delta = hozirgi_qoldiq - oldingi_qoldiq
    delta < 0  ->  sotilgan = -delta
    delta > 0  ->  yangi yuk olingan = delta
    delta = 0 va uzoq vaqt o'tgan -> qotib qolgan
"""
import datetime as dt
from collections import defaultdict

from config import FAST_COVER_DAYS, SLOW_COVER_DAYS, STUCK_MIN_DAYS


def _parse_date(s: str) -> dt.date:
    return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()


def analyze_period(rows: list) -> dict:
    """
    get_counts_in_period() qatorlarini olib, har bir klent bo'yicha tahlil qaytaradi.

    Qaytadi:
        {
          client_id: {
            "client_name": str,
            "sessions_count": int,
            "last_date": str,
            "last_value": float,        # oxirgi qoldiqning umumiy summasi
            "sold_units": float,        # davr ichida sotilgan (taxminiy)
            "delivered_units": float,   # davr ichida olingan yangi yuk (taxminiy)
            "sold_value": float,
            "span_days": int,
            "sold_per_day": float,
            "cover_days": float | None, # qoldiq necha kunga yetadi
            "status": str,              # tez | normal | sekin | qotgan | yangi
            "products": { product_id: {...} }
          }
        }
    """
    # Klent -> tovar -> ketma-ket (sana, miqdor) larni yig'amiz
    # rows allaqachon client_name, product, count_date bo'yicha tartiblangan
    by_client = defaultdict(lambda: {
        "client_name": "",
        "dates": set(),
        "sessions": defaultdict(dict),   # date -> {product_id: qty}
        "product_meta": {},              # product_id -> {name, unit, price}
        "last_date": None,
    })

    for r in rows:
        cid = r["client_id"]
        c = by_client[cid]
        c["client_name"] = r["client_name"]
        d = r["count_date"]
        c["dates"].add(d)
        c["sessions"][d][r["product_id"]] = r["quantity"]
        c["product_meta"][r["product_id"]] = {
            "name": r["product_name"],
            "unit": r["unit"],
            "price": r["price"],
        }

    result = {}
    for cid, c in by_client.items():
        dates_sorted = sorted(c["dates"])
        last_date = dates_sorted[-1]
        first_date = dates_sorted[0]
        span_days = max((_parse_date(last_date) - _parse_date(first_date)).days, 0)

        # Tovar bo'yicha sotilgan/yangi yuk yig'indisi (ketma-ket sessiyalar deltasi)
        prod_stats = {}
        for pid, meta in c["product_meta"].items():
            sold = 0.0
            delivered = 0.0
            prev_qty = None
            for d in dates_sorted:
                qty = c["sessions"][d].get(pid)
                if qty is None:
                    continue
                if prev_qty is not None:
                    delta = qty - prev_qty
                    if delta < 0:
                        sold += -delta
                    elif delta > 0:
                        delivered += delta
                prev_qty = qty
            last_qty = c["sessions"][last_date].get(pid, 0)
            prod_stats[pid] = {
                "name": meta["name"],
                "unit": meta["unit"],
                "price": meta["price"],
                "last_qty": last_qty,
                "sold": sold,
                "delivered": delivered,
                "value": last_qty * meta["price"],
            }

        sold_units = sum(p["sold"] for p in prod_stats.values())
        delivered_units = sum(p["delivered"] for p in prod_stats.values())
        sold_value = sum(p["sold"] * p["price"] for p in prod_stats.values())
        last_value = sum(p["value"] for p in prod_stats.values())
        last_qty_total = sum(p["last_qty"] for p in prod_stats.values())

        # kunlik sotuv tezligi
        sold_per_day = (sold_units / span_days) if span_days > 0 else 0.0
        cover_days = (last_qty_total / sold_per_day) if sold_per_day > 0 else None

        # holatni aniqlash
        days_since_last_change = span_days  # soddalashtirilgan
        status = _classify(
            sold_units, delivered_units, last_qty_total,
            cover_days, span_days, len(dates_sorted),
        )

        result[cid] = {
            "client_name": c["client_name"],
            "sessions_count": len(dates_sorted),
            "first_date": first_date,
            "last_date": last_date,
            "last_value": last_value,
            "sold_units": sold_units,
            "delivered_units": delivered_units,
            "sold_value": sold_value,
            "span_days": span_days,
            "sold_per_day": sold_per_day,
            "cover_days": cover_days,
            "status": status,
            "products": prod_stats,
        }
    return result


def _classify(sold, delivered, stock, cover_days, span_days, sessions_count):
    """Klent holatini matn kodi sifatida qaytaradi."""
    # Faqat 1 marta sanalgan bo'lsa, hali tahlil qilib bo'lmaydi
    if sessions_count < 2:
        return "yangi_klent"
    # Sotuv yo'q va zaxira bor, ancha vaqt o'tgan -> qotgan
    if sold == 0 and stock > 0 and span_days >= STUCK_MIN_DAYS:
        return "qotgan"
    if cover_days is not None:
        if cover_days <= FAST_COVER_DAYS:
            return "tez"
        if cover_days >= SLOW_COVER_DAYS:
            return "sekin"
    return "normal"


# Holat kodlari uchun matn va rang (Excel hex)
STATUS_LABELS = {
    "tez":         ("🟢 Tez sotyapti",     "C6EFCE"),
    "normal":      ("⚪ Normal",            "FFFFFF"),
    "sekin":       ("🟠 Sekin sotyapti",   "FFD699"),
    "qotgan":      ("🔴 Qotib qolgan",     "FFC7CE"),
    "yangi_klent": ("🔵 Yangi (1 marta)",  "DDEBF7"),
}


def status_text(code: str) -> str:
    return STATUS_LABELS.get(code, ("—", "FFFFFF"))[0]


def status_color(code: str) -> str:
    return STATUS_LABELS.get(code, ("—", "FFFFFF"))[1]

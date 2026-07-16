# -*- coding: utf-8 -*-
"""
sklad_read.py — CP Sklad (sayt)'dan SANOQ TARIXINI O'QISH  [YO'L B]
====================================================================
Maqsad: bot hisobotlari (kunlik/oylik Excel + tezkor tahlil) tarixni
endi SQLite'dan emas, TO'G'RIDAN-TO'G'RI SAYTDAN oladi.
Sabab: Railway deploy'da SQLite tozalanadi; sayt esa to'liq va butun
(1488+ counts). Endi manba bitta — sayt.

Bu modul sklad_sync.py ning HTTP o'qish funksiyasini QAYTA ishlatadi
(_http_get_blob) — ya'ni ulanish mantiqi bir joyda turadi.

Sayt blok tuzilishi:
  counts   : {id, qty, date, time, clientId, productId}   (1 yozuv = 1 tovar)
  clients  : {id, name, region}
  products : {id, name, unit, price}

Chiqadigan format — database.py ning ESKI funksiyalari qaytargan format
BILAN AYNAN BIR XIL (shuning uchun hisobot/analitika kodi o'zgarmaydi):
  count_id, client_id, count_date, created_at, client_name,
  agent_name, product_id, product_name, unit, price, quantity
"""
import time
import asyncio
import logging

from sklad_sync import _http_get_blob   # sayt blokini o'qish (urllib)

log = logging.getLogger("sklad_read")

# Sanoq botida yagona agent — sayt counts'da agent saqlanmaydi.
# Kerak bo'lsa shu yerdan o'zgartir.
AGENT_NAME = "Qodirxon"

# Kichik kesh: kunlik+oylik+tahlil ketma-ket chaqirilganda saytni
# qayta-qayta tortmaslik uchun. TTL soniya ichida bitta nusxa ishlaydi.
_CACHE_TTL = 45  # soniya
_cache = {"t": 0.0, "clients": {}, "products": {}, "counts": []}


def _to_float(x, default=0.0):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _build_created_at(date_str, time_str):
    """'YYYY-MM-DD HH:MM' qaytaradi — Excel row['created_at'][11:16] shuni kutadi."""
    d = (str(date_str) if date_str else "").strip()
    t = (str(time_str) if time_str else "").strip()
    if ":" in t:
        hh, _, rest = t.partition(":")
        mm = (rest[:2] or "00")
        try:
            t = f"{int(hh):02d}:{mm}"
        except ValueError:
            t = "00:00"
    else:
        t = "00:00"
    return f"{d} {t}"


def _load_blocking():
    """Saytdan blokni o'qib, ID->nom xaritalari va counts ni tayyorlaydi.
    Keshdan foydalanadi (TTL). Bloklovchi — asyncio.to_thread orqali chaqiriladi."""
    now = time.time()
    if now - _cache["t"] < _CACHE_TTL and _cache["counts"]:
        return _cache["clients"], _cache["products"], _cache["counts"]

    _row, blob, _col = _http_get_blob()

    clients = {}
    for c in blob.get("clients", []):
        if isinstance(c, dict):
            clients[c.get("id")] = c.get("name")

    products = {}
    for p in blob.get("products", []):
        if isinstance(p, dict):
            products[p.get("id")] = {
                "name": p.get("name"),
                "unit": p.get("unit", ""),
                "price": _to_float(p.get("price"), 0.0),
            }

    counts = [c for c in blob.get("counts", []) if isinstance(c, dict)]

    _cache.update({"t": now, "clients": clients,
                   "products": products, "counts": counts})
    return clients, products, counts


def _map_row(c, clients, products):
    """Bitta sayt count yozuvini -> eski hisobot formatiga."""
    cid = c.get("clientId")
    pid = c.get("productId")
    pmeta = products.get(pid) or {}
    return {
        "count_id":     c.get("id"),
        "client_id":    cid,
        "count_date":   c.get("date"),
        "created_at":   _build_created_at(c.get("date"), c.get("time")),
        "client_name":  clients.get(cid) or f"(mijoz {cid})",
        "agent_name":   AGENT_NAME,
        "product_id":   pid,
        "product_name": pmeta.get("name") or f"(tovar {pid})",
        "unit":         pmeta.get("unit", ""),
        "price":        _to_float(pmeta.get("price"), 0.0),
        "quantity":     _to_float(c.get("qty"), 0.0),
    }


def _by_date_blocking(date_str):
    clients, products, counts = _load_blocking()
    rows = [_map_row(c, clients, products)
            for c in counts if c.get("date") == date_str]
    rows.sort(key=lambda r: (r["client_name"], r["product_name"]))
    return rows


def _in_period_blocking(start_date, end_date):
    clients, products, counts = _load_blocking()
    rows = [_map_row(c, clients, products)
            for c in counts
            if start_date <= (c.get("date") or "") <= end_date]
    rows.sort(key=lambda r: (r["client_name"], r["product_name"],
                             r["count_date"] or "", r["created_at"]))
    return rows


# --- Public async API (database.py shularni chaqiradi) --------------------
async def counts_by_date_from_site(date_str: str):
    return await asyncio.to_thread(_by_date_blocking, date_str)


async def counts_in_period_from_site(start_date: str, end_date: str):
    return await asyncio.to_thread(_in_period_blocking, start_date, end_date)


# --- Mustaqil test: python sklad_read.py  (faqat o'qiydi) -----------------
if __name__ == "__main__":
    import datetime as dt
    logging.basicConfig(level=logging.INFO)
    today = dt.date.today().strftime("%Y-%m-%d")
    print("sklad_read — TEST (faqat o'qish)")
    cl, pr, cn = _load_blocking()
    print(f"clients={len(cl)}  products={len(pr)}  counts={len(cn)}")
    start = (dt.date.today() - dt.timedelta(days=60)).strftime("%Y-%m-%d")
    per = _in_period_blocking(start, today)
    print(f"so'nggi 60 kun: {len(per)} qator")
    if per:
        r = per[0]
        print("namuna:", r["count_date"], "|", r["created_at"], "|",
              r["client_name"], "|", r["product_name"],
              r["quantity"], r["unit"], r["price"])

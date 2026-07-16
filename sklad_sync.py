# -*- coding: utf-8 -*-
"""
sklad_sync.py  —  Sanoq bot -> CP Sklad (sayt) SINXRONIZATSIYASI
=================================================================
Vazifa: bot bitta sanashni tugatganda, o'sha natijani
sayt (cp_sklad JSON blok) ichidagi `counts` massiviga qo'shadi.

MUHIM TAMOYILLAR:
- Bot ID != Sayt ID. Shuning uchun NOM bo'yicha bog'lanadi
  (biz 139/139 va 17/17 mos kelishini tekshirdik).
- last-write-wins RISKINI kamaytirish: yozishdan AYNAN oldin
  blokni QAYTA o'qiydi, keyin qo'shadi, darhol qaytaradi.
- Sync XATO bo'lsa ham — bot ISHDAN TO'XTAMAYDI. Xato faqat
  log qilinadi. Sanash SQLite'da baribir saqlanadi.
- Faqat QO'SHADI (append). Hech narsani o'chirmaydi.

ENV KERAK (config.py yoki .env):
  SKLAD_SUPABASE_URL   (default pastda)
  SKLAD_ANON_KEY       (default pastda)
Agar .env'ga qo'ymasang, pastdagi default ishlatiladi.
"""

import os
import json
import asyncio
import logging
import datetime as dt
import urllib.request
import urllib.error

log = logging.getLogger("sklad_sync")

# ---------------------------------------------------------------------------
# Sozlamalar (ESKI sklad bazasi — sayt shu yerda)
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SKLAD_SUPABASE_URL", "https://qzemxaplmsrraojkzidz.supabase.co")
ANON_KEY     = os.getenv("SKLAD_ANON_KEY", "sb_publishable_gI375UfsdjUXFc1eAE0Qcw_etU_guDy")
TABLE        = "cp_sklad"
_TIMEOUT     = 20  # soniya


def _norm(s: str) -> str:
    """Nom solishtirish uchun normallashtirish (apostrof + bo'shliq)."""
    if not s:
        return ""
    s = str(s).strip().lower()
    for ch in ("\u02bb", "`", "\u2018", "\u2019", "\u00b4"):
        s = s.replace(ch, "'")
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# HTTP (past daraja) — bloklovchi urllib, alohida threadda ishlatiladi
# ---------------------------------------------------------------------------
def _http_get_blob():
    """cp_sklad qatorini o'qib, (row_dict, blob_dict) qaytaradi."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        rows = json.loads(r.read().decode())
    if not rows:
        raise RuntimeError("cp_sklad jadvali bo'sh")
    row = rows[0]

    # blok qayerda? — qatorning o'zi yoki biror ustun ichida
    if "clients" in row and "counts" in row:
        return row, row, None  # blok = qatorning o'zi
    for k, v in row.items():
        if isinstance(v, dict) and "clients" in v:
            return row, v, k
        if isinstance(v, str):
            try:
                p = json.loads(v)
                if isinstance(p, dict) and "clients" in p:
                    return row, p, k
            except Exception:
                pass
    raise RuntimeError(f"JSON blokni topa olmadim. Kalitlar: {list(row.keys())}")


def _http_patch_blob(row, blob, blob_col, pk_col, pk_val):
    """Yangilangan blokni qaytarib yozadi (PATCH)."""
    if blob_col is None:
        # blok = qatorning o'zi: butun qatorni yangilaymiz (pk dan tashqari)
        payload = {k: v for k, v in blob.items() if k != pk_col}
    else:
        # blok ustun ichida: faqat o'sha ustunni yangilaymiz
        col_val = row[blob_col]
        payload = {blob_col: blob if isinstance(col_val, dict) else json.dumps(blob, ensure_ascii=False)}

    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?{pk_col}=eq.{pk_val}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH", headers={
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.status


def _detect_pk(row):
    """Qatorning birlamchi kalitini (id) topadi."""
    for cand in ("id", "uuid", "pk"):
        if cand in row:
            return cand, row[cand]
    # topilmasa — birinchi kalit
    first = next(iter(row.keys()))
    return first, row[first]


# ---------------------------------------------------------------------------
# Asosiy ish (bloklovchi) — push_count_blocking
# ---------------------------------------------------------------------------
def push_count_blocking(client_name: str, items_by_name: dict):
    """
    client_name      : bot'dagi mijoz nomi (masalan "Axadjon aka Bo'z")
    items_by_name    : { tovar_nomi(bot) : qty }  masalan {"Biora 01 Shpaklovka": 34}

    Sayt blokidan mijoz/tovar ID sini NOM bo'yicha topadi,
    counts ga yangi yozuvlar qo'shadi, blokni qaytaradi.

    Qaytaradi: (qo'shilgan_soni:int, xato_ro'yxati:list[str])
    """
    # 1) Blokni O'QISH (yozishdan aynan oldin — eng yangi nusxa)
    row, blob, blob_col = _http_get_blob()
    pk_col, pk_val = _detect_pk(row)

    clients  = blob.get("clients", [])
    products = blob.get("products", [])
    counts   = blob.get("counts", [])
    seq      = int(blob.get("seq", 0))

    # 2) NOM -> ID xaritalari
    client_map  = {_norm(c.get("name")): c.get("id") for c in clients if isinstance(c, dict)}
    product_map = {_norm(p.get("name")): p.get("id") for p in products if isinstance(p, dict)}

    errors = []

    site_client_id = client_map.get(_norm(client_name))
    if site_client_id is None:
        errors.append(f"MIJOZ topilmadi (sayt): '{client_name}'")
        # mijoz topilmasa — umuman yozmaymiz
        return 0, errors

    now = dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    new_rows = []
    for pname, qty in items_by_name.items():
        pid = product_map.get(_norm(pname))
        if pid is None:
            errors.append(f"TOVAR topilmadi (sayt): '{pname}' — o'tkazib yuborildi")
            continue
        seq += 1
        new_rows.append({
            "id": seq,
            "qty": qty,
            "date": date_str,
            "time": time_str,
            "clientId": site_client_id,
            "productId": pid,
        })

    if not new_rows:
        return 0, errors

    # 3) Blokga qo'shish
    counts.extend(new_rows)
    blob["counts"] = counts
    blob["seq"] = seq

    # 4) QAYTARIB YOZISH (PATCH)
    _http_patch_blob(row, blob, blob_col, pk_col, pk_val)

    return len(new_rows), errors


# ---------------------------------------------------------------------------
# Async o'ram — botdan (aiogram) shu chaqiriladi
# ---------------------------------------------------------------------------
async def push_count(client_name: str, items_by_name: dict):
    """
    Async o'ram. Bloklovchi HTTP ni alohida threadda ishlatadi —
    bot event-loop'ini bloklamaydi.

    HECH QACHON exception ko'tarmaydi — xatoni log qiladi va
    (0, [xato]) qaytaradi. Bot to'xtamasligi kerak.
    """
    try:
        added, errors = await asyncio.to_thread(
            push_count_blocking, client_name, items_by_name
        )
        if errors:
            for e in errors:
                log.warning("sklad_sync: %s", e)
        if added:
            log.info("sklad_sync: %s ta yozuv saytga qo'shildi (%s)", added, client_name)
        return added, errors
    except urllib.error.URLError as e:
        log.error("sklad_sync: tarmoq xatosi — %s", e)
        return 0, [f"Tarmoq xatosi: {e}"]
    except Exception as e:
        log.exception("sklad_sync: kutilmagan xato")
        return 0, [f"Xato: {e}"]


# ---------------------------------------------------------------------------
# Mustaqil test (python sklad_sync.py) — HECH NARSA YOZMAYDI, faqat o'qiydi
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("sklad_sync — TEST (faqat o'qish, yozmaydi)")
    try:
        row, blob, col = _http_get_blob()
        pk_col, pk_val = _detect_pk(row)
        print("Blok topildi. Ustun:", col if col else "(qatorning o'zi)")
        print("PK:", pk_col, "=", pk_val)
        print("clients:", len(blob.get("clients", [])),
              "| products:", len(blob.get("products", [])),
              "| counts:", len(blob.get("counts", [])),
              "| seq:", blob.get("seq"))
        # Namuna: birinchi mijoz nomi bilan xaritani sinash
        if blob.get("clients"):
            c0 = blob["clients"][0]
            print("Namuna mijoz:", c0.get("name"), "-> id", c0.get("id"))
        print("\nO'qish OK. Yozish sinovini bot orqali qilamiz.")
    except Exception as e:
        print("XATO:", e)

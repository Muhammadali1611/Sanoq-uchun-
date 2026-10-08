# -*- coding: utf-8 -*-
"""
catalog_sync.py — TOVAR VA KLENTLAR RO'YXATI SAYTDAN (yagona manba)
==================================================================
Muammo: bot o'zining eski tovar ro'yxati bilan sanardi ("Concrete 75"),
1C'dan sotuv esa yangi nom bilan kelardi ("Kreta 75 Uselinniy...") ->
hisob bog'lanmay qolardi. Saytdagi yangi klentlar esa botda yo'q edi.

Endi:
  sync_from_site()  — saytdagi tovar/klentlarni botga ko'chiradi (nom bo'yicha),
                      saytda yo'qlarini botda yashiradi (tarix o'chmaydi).
                      Bot ishga tushganda va har 15 daqiqada ishlaydi.
  push_client() / push_product() — botda qo'shilgan klent/tovar saytga ham
                      qo'shiladi (sayt nextClientId kabi: max id + 1).
"""
import asyncio
import logging
import datetime as dt

import aiosqlite

from config import DB_PATH
import sklad_sync
from sklad_sync import _norm

log = logging.getLogger("catalog_sync")
UNIT = "qop"
_lock = asyncio.Lock()


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _region(r):
    r = (r or "").strip()
    return None if r in ("", "—", "-") else r


async def _hidden(kind):
    """Botda o'chirilgan (yashirilgan) nomlar — sync ularni qayta yoqmaydi."""
    import json
    import group_notify as gn
    try:
        return set(json.loads(await gn.get_setting(f"hidden_{kind}") or "[]"))
    except Exception:
        return set()


async def hide(kind, name, hidden=True):
    """kind: 'products' | 'clients'. Botdagi o'chirish saytga tegmaydi, faqat botda yashiradi."""
    import json
    import group_notify as gn
    h = await _hidden(kind)
    (h.add if hidden else h.discard)(_norm(name))
    await gn.set_setting(f"hidden_{kind}", json.dumps(sorted(h), ensure_ascii=False))


async def sync_from_site(blob=None) -> dict:
    """Saytdagi ro'yxatni botga moslaydi. Qaytaradi: o'zgarishlar soni."""
    async with _lock:
        if blob is None:
            blob = (await asyncio.to_thread(sklad_sync._http_get_blob))[1]
        site_p = {_norm(p.get("name")): p for p in blob.get("products", [])
                  if isinstance(p, dict) and p.get("name")}
        site_c = {_norm(c.get("name")): c for c in blob.get("clients", [])
                  if isinstance(c, dict) and c.get("name")}
        hid_p, hid_c = await _hidden("products"), await _hidden("clients")
        site_p = {k: v for k, v in site_p.items() if k not in hid_p}
        site_c = {k: v for k, v in site_c.items() if k not in hid_c}
        st = {"tovar_yangi": 0, "tovar_yashirildi": 0, "klent_yangi": 0, "klent_yashirildi": 0}

        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            # --- tovarlar ---
            cur = await conn.execute("SELECT * FROM products")
            seen = set()
            for r in await cur.fetchall():
                key = _norm(r["name"])
                sp = site_p.get(key)
                if sp and key not in seen:
                    seen.add(key)
                    await conn.execute(
                        "UPDATE products SET name = ?, price = ?, active = 1 WHERE id = ?",
                        (sp["name"], float(sp.get("price") or 0), r["id"]))
                elif r["active"]:
                    await conn.execute("UPDATE products SET active = 0 WHERE id = ?", (r["id"],))
                    st["tovar_yashirildi"] += 1
            for key, sp in site_p.items():
                if key not in seen:
                    await conn.execute(
                        "INSERT INTO products (name, unit, price, active, created_at) VALUES (?, ?, ?, 1, ?)",
                        (sp["name"], UNIT, float(sp.get("price") or 0), _now()))
                    st["tovar_yangi"] += 1

            # --- klentlar ---
            cur = await conn.execute("SELECT * FROM clients")
            seen = set()
            for r in await cur.fetchall():
                key = _norm(r["name"])
                sc = site_c.get(key)
                if sc and key not in seen:
                    seen.add(key)
                    await conn.execute(
                        "UPDATE clients SET name = ?, region = ?, active = 1 WHERE id = ?",
                        (sc["name"], _region(sc.get("region")) or r["region"], r["id"]))
                elif r["active"]:
                    await conn.execute("UPDATE clients SET active = 0 WHERE id = ?", (r["id"],))
                    st["klent_yashirildi"] += 1
            for key, sc in site_c.items():
                if key not in seen:
                    await conn.execute(
                        "INSERT INTO clients (name, region, active, created_at) VALUES (?, ?, 1, ?)",
                        (sc["name"], _region(sc.get("region")), _now()))
                    st["klent_yangi"] += 1
            await conn.commit()

        if any(st.values()):
            log.info("Katalog saytdan yangilandi: %s", st)
        return st


# ---------------------------------------------------------------------------
# Botda qo'shilgan klent/tovar -> saytga ham
# ---------------------------------------------------------------------------
def _push_blocking(kind, item):
    def mut(blob):
        arr = blob.setdefault(kind, [])
        if any(_norm(x.get("name")) == _norm(item["name"]) for x in arr if isinstance(x, dict)):
            return None  # allaqachon bor
        new_id = max([int(x.get("id") or 0) for x in arr if isinstance(x, dict)] + [0]) + 1
        arr.append({"id": new_id, **item})
        return new_id
    return sklad_sync.update_blob_blocking(mut)


async def push_client(name, region=None):
    try:
        return await asyncio.to_thread(_push_blocking, "clients",
                                       {"name": name, "region": region or "—"})
    except Exception:
        log.exception("klent saytga qo'shilmadi: %s", name)


async def push_product(name, price=0):
    try:
        return await asyncio.to_thread(_push_blocking, "products",
                                       {"name": name, "price": float(price or 0), "unit": "dona"})
    except Exception:
        log.exception("tovar saytga qo'shilmadi: %s", name)

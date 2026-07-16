# -*- coding: utf-8 -*-
"""
import_from_site.py  —  SAYT (CP Sklad) -> BOT (SQLite) TIKLASH
================================================================
Admin buyrug'i: /import_sayt
Saytdagi barcha `counts` yozuvlarini botning SQLite bazasiga
tiklaydi (nom bo'yicha bog'lab).

XAVFSIZLIK:
- Faqat admin ishlata oladi.
- Sayt ID -> nom -> bot ID (nom bo'yicha; biz 139/139, 17/17 mos
  kelishini tekshirдик).
- "Tizim (import)" nomli agentga bog'lanadi.
- QAYTA ishlatilsa: mavjud import qilingan sanoqlarni takroran
  qo'shmaydi (client_id + product_id + date + qty + time bo'yicha).
- Botning saytga yozishiga TEGMAYDI (bir tomonlama: sayt -> bot).

Ulash: bot.py da dp.include_router(import_from_site.router)
"""

import json
import logging
import datetime as dt
import urllib.request

import aiosqlite
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

import database as db
from config import DB_PATH, ADMIN_IDS

router = Router()
log = logging.getLogger("import_sayt")

SUPABASE_URL = "https://qzemxaplmsrraojkzidz.supabase.co"
ANON_KEY     = "sb_publishable_gI375UfsdjUXFc1eAE0Qcw_etU_guDy"
TABLE        = "cp_sklad"

SYSTEM_AGENT_ID   = 8317612695  # Qodirxon (agent) — eski sanoqlar shunga bog'lanadi
SYSTEM_AGENT_NAME = "Qodirxon"


def _norm(s):
    if not s:
        return ""
    s = str(s).strip().lower()
    for ch in ("\u02bb", "`", "\u2018", "\u2019", "\u00b4"):
        s = s.replace(ch, "'")
    return " ".join(s.split())


def _fetch_site_blob():
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}?select=*"
    req = urllib.request.Request(url, headers={
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode())
    row = rows[0]
    if "clients" in row and "counts" in row:
        return row
    for v in row.values():
        if isinstance(v, dict) and "counts" in v:
            return v
        if isinstance(v, str):
            try:
                p = json.loads(v)
                if isinstance(p, dict) and "counts" in p:
                    return p
            except Exception:
                pass
    raise RuntimeError("Sayt blokini topa olmadim")


async def _ensure_system_agent():
    """Tizim agentini yaratadi (bo'lmasa)."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT id FROM users WHERE id = ?", (SYSTEM_AGENT_ID,))
        if not await cur.fetchone():
            await conn.execute(
                "INSERT INTO users (id, full_name, role, added_by, created_at) "
                "VALUES (?, ?, 'admin', NULL, ?)",
                (SYSTEM_AGENT_ID, SYSTEM_AGENT_NAME,
                 dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            await conn.commit()


@router.message(Command("mening_id"))
async def mening_id(message: Message):
    """Istalgan foydalanuvchi o'z Telegram id'sini bilib oladi."""
    u = message.from_user
    uname = ("@" + u.username) if u.username else "(yo'q)"
    await message.answer(
        f"Sizning Telegram ma'lumotingiz:\n"
        f"ID: <code>{u.id}</code>\n"
        f"Ism: {u.full_name}\n"
        f"Username: {uname}"
    )


@router.message(Command("import_sayt"))
async def import_sayt(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Bu buyruq faqat admin uchun.")
        return

    await message.answer("Saytdan ma'lumot yuklanyapti... (biroz kuting)")

    try:
        blob = await _run_blocking(_fetch_site_blob)
    except Exception as e:
        log.exception("sayt o'qishda xato")
        await message.answer(f"Xato: saytga ulanib bo'lmadi.\n{e}")
        return

    site_clients  = blob.get("clients", [])
    site_products = blob.get("products", [])
    site_counts   = blob.get("counts", [])

    # sayt ID -> nom
    scid_to_name = {c.get("id"): c.get("name") for c in site_clients if isinstance(c, dict)}
    spid_to_name = {p.get("id"): p.get("name") for p in site_products if isinstance(p, dict)}

    await _ensure_system_agent()

    # bot: nom -> id
    bot_clients  = await db.get_clients(active_only=False)
    bot_products = await db.get_products(active_only=False)
    bot_cname_to_id = {_norm(c["name"]): c["id"] for c in bot_clients}
    bot_pname_to_id = {_norm(p["name"]): p["id"] for p in bot_products}

    added_sessions = 0
    added_items    = 0
    skipped        = 0
    errors         = 0

    async with aiosqlite.connect(DB_PATH) as conn:
        # Takrorlanishni oldini olish uchun mavjud kalitlar to'plami
        cur = await conn.execute(
            "SELECT c.client_id, ci.product_id, c.count_date, ci.quantity "
            "FROM counts c JOIN count_items ci ON ci.count_id = c.id"
        )
        existing = set()
        for r in await cur.fetchall():
            existing.add((r[0], r[1], r[2], float(r[3])))

        # Saytdagi har bir count (bu blokda 1 count = 1 tovar yozuvi)
        # Botда: 1 count sessiyа + 1 count_item. Sodda: har sayt yozuvı
        # uchun 1 sessiya (bir tovar) — struktura mos, ko'rish ishlaydi.
        for sc in site_counts:
            try:
                scid = sc.get("clientId")
                spid = sc.get("productId")
                qty  = float(sc.get("qty", 0))
                date = sc.get("date")
                time = sc.get("time", "00:00")

                cname = scid_to_name.get(scid)
                pname = spid_to_name.get(spid)
                if cname is None or pname is None:
                    errors += 1
                    continue

                bot_cid = bot_cname_to_id.get(_norm(cname))
                bot_pid = bot_pname_to_id.get(_norm(pname))
                if bot_cid is None or bot_pid is None:
                    errors += 1
                    continue

                key = (bot_cid, bot_pid, date, qty)
                if key in existing:
                    skipped += 1
                    continue

                created = f"{date} {time}:00" if len(time) == 5 else f"{date} 00:00:00"
                cur2 = await conn.execute(
                    "INSERT INTO counts (client_id, agent_id, count_date, created_at, note) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (bot_cid, SYSTEM_AGENT_ID, date, created, "saytdan import"),
                )
                count_id = cur2.lastrowid
                await conn.execute(
                    "INSERT INTO count_items (count_id, product_id, quantity) VALUES (?, ?, ?)",
                    (count_id, bot_pid, qty),
                )
                existing.add(key)
                added_sessions += 1
                added_items += 1
            except Exception:
                errors += 1
                continue

        await conn.commit()

    await message.answer(
        "✅ Import tugadi.\n\n"
        f"Sayt yozuvlari: {len(site_counts)}\n"
        f"Qo'shildi: {added_sessions} ta sanoq\n"
        f"O'tkazib yuborildi (mavjud edi): {skipped}\n"
        f"Xato/mos kelmadi: {errors}\n\n"
        "Endi botdan istalgan sanadagi sanoqni topsa bo'ladi."
    )


# aiogram loop'ini bloklamaslik uchun
async def _run_blocking(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)

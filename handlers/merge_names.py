# -*- coding: utf-8 -*-
"""
/nomlarni_birlashtir — ESKI TOVAR NOMLARINI 1C'DAGI YANGI NOMGA O'TKAZISH (faqat admin)
=====================================================================================
Bir mahsulot ikki nom bilan yashayotgan edi (masalan "Concrete 75" — sanoqlar,
"Kreta 75 Uselinniy 25kg (Suxoy)" — 1C sotuvlari) -> hisob bog'lanmasdi.

Buyruq:
  1) har bir juftlik bo'yicha qancha yozuv ko'chishini ko'rsatadi,
  2) admin "✅ Birlashtir" bosgandan keyin saytda eski tovarning BARCHA
     yozuvlari (boshlang'ich qoldiq, sotuv, sanoq) yangi tovarga o'tadi va
     eski tovar ro'yxatdan o'chadi,
  3) botning tovar ro'yxati saytdan qayta olinadi.
Qayta ishlatilsa — allaqachon birlashganlarini o'tkazib yuboradi.
Yangi juftlik kerak bo'lsa — MERGE_MAP ga qo'shing.
"""
import asyncio
import copy
import html
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
import catalog_sync
import sklad_sync
from sklad_sync import _http_get_blob, _norm
from config import ADMIN_IDS

router = Router()
log = logging.getLogger("merge_names")

# ESKI nom (bot/sayt)  ->  YANGI nom (1C'dan keladigan)
MERGE_MAP = [
    ("Concrete 75",      "Kreta 75 Uselinniy 25kg (Suxoy)"),
    ("Concrete Rodband", "Kreta Rodband 25 kg"),
    # 1C nomga "(Suxoy)" qo'shildi — avval mavjud tovar nomi yangilanadi,
    # keyin eski Dom Oq fasad unga birlashadi (tartib muhim!)
    ("ForGips Oq fasad 20kg", "ForGips Oq fasad 20kg (Suxoy)"),
    ("Dom Oq fasad",     "ForGips Oq fasad 20kg (Suxoy)"),
    ("Dom Nalivnoy",     "Remost Nalivnoy pol 25kg (Suxoy)"),
    ("Dom 22",           "Remost 22 25kg (Suxoy)"),
    ("Dom 07 Rodband",   "Remost 07 rodband 25kg (Suxoy)"),
    ("Concrete 01 Shpaklovka", "Kreta 01 20kg (Suxoy)"),
]
ARRAYS = ("initialStock", "sales", "counts", "deliveries")


def e(s):
    return html.escape(str(s), quote=False)


async def _is_admin(uid):
    if uid in ADMIN_IDS:
        return True
    u = await db.get_user(uid)
    return bool(u and u["role"] == "admin")


def _step(blob, old, new):
    """Bitta juftlikni blokka qo'llaydi. Qaytaradi: (qator_tavsifi, ko'chgan_soni)."""
    by_name = {_norm(p.get("name")): p for p in blob.get("products", []) if isinstance(p, dict)}
    po, pn = by_name.get(_norm(old)), by_name.get(_norm(new))
    if po is None:
        return (old, new, None, None, "allaqachon bajarilgan"), 0
    if pn is None:
        # Yangi nom saytda hali yo'q -> eski tovarning NOMI o'zgartiriladi
        # (tarix joyida qoladi, 1C importi endi shu nom bilan mos tushadi)
        po["name"] = new
        return (old, new, po["id"], "rename", "nomi 1C'dagi nomga o'zgartiriladi"), 1
    cnt = {k: 0 for k in ARRAYS}
    for k in ARRAYS:
        for r in blob.get(k, []) or []:
            if isinstance(r, dict) and str(r.get("productId")) == str(po["id"]):
                r["productId"] = pn["id"]
                cnt[k] += 1
    blob["products"] = [p for p in blob.get("products", []) if p is not po]
    return (old, new, po["id"], pn["id"], cnt), sum(cnt.values())


def plan(blob):
    """Oldindan ko'rish: nusxada ketma-ket bajarib, nima bo'lishini qaytaradi."""
    work = copy.deepcopy(blob)
    return [_step(work, old, new)[0] for old, new in MERGE_MAP]


def apply_merge(blob):
    """Blokni joyida, juftliklarni TARTIB bilan o'zgartiradi.
    Qaytaradi: o'zgargan yozuvlar soni (hech narsa bo'lmasa None)."""
    total, changed = 0, False
    for old, new in MERGE_MAP:
        row, n = _step(blob, old, new)
        total += n
        changed = changed or row[2] is not None
    return total if changed else None


def _fmt_plan(rows):
    lines = []
    for old, new, oid, nid, info in rows:
        if isinstance(info, str):
            lines.append(f"• {e(old)} → {e(new)}\n   <i>{e(info)}</i>")
        else:
            lines.append(f"• <b>{e(old)}</b> → <b>{e(new)}</b>\n"
                         f"   sanoq: {info['counts']}, sotuv: {info['sales']}, "
                         f"boshl. qoldiq: {info['initialStock']}")
    return "\n".join(lines)


@router.message(Command("nomlarni_birlashtir"))
async def merge_cmd(message: Message):
    if not await _is_admin(message.from_user.id):
        return
    try:
        blob = (await asyncio.to_thread(_http_get_blob))[1]
    except Exception as ex:
        await message.answer(f"Saytga ulanib bo'lmadi: {e(ex)}")
        return
    rows = plan(blob)
    todo = [r for r in rows if not isinstance(r[4], str) or r[3] == "rename"]
    text = "🔁 <b>Tovar nomlarini birlashtirish</b>\n\n" + _fmt_plan(rows)
    if not todo:
        await message.answer(text + "\n\n✅ Birlashtiriladigan narsa qolmagan.")
        return
    text += ("\n\n⚠️ Eski nomning butun tarixi yangi nomga o'tadi, eski nom o'chadi.\n"
             "Boshlashdan oldin saytning <b>barcha ochiq oynalarini yoping</b> "
             "(eski nusxa bilan saqlab yubormasligi uchun).")
    kbd = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Birlashtir", callback_data="mrg:yes"),
        InlineKeyboardButton(text="❌ Bekor", callback_data="mrg:no")]])
    await message.answer(text, reply_markup=kbd)


@router.callback_query(F.data == "mrg:no")
async def merge_no(call: CallbackQuery):
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()


@router.callback_query(F.data == "mrg:yes")
async def merge_yes(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        await call.answer("Faqat admin", show_alert=True)
        return
    await call.answer("Birlashtirilyapti...")
    try:
        moved = await asyncio.to_thread(sklad_sync.update_blob_blocking, apply_merge) or 0
    except Exception as ex:
        log.exception("birlashtirishda xato")
        await call.message.edit_text(f"❌ Xato: {e(ex)}\nSaytda hech narsa o'zgarmadi.")
        return
    try:
        st = await catalog_sync.sync_from_site()
    except Exception:
        st = {}
    await call.message.edit_text(
        f"✅ Tayyor. {moved} ta yozuv yangi nomlarga o'tkazildi.\n"
        f"Botdagi tovarlar ro'yxati saytdan yangilandi "
        f"(+{st.get('tovar_yangi', 0)} yangi, {st.get('tovar_yashirildi', 0)} eski yashirildi).\n\n"
        "Saytni qayta oching (F5) — u yerda ham yangi nomlar bilan ko'rinadi.")

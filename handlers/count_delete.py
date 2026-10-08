# -*- coding: utf-8 -*-
"""
🗑 SANOQNI O'CHIRISH (faqat admin)
==================================
Klent -> oxirgi sanoqlar (SAYTDAN, sana+vaqt bo'yicha guruhlangan) -> tasdiq ->
  1) saytdan o'chadi (asosiy manba),
  2) botning o'z bazasidan o'chadi (mos kelsa),
  3) guruhdagi hisobot rasmi o'chiriladi (bo'lmasa "o'chirildi" deb belgilanadi).
Saytda qo'lda kiritilgan sanoqlarni ham ko'radi va o'chira oladi.
"""
import asyncio
import html
import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
import keyboards as kb
import group_notify as gn
import site_analysis as sa
import sklad_sync
from sklad_sync import _http_get_blob, _norm
from config import ADMIN_IDS

router = Router()
log = logging.getLogger("count_delete")
UNIT = "qop"


class DelCount(StatesGroup):
    searching = State()
    choosing = State()


def e(s):
    return html.escape(str(s if s is not None else ""), quote=False)


async def _is_admin(uid):
    if uid in ADMIN_IDS:
        return True
    u = await db.get_user(uid)
    return bool(u and u["role"] == "admin")


def _sessions(blob, site_cid, limit=8):
    """Klentning sanoqlari: (sana, vaqt) bo'yicha guruhlab, eng yangisi birinchi."""
    _, products = sa.maps(blob)
    groups = {}
    for c in blob.get("counts", []):
        if not isinstance(c, dict) or not sa._same(c.get("clientId"), site_cid):
            continue
        key = (str(c.get("date") or ""), str(c.get("time") or ""))
        g = groups.setdefault(key, {"date": key[0], "time": key[1], "agent": None, "items": []})
        if c.get("agent"):
            g["agent"] = c["agent"]
        g["items"].append((products.get(str(c.get("productId")), {}).get("name", "?"),
                           sa._num(c.get("qty"))))
    out = sorted(groups.values(), key=lambda g: (g["date"], g["time"]), reverse=True)
    return out[:limit]


@router.message(F.text == kb.BTN_DEL_COUNT)
async def dc_start(message: Message, state: FSMContext):
    if not await _is_admin(message.from_user.id):
        return
    await state.set_state(DelCount.searching)
    await message.answer("🗑 Qaysi klentning sanog'ini o'chiramiz? Ismini yozing "
                         "(qisman bo'lsa ham bo'ladi):", reply_markup=kb.cancel_menu())


@router.message(DelCount.searching, F.text != kb.BTN_CANCEL)
async def dc_search(message: Message, state: FSMContext):
    q = _norm(message.text or "")
    try:
        blob = (await asyncio.to_thread(_http_get_blob))[1]
    except Exception as ex:
        await message.answer(f"Saytga ulanib bo'lmadi: {e(ex)}")
        return
    found = [c for c in blob.get("clients", []) if q and q in _norm(c.get("name"))][:12]
    if not found:
        await message.answer("Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    rows = [[InlineKeyboardButton(text=f"🏬 {c['name']}" + (f" — {c['region']}" if c.get("region") else ""),
                                  callback_data=f"dc:c:{c['id']}")] for c in found]
    await message.answer("Klentni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("dc:c:"))
async def dc_client(call: CallbackQuery, state: FSMContext):
    if not await _is_admin(call.from_user.id):
        await call.answer("Faqat admin", show_alert=True)
        return
    cid = call.data.split(":", 2)[2]
    blob = (await asyncio.to_thread(_http_get_blob))[1]
    clients, _ = sa.maps(blob)
    sess = _sessions(blob, cid)
    if not sess:
        await call.message.edit_text("Bu klentda sanoq yo'q.")
        await call.answer()
        return
    await state.set_state(DelCount.choosing)
    await state.update_data(dc_cid=cid, dc_name=clients.get(str(cid), {}).get("name", cid),
                            dc_sess=[[s["date"], s["time"]] for s in sess])
    rows = []
    for i, s in enumerate(sess):
        who = f" · {s['agent']}" if s["agent"] else ""
        rows.append([InlineKeyboardButton(
            text=f"📅 {sa.ddmm(s['date'])} {s['time']} · {len(s['items'])} ta mahsulot{who}",
            callback_data=f"dc:s:{i}")])
    await call.message.edit_text(
        f"🏬 <b>{e(clients.get(str(cid), {}).get('name', cid))}</b>\nQaysi sanoqni o'chiramiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(DelCount.choosing, F.data.startswith("dc:s:"))
async def dc_pick(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    i = int(call.data.split(":")[2])
    d, t = data["dc_sess"][i]
    blob = (await asyncio.to_thread(_http_get_blob))[1]
    s = next((x for x in _sessions(blob, data["dc_cid"], limit=100)
              if x["date"] == d and x["time"] == t), None)
    if not s:
        await call.answer("Bu sanoq allaqachon o'chirilgan", show_alert=True)
        return
    items = "\n".join(f"  • {e(n)}: {sa.fmt1(q)} {UNIT}" for n, q in sorted(s["items"]))
    kbd = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, o'chir", callback_data=f"dc:y:{i}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data="dc:n"),
    ]])
    await call.message.edit_text(
        f"❗ <b>{e(data['dc_name'])}</b>\n📅 {sa.ddmm(d)} {e(t)}"
        + (f" · 👤 {e(s['agent'])}" if s["agent"] else "")
        + f"\n\n{items}\n\nShu sanoq <b>saytdan, botdan va guruhdan</b> o'chirilsinmi?",
        reply_markup=kbd)
    await call.answer()


@router.callback_query(DelCount.choosing, F.data == "dc:n")
async def dc_no(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()


@router.callback_query(DelCount.choosing, F.data.startswith("dc:y:"))
async def dc_yes(call: CallbackQuery, state: FSMContext):
    if not await _is_admin(call.from_user.id):
        await call.answer("Faqat admin", show_alert=True)
        return
    data = await state.get_data()
    i = int(call.data.split(":")[2])
    d, t = data["dc_sess"][i]
    cid, cname = data["dc_cid"], data["dc_name"]
    await call.answer("O'chirilyapti...")

    # 1) SAYT
    removed_rows = []

    def mutator(blob):
        _, products = sa.maps(blob)
        keep = []
        for c in blob.get("counts", []):
            if (isinstance(c, dict) and sa._same(c.get("clientId"), cid)
                    and str(c.get("date") or "") == d and str(c.get("time") or "") == t):
                removed_rows.append((products.get(str(c.get("productId")), {}).get("name", "?"),
                                     sa._num(c.get("qty"))))
            else:
                keep.append(c)
        if not removed_rows:
            return None
        blob["counts"] = keep
        return len(removed_rows)

    try:
        n_site = await sklad_sync.update_blob(mutator) or 0
    except Exception as ex:
        log.exception("saytdan o'chirishda xato")
        await call.message.edit_text(f"❌ Saytdan o'chirib bo'lmadi: {e(ex)}\nHech narsa o'zgarmadi.")
        await state.clear()
        return

    # 2) BOT BAZASI (mos sessiya bo'lsa)
    n_bot = 0
    try:
        want = {(_norm(n), round(q, 3)) for n, q in removed_rows}
        for bc in await db.search_clients(cname, limit=10):
            if _norm(bc["name"]) != _norm(cname):
                continue
            for sess in await db.get_client_recent_counts(bc["id"], limit=30):
                got = {(_norm(it["product_name"]), round(float(it["quantity"]), 3))
                       for it in sess["items"]}
                if sess["count_date"] == d and got and got == want:
                    await db.delete_count(sess["id"])
                    n_bot += 1
                    break
    except Exception:
        log.exception("bot bazasidan o'chirishda xato (sayt allaqachon tozalandi)")

    # 3) GURUHDAGI XABAR
    grp = "—"
    ref = await gn.recall_message(cid, d, t)
    if ref:
        chat_id, msg_id = ref
        try:
            await call.bot.delete_message(chat_id, msg_id)
            grp = "rasm o'chirildi"
        except Exception:
            try:
                await call.bot.send_message(
                    chat_id, f"❌ Bu sanoq ({sa.ddmm(d)} {t}) admin tomonidan o'chirildi.",
                    reply_to_message_id=msg_id)
                grp = "o'chirildi deb belgilandi (48 soatdan eski)"
            except Exception:
                grp = "topilmadi"
        await gn.set_setting(gn._msg_key(cid, d, t), "")

    await state.clear()
    await call.message.edit_text(
        f"🗑 <b>{e(cname)}</b> — {sa.ddmm(d)} {e(t)} sanog'i o'chirildi.\n\n"
        f"• Sayt: {n_site} ta yozuv\n• Bot: {'✅' if n_bot else '— (botda yo‘q edi)'}\n"
        f"• Guruh: {grp}")

# -*- coding: utf-8 -*-
"""
group_notify.py — GURUHGA AVTOMATIK XABARLAR (topiclar bo'yicha)
=================================================================
1) Sanoq tugashi bilan -> o'sha agentning topiciga natija:
   oldi / sotdi / qoldiq, oylik tezlik, 30 dan kam qolgan, turib qolgan,
   shubhali sanoq.
2) Saytga sotuv kiritilganda (har 15 daqiqada tekshiradi) -> klentni oxirgi
   sanagan agentning topiciga; kerak bo'lsa sanoq natijasini yangilab yozadi.
   Agent noma'lum bo'lsa -> General.

Sozlash (guruhda, admin):  har bir topicda  /topic  yozing -> agentni tanlang.
Hisob mantig'i: site_analysis.py (saytdagi bilan 1:1).

Railway Volume bo'lmasa ham ishlashi uchun zaxira ENV:
  GROUP_CHAT_ID=-100xxxxxxxxxx
  TOPIC_MAP=agentId:threadId,agentId:threadId     (0 = General)
  SALES_CHECK_MIN=15
"""
import os
import json
import html
import asyncio
import logging
import datetime as dt

import aiosqlite
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, BufferedInputFile)
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

import database as db
import site_analysis as sa
import report_image as ri
from config import DB_PATH, ADMIN_IDS
from sklad_sync import _http_get_blob, _norm

log = logging.getLogger("group_notify")
router = Router()

SALES_CHECK_MIN = int(os.getenv("SALES_CHECK_MIN", "15") or 15)
MONTHS_UZ = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
             "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]
UNIT = "qop"  # saytda tovar birligi "dona" turibdi — guruhda hammasi qop deb ko'rsatiladi
STATUS_EMOJI = {"tez": " 🟢", "sekin": " 🟠", "turgan": " 🔴"}

# Bir vaqtda faqat bitta sotuv tekshiruvi ishlasin
_watch_lock = asyncio.Lock()


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


# ===========================================================================
# 1. SOZLAMALAR (SQLite + ENV zaxira)
# ===========================================================================
async def init():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.commit()


async def get_setting(key, default=None):
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        await conn.commit()


async def get_group_chat():
    v = await get_setting("group_chat_id") or os.getenv("GROUP_CHAT_ID", "")
    try:
        return int(v) if v else None
    except ValueError:
        return None


def _env_topic_map() -> dict:
    out = {}
    for part in os.getenv("TOPIC_MAP", "").replace(";", ",").split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            try:
                out[int(a.strip())] = int(b.strip())
            except ValueError:
                pass
    return out


async def get_topic_map() -> dict:
    """{agent_id: thread_id}  (0 yoki None = General)."""
    m = _env_topic_map()
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT key, value FROM bot_settings WHERE key LIKE 'topic:%'")
        for k, v in await cur.fetchall():
            try:
                m[int(k.split(":", 1)[1])] = int(v)
            except ValueError:
                pass
    return m


async def thread_for_agent(agent_id):
    if agent_id is None:
        return None
    try:
        agent_id = int(agent_id)
    except (TypeError, ValueError):
        return None
    t = (await get_topic_map()).get(agent_id)
    return t or None  # 0 -> General


# ===========================================================================
# 2. TELEGRAMGA YUBORISH (bo'laklash + limit + topic xatosi)
# ===========================================================================
def _chunks(text: str, limit: int = 3900):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


async def send(bot: Bot, thread_id, text: str):
    chat_id = await get_group_chat()
    if not chat_id:
        log.info("Guruh sozlanmagan — xabar yuborilmadi")
        return False
    for part in _chunks(text):
        for attempt in range(3):
            try:
                await bot.send_message(chat_id, part, message_thread_id=thread_id or None)
                break
            except TelegramRetryAfter as ex:
                await asyncio.sleep(ex.retry_after + 1)
            except TelegramBadRequest as ex:
                # topic o'chirilgan bo'lsa -> General'ga
                if thread_id and "thread" in str(ex).lower():
                    log.warning("Topic %s topilmadi, General'ga yuboriladi", thread_id)
                    thread_id = None
                    continue
                log.error("Guruhga yuborib bo'lmadi: %s", ex)
                return False
        await asyncio.sleep(1.2)  # guruhga daqiqasiga ~20 xabar limiti
    return True


async def send_photo(bot: Bot, thread_id, png: bytes, caption: str, filename="sanoq.png"):
    """Rasm + izoh yuboradi. Qaytaradi: (chat_id, message_id) yoki None."""
    chat_id = await get_group_chat()
    if not chat_id:
        return None
    for attempt in range(3):
        try:
            m = await bot.send_photo(chat_id, BufferedInputFile(png, filename=filename),
                                     caption=caption, message_thread_id=thread_id or None)
            return chat_id, m.message_id
        except TelegramRetryAfter as ex:
            await asyncio.sleep(ex.retry_after + 1)
        except TelegramBadRequest as ex:
            if thread_id and "thread" in str(ex).lower():
                thread_id = None
                continue
            log.error("Guruhga rasm yuborib bo'lmadi: %s", ex)
            return None
    return None


def _msg_key(site_cid, date_str, time_str):
    return f"msg:{site_cid}|{date_str}|{time_str}"


async def remember_message(site_cid, date_str, time_str, chat_id, message_id):
    await set_setting(_msg_key(site_cid, date_str, time_str), json.dumps([chat_id, message_id]))


async def recall_message(site_cid, date_str, time_str):
    v = await get_setting(_msg_key(site_cid, date_str, time_str))
    try:
        return tuple(json.loads(v)) if v else None
    except Exception:
        return None


# ===========================================================================
# 3. /topic — topicni agentga bog'lash (guruhda, faqat admin)
# ===========================================================================
async def _is_admin(user_id) -> bool:
    if user_id in ADMIN_IDS:
        return True
    u = await db.get_user(user_id)
    return bool(u and u["role"] == "admin")


@router.message(Command("topic"), F.chat.type.in_({"group", "supergroup"}))
async def topic_cmd(message: Message):
    if not await _is_admin(message.from_user.id):
        await message.reply("Bu buyruq faqat admin uchun.")
        return
    users = []
    for role in ("agent", "manager", "admin"):
        users += await db.get_users_by_role(role)
    rows = [[InlineKeyboardButton(text=f"👤 {u['full_name']}", callback_data=f"tp:{u['id']}")]
            for u in users]
    rows.append([InlineKeyboardButton(text="🏠 Umumiy (agentsiz sotuvlar)", callback_data="tp:0")])
    await message.reply(
        "Bu topicga kimning sanoq va sotuvlari tushsin?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("tp:"))
async def topic_pick(call: CallbackQuery):
    if not await _is_admin(call.from_user.id):
        await call.answer("Faqat admin", show_alert=True)
        return
    uid = int(call.data.split(":")[1])
    chat_id = call.message.chat.id
    thread = call.message.message_thread_id if call.message.is_topic_message else None
    await set_setting("group_chat_id", chat_id)
    if uid == 0:
        label = "🏠 Umumiy — agenti noma'lum klentlarning sotuvlari"
    else:
        await set_setting(f"topic:{uid}", thread or 0)
        u = await db.get_user(uid)
        label = f"👤 {u['full_name'] if u else uid} — sanoq, sotuv va ogohlantirishlari"

    tm = await get_topic_map()
    env_line = ",".join(f"{k}:{v}" for k, v in tm.items())
    await call.message.edit_text(
        f"✅ Sozlandi. Bu topicga: <b>{e(label)}</b>\n\n"
        f"<i>Zaxira (Railway → Variables):</i>\n"
        f"<code>GROUP_CHAT_ID={chat_id}</code>\n<code>TOPIC_MAP={env_line}</code>")
    await call.answer("Saqlandi")


# ===========================================================================
# 4. SANOQ XABARI
# ===========================================================================
def _unit(p):
    return UNIT


def build_count_message(blob, site_client_id, product_ids, date_str, time_str,
                        agent_name=None, today_str=None):
    """Bitta sanoq bo'yicha guruh xabari (sof funksiya — test qilinadi)."""
    today_str = today_str or sa.today()
    clients, products = sa.maps(blob)
    client = clients.get(str(site_client_id), {})
    lines = [f"📋 <b>Sanoq: {e(client.get('name', site_client_id))}</b>"
             + (f" — {e(client['region'])}" if client.get("region") else "")]
    lines.append(f"👤 {e(agent_name or '—')} · 🗓 {sa.ddmm(date_str)} {e(time_str or '')}")
    lines.append("")

    low, stuck, suspicious = [], [], []
    total_value = 0.0
    for pid in product_ids:
        p = products.get(str(pid), {})
        name, unit = e(p.get("name", pid)), _unit(p)
        a = sa.analyze_client_product(blob, site_client_id, pid, today_str=today_str)
        st = sa.status_of(a)
        cur = a["current"]
        total_value += cur * sa._num(p.get("price"))

        iv = next((i for i in reversed(a["intervals"])
                   if i["to"] == date_str and (i["toT"] or "") == (time_str or "")), None)
        if iv is None and a["intervals"] and a["intervals"][-1]["to"] == date_str:
            iv = a["intervals"][-1]

        if iv is None:
            lines.append(f"• <b>{name}</b>: birinchi sanoq → {sa.fmt1(cur)} {unit}")
        else:
            start = (f"{sa.fmt1(iv['startQty'])} ({sa.ddmm(iv['from'])})"
                     if iv["hasPrev"] else "0")
            got = f" + {sa.fmt1(iv['delivered'])} oldi" if iv["delivered"] > 0.001 else ""
            raw = iv["rawSold"]
            if raw < -0.001:
                res = f"❗ hisobdan +{sa.fmt1(-raw)} ko'p"
                suspicious.append((name, -raw))
            elif raw > 0.001:
                res = f"<b>sotdi {sa.fmt1(raw)}</b>"
            else:
                res = "sotmadi"
            lines.append(f"• <b>{name}</b>: {start}{got} → {sa.fmt1(iv['endQty'])} ⇒ "
                         f"{res}{STATUS_EMOJI.get(st, '')}")

        if cur < sa.LOW_STOCK:
            low.append(f"{name} — {sa.fmt1(cur)}")
        if st == "turgan":
            stuck.append(f"{name} — {sa.fmt1(cur)} {unit} ({a['daysSinceLastSale']} kun)")

    # Klent bo'yicha umumiy (hamma mahsulotlar)
    ca = sa.analyze_client(blob, site_client_id, today_str=today_str)
    mprefix = date_str[:7]
    m_deliv, m_sold = sa.month_totals(blob, site_client_id, mprefix)
    try:
        mname = MONTHS_UZ[int(mprefix[5:7])]
    except Exception:
        mname = mprefix
    lines.append("")
    lines.append(f"📊 {mname}: {sa.fmt(m_deliv)} qop oldi · {sa.fmt(m_sold)} qop sotdi")
    if ca["perDay"] > 0:
        cover = f" → qoldiq ~{sa.fmt(ca['cover'])} kunga yetadi" if ca["cover"] is not None else ""
        lines.append(f"⚡ Oyiga ~{sa.fmt(ca['monthly'])} qop sotyapti{cover}")
    if total_value > 0:
        lines.append(f"💰 Sanalgan qoldiq: {sa.fmt(total_value)} so'm")

    if low:
        lines.append("")
        lines.append(f"⚠️ <b>{sa.LOW_STOCK} tadan kam qoldi:</b> " + ", ".join(low))
        lines.append("👉 Akaga yuk taklif qilish kerak!")
    if stuck:
        lines.append("")
        lines.append(f"🔴 <b>Turib qolgan ({sa.STUCK_DAYS}+ kun sotilmagan):</b> " + ", ".join(stuck))
    if suspicious:
        lines.append("")
        lines.append("❗ <b>Tekshiring:</b> " + ", ".join(
            f"{n} (+{sa.fmt1(q)})" for n, q in suspicious)
            + " — qoldiq hisobdagidan ko'p chiqdi.")
        if date_str >= today_str:
            lines.append("⏳ Bugun yuk berilgan bo'lsa — ertaga sotuv saytga kiritilgach "
                         "natija avtomatik yangilanadi. Aks holda qayta sanash kerak.")
        else:
            lines.append("Sotuv saytga kiritilmagan yoki xato sanalgan bo'lishi mumkin.")
    return "\n".join(lines)


async def notify_count(bot: Bot, agent_id, agent_name, client_name: str,
                       items_by_name: dict, when: dt.datetime, sync_errors=None):
    """agent.py dan sanoq tugagach chaqiriladi. Hech qachon xato ko'tarmaydi."""
    try:
        if not await get_group_chat():
            return
        thread = await thread_for_agent(agent_id)
        sync_errors = sync_errors or []
        if any("MIJOZ topilmadi" in x or "Tarmoq" in x or x.startswith("Xato")
               for x in sync_errors):
            await send(bot, thread,
                       f"⚠️ <b>{e(client_name)}</b> sanog'i saytga yozilmadi "
                       f"(👤 {e(agent_name)}).\nSabab: {e('; '.join(sync_errors))}\n"
                       f"Sanoq botda saqlangan.")
            return

        blob = (await asyncio.to_thread(_http_get_blob))[1]
        cmap = {_norm(c.get("name")): c.get("id") for c in blob.get("clients", [])}
        pmap = {_norm(p.get("name")): p.get("id") for p in blob.get("products", [])}
        site_cid = cmap.get(_norm(client_name))
        pids = [pmap[_norm(n)] for n in items_by_name if _norm(n) in pmap]
        if site_cid is None or not pids:
            return
        d_str, t_str = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")
        try:
            rep = ri.build_report(blob, site_cid, pids, d_str, t_str, agent_name)
            png = await asyncio.to_thread(ri.render_png, rep)
            sent = await send_photo(bot, thread, png, ri.build_caption(rep),
                                    filename=f"sanoq_{d_str}.png")
            if sent:
                await remember_message(site_cid, d_str, t_str, *sent)
                return
        except Exception:
            log.exception("Rasm hisobot tayyorlanmadi — matn ko'rinishida yuboriladi")
        text = build_count_message(blob, site_cid, pids, d_str, t_str, agent_name)
        await send(bot, thread, text)
    except Exception:
        log.exception("Guruhga sanoq xabari yuborilmadi (bot davom etadi)")


# ===========================================================================
# 5. SOTUV KUZATUVCHI (har 15 daqiqa)
# ===========================================================================
def _sig(r) -> str:
    return f"{r.get('id')}|{r.get('clientId')}|{r.get('productId')}|{r.get('date')}|{r.get('qty')}"


def last_counter_from_site(blob, site_client_id):
    """Klentni saytda oxirgi sanagan agent (agentId saqlangan sanoqlardan)."""
    best = None
    for c in blob.get("counts", []):
        if sa._same(c.get("clientId"), site_client_id) and c.get("agentId") is not None:
            key = sa._t(c)
            if best is None or key >= best[0]:
                best = (key, c.get("agentId"), c.get("agent"))
    return (best[1], best[2]) if best else (None, None)


async def last_counter_from_bot(client_name):
    """Zaxira: botning o'z bazasidagi oxirgi haqiqiy (importsiz) sanoq."""
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cur = await conn.execute(
                "SELECT c.agent_id, u.full_name, cl.name FROM counts c "
                "JOIN clients cl ON cl.id = c.client_id "
                "LEFT JOIN users u ON u.id = c.agent_id "
                "WHERE (c.note IS NULL OR c.note != 'saytdan import') "
                "ORDER BY c.count_date DESC, c.created_at DESC")
            want = _norm(client_name)
            for agent_id, full_name, cname in await cur.fetchall():
                if _norm(cname) == want:
                    return agent_id, full_name
    except Exception:
        log.exception("bot bazasidan agent topilmadi")
    return None, None


def build_sales_block(blob_before, blob_after, site_client_id, new_sales):
    """Bitta klent bo'yicha: yangi sotuvlar + yangilangan sanoq natijalari."""
    clients, products = sa.maps(blob_after)
    client = clients.get(str(site_client_id), {})
    lines = [f"🏬 <b>{e(client.get('name', site_client_id))}</b>"
             + (f" — {e(client['region'])}" if client.get("region") else "")]
    for s in sorted(new_sales, key=lambda r: (str(r.get("date")), str(r.get("productId")))):
        p = products.get(str(s.get("productId")), {})
        lines.append(f"  • {e(p.get('name', s.get('productId')))} — "
                     f"{sa.fmt1(sa._num(s.get('qty')))} {_unit(p)} ({sa.ddmm(s.get('date'))})")

    # Sotuv sanasi oldingi sanoqqa tushsa -> o'sha sanoq natijasi o'zgaradi
    for pid in sorted({s.get("productId") for s in new_sales}, key=str):
        old = {i["countId"]: i for i in
               sa.analyze_client_product(blob_before, site_client_id, pid)["intervals"]}
        new = sa.analyze_client_product(blob_after, site_client_id, pid)["intervals"]
        pname = e(products.get(str(pid), {}).get("name", pid))
        for iv in new:
            o = old.get(iv["countId"])
            if o and abs(o["rawSold"] - iv["rawSold"]) > 0.001:
                was = (f"hisobdan +{sa.fmt1(-o['rawSold'])} ko'p edi" if o["rawSold"] < -0.001
                       else f"avval {sa.fmt1(o['rawSold'])} edi")
                now = (f"hali ham hisobdan +{sa.fmt1(-iv['rawSold'])} ko'p ❗"
                       if iv["rawSold"] < -0.001 else f"<b>sotdi {sa.fmt1(iv['rawSold'])}</b>")
                lines.append(f"  ♻️ {sa.ddmm(iv['to'])} sanoq yangilandi: {pname} — {now} ({was})")
    return "\n".join(lines)


async def check_new_sales(bot: Bot):
    """Saytdagi yangi sotuvlarni topib, guruhga yuboradi."""
    if _watch_lock.locked():
        return
    async with _watch_lock:
        if not await get_group_chat():
            return
        blob = (await asyncio.to_thread(_http_get_blob))[1]
        sales = [s for s in blob.get("sales", []) if isinstance(s, dict)]
        current = {_sig(s) for s in sales}

        seen_raw = await get_setting("seen_sales")
        if seen_raw is None:
            # Birinchi ishga tushish: eski sotuvlarni guruhga to'kib yubormaymiz
            await set_setting("seen_sales", json.dumps(sorted(current)))
            log.info("Sotuv kuzatuvchi: boshlang'ich holat saqlandi (%s ta)", len(current))
            return
        seen = set(json.loads(seen_raw))
        new_sales = [s for s in sales if _sig(s) not in seen]
        if not new_sales:
            if current != seen:  # o'chirilganlar — ro'yxatni ixchamlash
                await set_setting("seen_sales", json.dumps(sorted(current)))
            return

        new_sigs = {_sig(s) for s in new_sales}
        blob_before = dict(blob)
        blob_before["sales"] = [s for s in sales if _sig(s) not in new_sigs]

        # Klent bo'yicha guruhlash -> agent topici bo'yicha guruhlash
        by_client = {}
        for s in new_sales:
            by_client.setdefault(str(s.get("clientId")), []).append(s)
        clients, _ = sa.maps(blob)
        by_thread = {}
        for cid, rows in by_client.items():
            agent_id, _name = last_counter_from_site(blob, cid)
            if agent_id is None:
                agent_id, _name = await last_counter_from_bot(clients.get(cid, {}).get("name"))
            thread = await thread_for_agent(agent_id)
            by_thread.setdefault(thread, []).append(
                build_sales_block(blob_before, blob, cid, rows))

        stamp = sa.uz_now().strftime("%d.%m %H:%M")
        for thread, blocks in by_thread.items():
            head = f"🚚 <b>Saytga sotuv kiritildi</b> ({stamp})"
            ok = await send(bot, thread, head + "\n\n" + "\n\n".join(blocks))
            if not ok:
                return  # keyingi safar qayta urinadi (seen yangilanmaydi)

        await set_setting("seen_sales", json.dumps(sorted(current)))
        log.info("Sotuv kuzatuvchi: %s ta yangi sotuv guruhga yuborildi", len(new_sales))


async def sales_watcher(bot: Bot):
    """bot.py da fon vazifasi sifatida ishga tushadi."""
    await asyncio.sleep(60)
    while True:
        try:
            await check_new_sales(bot)
        except Exception:
            log.exception("Sotuv kuzatuvchida xato (keyingi safar qayta urinadi)")
        await asyncio.sleep(max(SALES_CHECK_MIN, 1) * 60)


@router.message(Command("sotuv_tekshir"))
async def manual_check(message: Message):
    """Admin: kutmasdan hozir tekshirish."""
    if not await _is_admin(message.from_user.id):
        return
    await message.reply("Saytdagi sotuvlar tekshirilyapti...")
    try:
        await check_new_sales(message.bot)
        await message.reply("✅ Tekshirildi.")
    except Exception as ex:
        await message.reply(f"Xato: {e(ex)}")

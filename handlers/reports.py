"""Hisobot handlerlari: kunlik, oylik Excel va tezkor tahlil (menejer/admin)."""
import calendar
import datetime as dt

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
import keyboards as kb
import analytics
import excel_report as xls
from states import ReportDate

router = Router()

UZ_MONTHS = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


async def _can_report(user_id):
    u = await db.get_user(user_id)
    return u and u["role"] in ("manager", "admin")


# ---------------------------------------------------------------------------
# KUNLIK
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_DAILY)
async def daily_menu(message: Message, state: FSMContext):
    if not await _can_report(message.from_user.id):
        return
    b = InlineKeyboardBuilder()
    b.button(text="Bugun", callback_data="rep:day:today")
    b.button(text="Kecha", callback_data="rep:day:yesterday")
    b.button(text="📅 Boshqa sana", callback_data="rep:day:other")
    b.adjust(2, 1)
    await message.answer("Kunlik hisobot — qaysi kun?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("rep:day:"))
async def daily_pick(call, state: FSMContext):
    choice = call.data.split(":")[2]
    if choice == "other":
        await state.set_state(ReportDate.waiting_daily)
        await call.message.answer("Sanani yozing (YYYY-MM-DD), masalan 2026-06-01:",
                                  reply_markup=kb.cancel_menu())
        await call.answer()
        return
    date = dt.date.today()
    if choice == "yesterday":
        date -= dt.timedelta(days=1)
    await _send_daily(call.message, date.strftime("%Y-%m-%d"))
    await call.answer()


@router.message(ReportDate.waiting_daily)
async def daily_custom(message: Message, state: FSMContext):
    try:
        dt.datetime.strptime(message.text.strip(), "%Y-%m-%d")
    except ValueError:
        await message.answer("Format noto'g'ri. Masalan: 2026-06-01")
        return
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer("⏳ Tayyorlanmoqda...", reply_markup=kb.main_menu(user["role"]))
    await _send_daily(message, message.text.strip())


async def _send_daily(message: Message, date_str: str):
    rows = await db.get_counts_by_date(date_str)
    data = xls.build_daily_report(date_str, rows)
    file = BufferedInputFile(data, filename=f"kunlik_{date_str}.xlsx")
    cap = (f"📊 Kunlik hisobot: {date_str}\n{len(rows)} ta yozuv"
           if rows else f"📊 {date_str}: sanash bo'lmagan")
    await message.answer_document(file, caption=cap)


# ---------------------------------------------------------------------------
# OYLIK
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_MONTHLY)
async def monthly_menu(message: Message, state: FSMContext):
    if not await _can_report(message.from_user.id):
        return
    today = dt.date.today()
    prev = (today.replace(day=1) - dt.timedelta(days=1))
    b = InlineKeyboardBuilder()
    b.button(text=f"{UZ_MONTHS[today.month]} (shu oy)",
             callback_data=f"rep:mon:{today.year}-{today.month:02d}")
    b.button(text=f"{UZ_MONTHS[prev.month]} (o'tgan oy)",
             callback_data=f"rep:mon:{prev.year}-{prev.month:02d}")
    b.button(text="📅 Boshqa oy", callback_data="rep:mon:other")
    b.adjust(1)
    await message.answer("Oylik hisobot — qaysi oy?", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("rep:mon:"))
async def monthly_pick(call, state: FSMContext):
    val = call.data.split(":", 2)[2]
    if val == "other":
        await state.set_state(ReportDate.waiting_monthly)
        await call.message.answer("Oyni yozing (YYYY-MM), masalan 2026-05:",
                                  reply_markup=kb.cancel_menu())
        await call.answer()
        return
    year, month = map(int, val.split("-"))
    await call.answer("Tayyorlanmoqda...")
    await _send_monthly(call.message, year, month)


@router.message(ReportDate.waiting_monthly)
async def monthly_custom(message: Message, state: FSMContext):
    try:
        d = dt.datetime.strptime(message.text.strip(), "%Y-%m")
    except ValueError:
        await message.answer("Format noto'g'ri. Masalan: 2026-05")
        return
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer("⏳ Tayyorlanmoqda...", reply_markup=kb.main_menu(user["role"]))
    await _send_monthly(message, d.year, d.month)


async def _send_monthly(message: Message, year: int, month: int):
    start = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year}-{month:02d}-{last_day:02d}"
    rows = await db.get_counts_in_period(start, end)
    title = f"{UZ_MONTHS[month]} {year}"
    data = xls.build_monthly_report(title, rows)
    file = BufferedInputFile(data, filename=f"oylik_{year}_{month:02d}.xlsx")
    n_clients = len(set(r["client_name"] for r in rows)) if rows else 0
    cap = (f"📈 Oylik hisobot: {title}\n{n_clients} ta klent"
           if rows else f"📈 {title}: ma'lumot yo'q")
    await message.answer_document(file, caption=cap)


# ---------------------------------------------------------------------------
# TEZKOR TAHLIL (matnli)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_ANALYZE)
async def quick_analyze(message: Message):
    if not await _can_report(message.from_user.id):
        return
    today = dt.date.today()
    start = (today - dt.timedelta(days=60)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    rows = await db.get_counts_in_period(start, end)
    analysis = analytics.analyze_period(rows)
    if not analysis:
        await message.answer("So'nggi 60 kunda yetarli ma'lumot yo'q.")
        return

    vals = list(analysis.values())
    stuck = [a for a in vals if a["status"] in ("qotgan", "sekin")]
    fast = sorted([a for a in vals if a["sold_per_day"] > 0],
                  key=lambda x: x["sold_per_day"], reverse=True)[:5]

    out = ["🔍 <b>Tezkor tahlil (so'nggi 60 kun)</b>\n"]

    if fast:
        out.append("🟢 <b>Tez sotayotgan klentlar:</b>")
        for a in fast:
            out.append(f"  • {a['client_name']} — {a['sold_per_day']:.1f} dona/kun")
        out.append("")

    if stuck:
        out.append("🔴 <b>Yuk qotib qolgan / sekin:</b>")
        for a in stuck:
            out.append(f"  • {a['client_name']} — qoldiq {a['last_value']:,.0f} so'm "
                       f"({analytics.status_text(a['status'])})")

    if not fast and not stuck:
        out.append("Hozircha tahlil uchun yetarli o'zgarish yo'q.")

    await message.answer("\n".join(out))

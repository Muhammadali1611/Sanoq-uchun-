"""Umumiy handlerlar: /start, avtomatik ro'yxat so'rovi, qidiruv, bekor qilish."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from states import SearchClient

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if user:
        await message.answer(
            f"Assalomu alaykum, {user['full_name']}! 👋\n"
            f"Rolingiz: <b>{_role_uz(user['role'])}</b>",
            reply_markup=kb.main_menu(user["role"]),
        )
        return

    # Begona odam — adminga avtomatik so'rov boradi
    uid = message.from_user.id
    name = message.from_user.full_name
    uname = f" (@{message.from_user.username})" if message.from_user.username else ""
    admins = await db.get_all_admins()
    if admins:
        for adm in admins:
            try:
                await message.bot.send_message(
                    adm["id"],
                    f"🆕 <b>Yangi foydalanuvchi botga kirmoqchi:</b>\n"
                    f"👤 {name}{uname}\n🆔 <code>{uid}</code>\n\nKiritamizmi?",
                    reply_markup=kb.approve_kb(uid),
                )
            except Exception:
                pass
        await message.answer(
            "Salom! So'rovingiz adminga yuborildi. ✅\n"
            "Admin tasdiqlagach, /start bosing."
        )
    else:
        await message.answer(
            "Tizimda admin yo'q. Iltimos, .env faylga ADMIN_IDS ni yozing.\n"
            f"Sizning ID: <code>{uid}</code>"
        )


# ---------------------------------------------------------------------------
# Klent qidirish (barcha rollar) — oxirgi sanash kartochkasi
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_SEARCH)
async def search_start(message: Message, state: FSMContext):
    if not await db.get_user(message.from_user.id):
        return
    await state.set_state(SearchClient.waiting)
    await message.answer("Klent ismini yozing (qisman bo'lsa ham bo'ladi):",
                         reply_markup=kb.cancel_menu())


@router.message(SearchClient.waiting)
async def search_do(message: Message, state: FSMContext):
    q = message.text.strip()
    matches = await db.search_clients(q)
    if not matches:
        await message.answer("Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    await state.update_data(q=q)
    await message.answer(f"🔍 «{q}» — {len(matches)} ta topildi:",
                         reply_markup=kb.clients_kb(matches, "info"))


@router.callback_query(F.data.startswith("info:pg:"))
async def search_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[2])
    data = await state.get_data()
    matches = await db.search_clients(data.get("q", ""))
    await call.message.edit_reply_markup(reply_markup=kb.clients_kb(matches, "info", page))
    await call.answer()


@router.callback_query(F.data.startswith("info:cl:"))
async def search_card(call: CallbackQuery):
    cid = int(call.data.split(":")[2])
    client = await db.get_client(cid)
    sess = await db.get_last_session_for_client(cid)
    region = f"\n📍 Region: {client['region']}" if client.get("region") else ""
    phone = f"\n📞 {client['phone']}" if client.get("phone") else ""
    text = [f"🏬 <b>{client['name']}</b>{region}{phone}"]
    if sess:
        text.append(f"\n🗓 Oxirgi sanash: {sess['count_date']}")
        total = 0.0
        for pid, qty in sess["items"].items():
            p = await db.get_product(pid)
            if not p:
                continue
            val = qty * p["price"]
            total += val
            text.append(f"  • {p['name']}: {qty:g} {p['unit']} = {val:,.0f} so'm")
        text.append(f"\n💰 Jami qoldiq: <b>{total:,.0f} so'm</b>")
    else:
        text.append("\nHali sanalmagan.")
    await call.message.answer("\n".join(text))
    await call.answer()


# ---------------------------------------------------------------------------
# Bekor qilish
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_CANCEL)
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    role = user["role"] if user else "agent"
    await message.answer("Bekor qilindi.", reply_markup=kb.main_menu(role))


# ---------------------------------------------------------------------------
# Ro'yxatlar
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_CLIENTS)
async def list_clients(message: Message):
    if not await db.get_user(message.from_user.id):
        return
    regions = await db.get_regions()
    if not regions:
        await message.answer("Klentlar hali qo'shilmagan.")
        return
    total = sum(r["cnt"] for r in regions)
    lines = [f"👥 <b>Klentlar:</b> jami {total} ta, {len(regions)} ta region\n"]
    lines += [f"📍 {r['region']} — {r['cnt']} ta" for r in regions]
    lines.append("\nAniq klentni topish uchun «🔍 Klent qidirish».")
    await message.answer("\n".join(lines))


@router.message(F.text == kb.BTN_PRODUCTS)
async def list_products(message: Message):
    if not await db.get_user(message.from_user.id):
        return
    products = await db.get_products()
    if not products:
        await message.answer("Tovarlar hali qo'shilmagan.")
        return
    lines = [f"{i+1}. {p['name']} — {p['price']:,.0f} so'm / {p['unit']}"
             for i, p in enumerate(products)]
    await message.answer("📦 <b>Tovarlar:</b>\n" + "\n".join(lines))


def _role_uz(role: str) -> str:
    return {"admin": "Admin", "manager": "Menejer", "agent": "Agent"}.get(role, role)

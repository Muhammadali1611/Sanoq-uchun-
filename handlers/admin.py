"""Admin va menejer handlerlari."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from states import AddUser, AddClient, AddProduct, DelClient, EditCount

router = Router()


async def _role(user_id):
    u = await db.get_user(user_id)
    return u["role"] if u else None


# ---------------------------------------------------------------------------
# So'rovni tasdiqlash (admin)
# ---------------------------------------------------------------------------
@router.callback_query(F.data.startswith("appr:"))
async def approve_user(call: CallbackQuery):
    if await _role(call.from_user.id) != "admin":
        await call.answer("Faqat admin", show_alert=True)
        return
    _, role, uid = call.data.split(":")
    uid = int(uid)
    if role == "no":
        await call.message.edit_text("❌ So'rov rad etildi.")
        try:
            await call.bot.send_message(uid, "Afsuski, so'rovingiz rad etildi.")
        except Exception:
            pass
        await call.answer()
        return
    try:
        chat = await call.bot.get_chat(uid)
        name = chat.full_name
    except Exception:
        name = "Foydalanuvchi"
    await db.add_user(uid, name, role, added_by=call.from_user.id)
    role_uz = "Agent" if role == "agent" else "Menejer"
    await call.message.edit_text(f"✅ {name} — {role_uz} sifatida qo'shildi.")
    try:
        await call.bot.send_message(
            uid, f"✅ Siz {role_uz} sifatida ro'yxatga olindingiz!",
            reply_markup=kb.main_menu(role),
        )
    except Exception:
        pass
    await call.answer("Qo'shildi")


# ---------------------------------------------------------------------------
# Qo'lda agent / menejer qo'shish (admin)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_ADD_AGENT)
async def add_agent_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) != "admin":
        return
    await state.update_data(new_role="agent")
    await state.set_state(AddUser.waiting_id)
    await message.answer(
        "Yangi <b>agent</b>ning Telegram ID raqamini yuboring.\n"
        "(ID ni bilmasa, u botga /start bosib, ID'ni sizga aytadi)",
        reply_markup=kb.cancel_menu(),
    )


@router.message(F.text == kb.BTN_ADD_MANAGER)
async def add_manager_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) != "admin":
        return
    await state.update_data(new_role="manager")
    await state.set_state(AddUser.waiting_id)
    await message.answer(
        "Yangi <b>menejer</b>ning Telegram ID raqamini yuboring.",
        reply_markup=kb.cancel_menu(),
    )


@router.message(AddUser.waiting_id)
async def add_user_id(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("ID faqat raqamlardan iborat bo'lishi kerak. Qayta yuboring.")
        return
    await state.update_data(new_id=int(text))
    await state.set_state(AddUser.waiting_name)
    await message.answer("Ism-familiyasini yozing:")


@router.message(AddUser.waiting_name)
async def add_user_name(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.add_user(data["new_id"], message.text.strip(), data["new_role"],
                      added_by=message.from_user.id)
    role_uz = "Agent" if data["new_role"] == "agent" else "Menejer"
    await state.clear()
    await message.answer(f"✅ {message.text.strip()} — {role_uz} qo'shildi.",
                         reply_markup=kb.main_menu("admin"))
    try:
        await message.bot.send_message(
            data["new_id"], f"✅ Siz {role_uz} sifatida ro'yxatga olindingiz! /start bosing.")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Xodimlar ro'yxati (admin)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_STAFF)
async def staff_list(message: Message):
    if await _role(message.from_user.id) != "admin":
        return
    lines = []
    for role, title in (("admin", "👑 Adminlar"), ("manager", "🧑‍💼 Menejerlar"), ("agent", "🚶 Agentlar")):
        users = await db.get_users_by_role(role)
        lines.append(f"\n<b>{title}:</b>")
        if users:
            lines += [f"  • {u['full_name']} (<code>{u['id']}</code>)" for u in users]
        else:
            lines.append("  —")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# Klent qo'shish (admin + menejer) — region bilan
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_ADD_CLIENT)
async def add_client_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) not in ("admin", "manager"):
        return
    await state.set_state(AddClient.waiting_name)
    await message.answer("Yangi klent nomini yozing:", reply_markup=kb.cancel_menu())


@router.message(AddClient.waiting_name)
async def add_client_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddClient.waiting_region)
    regions = await db.get_regions()
    hint = ", ".join(r["region"] for r in regions[:8]) if regions else "masalan: Qo'qon"
    await message.answer(f"Regionini yozing (mavjudlardan biri yoki yangi):\n<i>{hint}...</i>")


@router.message(AddClient.waiting_region)
async def add_client_region(message: Message, state: FSMContext):
    region = message.text.strip()
    await state.update_data(region=None if region in ("-", "—") else region)
    await state.set_state(AddClient.waiting_phone)
    await message.answer("Telefon raqamini yozing (yoki «-»):")


@router.message(AddClient.waiting_phone)
async def add_client_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    phone = None if message.text.strip() in ("-", "—") else message.text.strip()
    await db.add_client(data["name"], region=data.get("region"), phone=phone)
    role = await _role(message.from_user.id)
    await state.clear()
    reg = f" ({data['region']})" if data.get("region") else ""
    await message.answer(f"✅ Klent qo'shildi: <b>{data['name']}</b>{reg}",
                         reply_markup=kb.main_menu(role))


# ---------------------------------------------------------------------------
# Tovar qo'shish (admin + menejer)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_ADD_PRODUCT)
async def add_product_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) not in ("admin", "manager"):
        return
    await state.set_state(AddProduct.waiting_name)
    await message.answer("Yangi tovar nomini yozing:", reply_markup=kb.cancel_menu())


@router.message(AddProduct.waiting_name)
async def add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.waiting_unit)
    await message.answer("O'lchov birligini yozing (masalan: dona, qop, kg):")


@router.message(AddProduct.waiting_unit)
async def add_product_unit(message: Message, state: FSMContext):
    await state.update_data(unit=message.text.strip())
    await state.set_state(AddProduct.waiting_price)
    await message.answer("1 birlik narxini so'mda yozing (masalan: 34500):")


@router.message(AddProduct.waiting_price)
async def add_product_price(message: Message, state: FSMContext):
    raw = message.text.strip().replace(" ", "").replace(",", "")
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Narx noto'g'ri. Faqat raqam yozing (masalan: 34500).")
        return
    data = await state.get_data()
    await db.add_product(data["name"], data["unit"], price)
    role = await _role(message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Tovar qo'shildi: <b>{data['name']}</b> — {price:,.0f} so'm / {data['unit']}",
        reply_markup=kb.main_menu(role),
    )


# ---------------------------------------------------------------------------
# Klent o'chirish (admin + menejer)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_DEL_CLIENT)
async def del_client_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) not in ("admin", "manager"):
        return
    await state.set_state(DelClient.waiting)
    await message.answer("O'chiriladigan klent ismini yozing:", reply_markup=kb.cancel_menu())


@router.message(DelClient.waiting)
async def del_client_search(message: Message, state: FSMContext):
    matches = await db.search_clients(message.text.strip())
    if not matches:
        await message.answer("Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    await message.answer("Qaysi klentni o'chirasiz?",
                         reply_markup=kb.clients_kb(matches, "delc"))


@router.callback_query(F.data.startswith("delc:cl:"))
async def del_client_pick(call: CallbackQuery, state: FSMContext):
    cid = int(call.data.split(":")[2])
    client = await db.get_client(cid)
    await call.message.edit_text(
        f"❗ <b>{client['name']}</b> o'chirilsinmi?\n"
        "(Tarix saqlanadi, faqat ro'yxatdan yashiriladi)",
        reply_markup=kb.confirm_kb("delc", cid),
    )
    await call.answer()


@router.callback_query(F.data.startswith("delc:yes:"))
async def del_client_yes(call: CallbackQuery, state: FSMContext):
    cid = int(call.data.split(":")[2])
    client = await db.get_client(cid)
    await db.delete_client(cid)
    await state.clear()
    await call.message.edit_text(f"🗑 <b>{client['name']}</b> o'chirildi.")
    await call.answer("O'chirildi")


@router.callback_query(F.data.startswith("delc:no:"))
async def del_client_no(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()


# ---------------------------------------------------------------------------
# Tovar o'chirish (admin + menejer)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_DEL_PRODUCT)
async def del_product_start(message: Message):
    if await _role(message.from_user.id) not in ("admin", "manager"):
        return
    products = await db.get_products()
    if not products:
        await message.answer("Tovarlar yo'q.")
        return
    await message.answer("Qaysi tovarni o'chirasiz?",
                         reply_markup=kb.products_del_kb(products))


@router.callback_query(F.data.startswith("delp:pr:"))
async def del_product_pick(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    p = await db.get_product(pid)
    await call.message.edit_text(
        f"❗ <b>{p['name']}</b> o'chirilsinmi?",
        reply_markup=kb.confirm_kb("delp", pid),
    )
    await call.answer()


@router.callback_query(F.data.startswith("delp:yes:"))
async def del_product_yes(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    p = await db.get_product(pid)
    await db.delete_product(pid)
    await call.message.edit_text(f"🗑 <b>{p['name']}</b> o'chirildi.")
    await call.answer("O'chirildi")


@router.callback_query(F.data.startswith("delp:no:"))
async def del_product_no(call: CallbackQuery):
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()


# ---------------------------------------------------------------------------
# Sanashni tuzatish / o'chirish (admin + menejer)
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_EDIT_COUNT)
async def edit_count_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) not in ("admin", "manager"):
        return
    await state.set_state(EditCount.searching)
    await message.answer("Tuzatmoqchi bo'lgan klent ismini yozing:", reply_markup=kb.cancel_menu())


@router.message(EditCount.searching)
async def edit_count_search(message: Message, state: FSMContext):
    matches = await db.search_clients(message.text.strip())
    if not matches:
        await message.answer("Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    await message.answer("Klentni tanlang:",
                         reply_markup=kb.clients_kb(matches, "edit"))


@router.callback_query(F.data.startswith("edit:cl:"))
async def edit_pick_client(call: CallbackQuery, state: FSMContext):
    cid = int(call.data.split(":")[2])
    sessions = await db.get_client_recent_counts(cid, limit=5)
    if not sessions:
        await call.message.answer("Bu klentda hali sanash yo'q.")
        await call.answer()
        return
    client = await db.get_client(cid)
    await state.set_state(EditCount.choosing_session)
    await call.message.edit_text(
        f"📋 <b>{client['name']}</b> — oxirgi sanashlar:\nQaysi birini tuzatamiz?",
        reply_markup=kb.sessions_kb(sessions),
    )
    await call.answer()


@router.callback_query(F.data.startswith("edit:cs:"))
async def edit_pick_session(call: CallbackQuery, state: FSMContext):
    count_id = int(call.data.split(":")[2])
    info = await db.get_count_by_id(count_id)
    sessions = await db.get_client_recent_counts(info["client_id"], limit=5)
    sess = next((s for s in sessions if s["id"] == count_id), None)
    if not sess:
        await call.answer("Topilmadi", show_alert=True)
        return
    items_txt = "\n".join(
        f"  • {it['product_name']}: {it['quantity']:g} {it['unit']}"
        for it in sess["items"]
    )
    await state.update_data(edit_count_id=count_id)
    await call.message.edit_text(
        f"📅 <b>{info['count_date']}</b> — {info['agent_name']}\n"
        f"🏬 {info['client_name']}\n\n{items_txt}\n\nNima qilamiz?",
        reply_markup=kb.edit_actions_kb(count_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("edit:del:"))
async def edit_delete_confirm(call: CallbackQuery):
    count_id = int(call.data.split(":")[2])
    await call.message.edit_text(
        "❗ Bu sanash butunlay o'chirilsinmi? (qaytarib bo'lmaydi)",
        reply_markup=kb.confirm_kb("editdel", count_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("editdel:yes:"))
async def edit_delete_yes(call: CallbackQuery, state: FSMContext):
    count_id = int(call.data.split(":")[2])
    await db.delete_count(count_id)
    await state.clear()
    await call.message.edit_text("🗑 Sanash o'chirildi.")
    await call.answer("O'chirildi")


@router.callback_query(F.data.startswith("editdel:no:"))
async def edit_delete_no(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Bekor qilindi.")
    await call.answer()


@router.callback_query(F.data.startswith("edit:fix:"))
async def edit_fix_show_items(call: CallbackQuery, state: FSMContext):
    count_id = int(call.data.split(":")[2])
    sessions = await db.get_client_recent_counts(
        (await db.get_count_by_id(count_id))["client_id"], limit=5
    )
    sess = next((s for s in sessions if s["id"] == count_id), None)
    if not sess:
        await call.answer("Topilmadi", show_alert=True)
        return
    await state.set_state(EditCount.choosing_item)
    await state.update_data(edit_count_id=count_id)
    await call.message.edit_text(
        "Qaysi tovar miqdorini tuzatamiz?",
        reply_markup=kb.count_items_edit_kb(sess["items"], count_id),
    )
    await call.answer()


@router.callback_query(EditCount.choosing_item, F.data.startswith("edit:it:"))
async def edit_pick_item(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    count_id = int(parts[2])
    product_id = int(parts[3])
    p = await db.get_product(product_id)
    await state.update_data(edit_product_id=product_id, edit_count_id=count_id)
    await state.set_state(EditCount.entering_qty)
    await call.message.answer(
        f"«{p['name']}» — to'g'ri miqdorni yozing ({p['unit']}):"
    )
    await call.answer()


@router.message(EditCount.entering_qty)
async def edit_enter_qty(message: Message, state: FSMContext):
    raw = message.text.strip().replace(" ", "").replace(",", ".")
    try:
        qty = float(raw)
    except ValueError:
        await message.answer("Faqat raqam yozing.")
        return
    data = await state.get_data()
    await db.update_count_item(data["edit_count_id"], data["edit_product_id"], qty)
    p = await db.get_product(data["edit_product_id"])
    role = await _role(message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Tuzatildi: <b>{p['name']}</b> → {qty:g} {p['unit']}",
        reply_markup=kb.main_menu(role),
    )

"""Admin va menejer handlerlari."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import html
import logging

import agent_topics
import catalog_sync
import count_sync
import database as db
import site_analysis as sa
import keyboards as kb
from states import AddUser, AddClient, AddProduct, DelClient, EditCount

router = Router()
log = logging.getLogger("admin")


async def _topic_note(uid, name, role):
    if role != "agent":
        return ""
    try:
        t = await agent_topics.auto_assign(uid, name)
    except Exception:
        log.exception("topic avtomatik ulanmadi")
        t = None
    if t:
        return f"\n📌 Guruhdagi «{html.escape(t)}» topiciga avtomatik ulandi."
    if (await gn_topic_map()).get(int(uid)):
        return ""
    return ("\n⚠️ Mos topic topilmadi — guruhda uning topiciga kirib /topic yozing "
            "va shu agentni tanlang.")


async def gn_topic_map():
    import group_notify
    return await group_notify.get_topic_map()


async def _bot_session(count_id):
    """Botdagi sanoq: (info, [(tovar, son), ...]) yoki (None, [])."""
    info = await db.get_count_by_id(count_id)
    if not info:
        return None, []
    for s in await db.get_client_recent_counts(info["client_id"], limit=50):
        if s["id"] == count_id:
            return info, [(it["product_name"], float(it["quantity"])) for it in s["items"]]
    return info, []


async def _site_ref(info, items):
    try:
        return await count_sync.find_site_session(
            info["client_name"], info["count_date"], items, info.get("agent_id"))
    except Exception:
        log.exception("saytdagi mos sanoq qidirilmadi")
        return "err"


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
    await call.message.edit_text(f"✅ {name} — {role_uz} sifatida qo'shildi."
                                 + await _topic_note(uid, name, role))
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
    note = await _topic_note(data["new_id"], message.text.strip(), data["new_role"])
    await message.answer(f"✅ {message.text.strip()} — {role_uz} qo'shildi." + note,
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
# Klent qo'shish (admin + menejer + agent) — region TUGMA orqali tanlanadi
# ---------------------------------------------------------------------------
@router.message(F.text == kb.BTN_ADD_CLIENT)
async def add_client_start(message: Message, state: FSMContext):
    if await _role(message.from_user.id) not in ("admin", "manager", "agent"):
        return
    await state.set_state(AddClient.waiting_name)
    await message.answer("Yangi klent nomini yozing:", reply_markup=kb.cancel_menu())


@router.message(AddClient.waiting_name)
async def add_client_name(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(name=name)
    regions = await db.get_regions()
    if regions:
        # Mavjud regionlarni tugma qilib beramiz — qo'lda yozilmaydi, dubl ochilmaydi
        await state.set_state(AddClient.waiting_region)
        await message.answer(
            f"<b>{name}</b> — qaysi regionga qo'shamiz?",
            reply_markup=kb.add_client_regions_kb(regions),
        )
    else:
        # Hali biror region yo'q — to'g'ridan-to'g'ri yangi region so'raymiz
        await state.set_state(AddClient.waiting_new_region)
        await message.answer("Region nomini yozing (yoki «-»):",
                             reply_markup=kb.cancel_menu())


@router.callback_query(AddClient.waiting_region, F.data.startswith("acreg:rg:"))
async def add_client_pick_region(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[2])
    regions = await db.get_regions()
    if idx >= len(regions):
        await call.answer("Ro'yxat yangilandi, qaytadan tanlang", show_alert=True)
        await call.message.edit_reply_markup(
            reply_markup=kb.add_client_regions_kb(regions))
        return
    label = regions[idx]["region"]
    # "Boshqa" — bu region NULL bo'lgan klentlar guruhi
    region = None if label == "Boshqa" else label
    await state.update_data(region=region)
    await state.set_state(AddClient.waiting_phone)
    await call.message.edit_text(f"📍 Region: <b>{label}</b>")
    await call.message.answer("Telefon raqamini yozing (yoki «-»):",
                              reply_markup=kb.cancel_menu())
    await call.answer()


@router.callback_query(AddClient.waiting_region, F.data == "acreg:new")
async def add_client_new_region_ask(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddClient.waiting_new_region)
    await call.message.answer("Yangi region nomini yozing:", reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(AddClient.waiting_new_region)
async def add_client_new_region_save(message: Message, state: FSMContext):
    region = message.text.strip()
    await state.update_data(region=None if region in ("-", "—") else region)
    await state.set_state(AddClient.waiting_phone)
    await message.answer("Telefon raqamini yozing (yoki «-»):",
                         reply_markup=kb.cancel_menu())


@router.message(AddClient.waiting_phone)
async def add_client_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    phone = None if message.text.strip() in ("-", "—") else message.text.strip()
    await db.add_client(data["name"], region=data.get("region"), phone=phone)
    await catalog_sync.hide("clients", data["name"], hidden=False)
    await catalog_sync.push_client(data["name"], data.get("region"))   # saytga ham
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
    if await _role(message.from_user.id) not in ("admin", "manager", "agent"):
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
    await catalog_sync.hide("products", data["name"], hidden=False)
    await catalog_sync.push_product(data["name"], price)               # saytga ham
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
    if await _role(message.from_user.id) not in ("admin", "manager", "agent"):
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
    await catalog_sync.hide("clients", client["name"])   # saytdan sync qayta yoqmasin
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
    if await _role(message.from_user.id) not in ("admin", "manager", "agent"):
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
    await catalog_sync.hide("products", p["name"])       # saytdan sync qayta yoqmasin
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
    if await _role(message.from_user.id) not in ("admin", "manager", "agent"):
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
    await call.answer("O'chirilyapti...")
    info, items = await _bot_session(count_id)
    site_txt, grp_txt = "— (saytda topilmadi)", "—"
    if info:
        ref = await _site_ref(info, items)
        if ref == "err":
            await state.clear()
            await call.message.edit_text(
                "❌ Saytga ulanib bo'lmadi — hech narsa o'chirilmadi. Birozdan keyin qayta urinib ko'ring.")
            return
        if ref:
            site_cid, t = ref
            try:
                n = await count_sync.delete_site_session(site_cid, info["count_date"], t)
                site_txt = f"{n} ta yozuv o'chirildi"
            except Exception:
                log.exception("saytdan o'chirilmadi")
                await state.clear()
                await call.message.edit_text(
                    "❌ Saytdan o'chirib bo'lmadi — hech narsa o'chirilmadi. Qayta urinib ko'ring.")
                return
            grp_txt = await count_sync.delete_group_report(call.bot, site_cid, info["count_date"], t)
    await db.delete_count(count_id)
    await state.clear()
    await call.message.edit_text(
        f"🗑 Sanash o'chirildi.\n\n• Bot: ✅\n• Sayt: {site_txt}\n• Guruh: {grp_txt}")


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
    p = await db.get_product(data["edit_product_id"])
    info, items = await _bot_session(data["edit_count_id"])
    old_qty = next((q for n, q in items if n == p["name"]), None)
    ref = await _site_ref(info, items) if info else None
    if ref == "err":
        await message.answer("❌ Saytga ulanib bo'lmadi — hech narsa o'zgarmadi. "
                             "Birozdan keyin qayta yozib ko'ring.")
        return
    site_txt = "— (saytda topilmadi)"
    if ref:
        site_cid, t = ref
        try:
            n = await count_sync.update_site_qty(site_cid, info["count_date"], t, p["name"], qty)
            site_txt = "✅" if n else "— (bu tovar saytdagi sanoqda yo'q)"
        except Exception:
            log.exception("saytda tuzatilmadi")
            await message.answer("❌ Saytda tuzatib bo'lmadi — hech narsa o'zgarmadi. Qayta urinib ko'ring.")
            return
        if n:
            await count_sync.note_group_report(
                message.bot, site_cid, info["count_date"], t,
                f"✏️ Tuzatildi: <b>{html.escape(p['name'])}</b> — "
                f"{sa.fmt1(old_qty) if old_qty is not None else '?'} → <b>{sa.fmt1(qty)}</b> {p['unit']}")
    await db.update_count_item(data["edit_count_id"], data["edit_product_id"], qty)
    role = await _role(message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Tuzatildi: <b>{p['name']}</b> → {qty:g} {p['unit']}\n• Sayt: {site_txt}",
        reply_markup=kb.main_menu(role),
    )

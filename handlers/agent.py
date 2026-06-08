"""Sanash jarayoni (agent/menejer): region -> klent (yoki qidiruv) -> tovar."""
import datetime as dt

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from states import Counting

router = Router()


async def _can_count(user_id):
    u = await db.get_user(user_id)
    return u and u["role"] in ("agent", "manager", "admin")


@router.message(F.text == kb.BTN_COUNT)
async def count_start(message: Message, state: FSMContext):
    if not await _can_count(message.from_user.id):
        return
    regions = await db.get_regions()
    if not regions:
        await message.answer("Klentlar yo'q. Avval klent qo'shilishi kerak.")
        return
    await state.set_state(Counting.choosing_region)
    await message.answer("📍 Qaysi regiondan boshlaymiz?",
                         reply_markup=kb.regions_kb(regions, action="cnt"))


@router.callback_query(Counting.choosing_region, F.data == "cnt:srch")
@router.callback_query(Counting.choosing_client, F.data == "cnt:srch")
async def count_search_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(Counting.searching)
    await call.message.answer("Klent ismini yozing (qisman bo'lsa ham bo'ladi):",
                              reply_markup=kb.cancel_menu())
    await call.answer()


@router.message(Counting.searching)
async def count_search_do(message: Message, state: FSMContext):
    q = message.text.strip()
    matches = await db.search_clients(q)
    if not matches:
        await message.answer("Topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return
    await state.update_data(list_mode="search", list_key=q, page=0)
    await state.set_state(Counting.choosing_client)
    await message.answer(
        f"🔍 «{q}» bo'yicha {len(matches)} ta topildi:",
        reply_markup=kb.clients_kb(matches, "cnt", 0, back="cnt:back"),
    )


@router.callback_query(Counting.choosing_region, F.data.startswith("cnt:rg:"))
async def count_pick_region(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[2])
    regions = await db.get_regions()
    if idx >= len(regions):
        await call.answer("Qaytadan urinib ko'ring", show_alert=True)
        return
    region = regions[idx]["region"]
    clients = await db.get_clients_by_region(region)
    await state.update_data(list_mode="region", list_key=region, page=0)
    await state.set_state(Counting.choosing_client)
    await call.message.edit_text(
        f"📍 <b>{region}</b> — klentni tanlang:",
        reply_markup=kb.clients_kb(clients, "cnt", 0, back="cnt:back"),
    )
    await call.answer()


@router.callback_query(Counting.choosing_client, F.data == "cnt:back")
async def count_back_to_regions(call: CallbackQuery, state: FSMContext):
    regions = await db.get_regions()
    await state.set_state(Counting.choosing_region)
    await call.message.edit_text("📍 Qaysi regiondan boshlaymiz?",
                                 reply_markup=kb.regions_kb(regions, "cnt"))
    await call.answer()


async def _current_clients(state: FSMContext):
    data = await state.get_data()
    if data.get("list_mode") == "search":
        return await db.search_clients(data["list_key"])
    return await db.get_clients_by_region(data.get("list_key", ""))


@router.callback_query(Counting.choosing_client, F.data.startswith("cnt:pg:"))
async def count_page(call: CallbackQuery, state: FSMContext):
    page = int(call.data.split(":")[2])
    clients = await _current_clients(state)
    await state.update_data(page=page)
    await call.message.edit_reply_markup(
        reply_markup=kb.clients_kb(clients, "cnt", page, back="cnt:back"))
    await call.answer()


@router.callback_query(Counting.choosing_client, F.data.startswith("cnt:cl:"))
async def count_pick_client(call: CallbackQuery, state: FSMContext):
    client_id = int(call.data.split(":")[2])
    client = await db.get_client(client_id)
    products = await db.get_products()
    if not products:
        await call.message.answer("Tovarlar yo'q. Menejerga ayting.")
        await state.clear()
        await call.answer()
        return
    await state.update_data(client_id=client_id, client_name=client["name"], items={})
    await state.set_state(Counting.choosing_product)
    await call.message.edit_text(
        f"🏬 <b>{client['name']}</b>\nTovarni tanlang va qoldig'ini kiriting:",
        reply_markup=kb.products_kb(products, chosen=set()),
    )
    await call.answer()


@router.callback_query(Counting.choosing_product, F.data.startswith("cnt:pr:"))
async def count_pick_product(call: CallbackQuery, state: FSMContext):
    product_id = int(call.data.split(":")[2])
    product = await db.get_product(product_id)
    await state.update_data(cur_product=product_id)
    await state.set_state(Counting.entering_qty)
    await call.message.answer(
        f"«{product['name']}» — qoldiq qancha ({product['unit']})? Raqam yozing:"
    )
    await call.answer()


@router.message(Counting.entering_qty)
async def count_enter_qty(message: Message, state: FSMContext):
    raw = message.text.strip().replace(" ", "").replace(",", ".")
    try:
        qty = float(raw)
    except ValueError:
        await message.answer("Faqat raqam yozing (masalan: 100).")
        return
    data = await state.get_data()
    items = data.get("items", {})
    items[data["cur_product"]] = qty
    await state.update_data(items=items)
    await state.set_state(Counting.choosing_product)
    products = await db.get_products()
    chosen = set(items.keys())
    await message.answer(
        f"✅ Saqlandi. Sanalganlar: {len(chosen)} ta tovar.\n"
        "Yana tovar tanlang yoki «✔️ Tugatdim» bosing:",
        reply_markup=kb.products_kb(products, chosen=chosen),
    )


@router.callback_query(Counting.choosing_product, F.data == "cnt:done")
async def count_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", {})
    if not items:
        await call.answer("Hech narsa sanamadingiz", show_alert=True)
        return
    client_id = data["client_id"]
    today = dt.date.today().strftime("%Y-%m-%d")

    # Oldingi sanash (taqqoslash uchun) — yangisini saqlashdan oldin olamiz
    prev = await db.get_last_session_for_client(client_id)

    count_id = await db.create_count(client_id, call.from_user.id, today)
    for pid, qty in items.items():
        await db.add_count_item(count_id, pid, qty)

    lines = [f"✅ <b>{data['client_name']}</b> sanaldi ({today})\n"]
    total_value = 0.0
    for pid, qty in items.items():
        p = await db.get_product(pid)
        value = qty * p["price"]
        total_value += value
        line = f"• {p['name']}: <b>{qty:g}</b> {p['unit']} = {value:,.0f} so'm"
        if prev and pid in prev["items"]:
            delta = qty - prev["items"][pid]
            if delta < 0:
                line += f"  →  🟢 {(-delta):g} sotilgan"
            elif delta == 0:
                line += "  →  ⏸ o'zgarmagan"
        lines.append(line)
    lines.append(f"\n💰 Jami qoldiq summasi: <b>{total_value:,.0f} so'm</b>")
    if prev:
        lines.append(f"📅 Oldingi sanash: {prev['count_date']}")

    user = await db.get_user(call.from_user.id)
    await state.clear()
    await call.message.edit_text("\n".join(lines))
    await call.message.answer("Davom etamizmi?", reply_markup=kb.main_menu(user["role"]))
    await call.answer("Saqlandi")

"""Klaviaturalar (menyular)."""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Tugma matnlari ---
BTN_COUNT = "📋 Sanash"
BTN_SEARCH = "🔍 Klent qidirish"
BTN_DAILY = "📊 Kunlik hisobot"
BTN_MONTHLY = "📈 Oylik hisobot"
BTN_ANALYZE = "📉 Tezkor tahlil"
BTN_ADD_CLIENT = "➕ Klent qo'shish"
BTN_ADD_PRODUCT = "➕ Tovar qo'shish"
BTN_DEL_CLIENT = "🗑 Klent o'chirish"
BTN_DEL_PRODUCT = "🗑 Tovar o'chirish"
BTN_CLIENTS = "👥 Klentlar"
BTN_PRODUCTS = "📦 Tovarlar"
BTN_ADD_AGENT = "➕ Agent qo'shish"
BTN_ADD_MANAGER = "➕ Menejer qo'shish"
BTN_STAFF = "🧑‍💼 Xodimlar"
BTN_EDIT_COUNT = "✏️ Tuzatish"
BTN_CANCEL = "❌ Bekor qilish"


def main_menu(role: str) -> ReplyKeyboardMarkup:
    rows = []
    if role == "agent":
        rows = [
            [KeyboardButton(text=BTN_COUNT), KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_CLIENTS), KeyboardButton(text=BTN_PRODUCTS)],
        ]
    elif role == "manager":
        rows = [
            [KeyboardButton(text=BTN_COUNT), KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_DAILY), KeyboardButton(text=BTN_MONTHLY)],
            [KeyboardButton(text=BTN_ANALYZE), KeyboardButton(text=BTN_EDIT_COUNT)],
            [KeyboardButton(text=BTN_ADD_CLIENT), KeyboardButton(text=BTN_ADD_PRODUCT)],
            [KeyboardButton(text=BTN_DEL_CLIENT), KeyboardButton(text=BTN_DEL_PRODUCT)],
            [KeyboardButton(text=BTN_CLIENTS), KeyboardButton(text=BTN_PRODUCTS)],
        ]
    elif role == "admin":
        rows = [
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_EDIT_COUNT)],
            [KeyboardButton(text=BTN_DAILY), KeyboardButton(text=BTN_MONTHLY)],
            [KeyboardButton(text=BTN_ANALYZE)],
            [KeyboardButton(text=BTN_ADD_CLIENT), KeyboardButton(text=BTN_ADD_PRODUCT)],
            [KeyboardButton(text=BTN_DEL_CLIENT), KeyboardButton(text=BTN_DEL_PRODUCT)],
            [KeyboardButton(text=BTN_ADD_AGENT), KeyboardButton(text=BTN_ADD_MANAGER)],
            [KeyboardButton(text=BTN_STAFF)],
            [KeyboardButton(text=BTN_CLIENTS), KeyboardButton(text=BTN_PRODUCTS)],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True
    )


def regions_kb(regions: list, action: str) -> InlineKeyboardMarkup:
    """Regionlar ro'yxati. regions = [{'region':..,'cnt':..}]. action: 'cnt'."""
    kb = InlineKeyboardBuilder()
    for i, rg in enumerate(regions):
        kb.button(text=f"{rg['region']} ({rg['cnt']})", callback_data=f"{action}:rg:{i}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text="🔍 Ism bo'yicha qidirish", callback_data=f"{action}:srch"))
    return kb.as_markup()


def clients_kb(clients: list, action: str, page: int = 0, per_page: int = 8,
               back: str = None) -> InlineKeyboardMarkup:
    """Klentlar ro'yxati (inline). action: 'cnt' | 'delc' | 'info'."""
    kb = InlineKeyboardBuilder()
    start = page * per_page
    chunk = clients[start:start + per_page]
    for cl in chunk:
        kb.button(text=cl["name"], callback_data=f"{action}:cl:{cl['id']}")
    kb.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{action}:pg:{page-1}"))
    if start + per_page < len(clients):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{action}:pg:{page+1}"))
    if nav:
        kb.row(*nav)
    if back:
        kb.row(InlineKeyboardButton(text="🔙 Regionlar", callback_data=back))
    return kb.as_markup()


def products_kb(products: list, chosen: set = None) -> InlineKeyboardMarkup:
    """Sanash uchun tovar tanlash. Tanlanganlar ✅ bilan."""
    chosen = chosen or set()
    kb = InlineKeyboardBuilder()
    for p in products:
        mark = "✅ " if p["id"] in chosen else ""
        kb.button(text=f"{mark}{p['name']}", callback_data=f"cnt:pr:{p['id']}")
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="✔️ Tugatdim", callback_data="cnt:done"))
    return kb.as_markup()


def products_del_kb(products: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p['name']} — {p['price']:,.0f}", callback_data=f"delp:pr:{p['id']}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_kb(prefix: str, item_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ha, o'chir", callback_data=f"{prefix}:yes:{item_id}")
    kb.button(text="❌ Yo'q", callback_data=f"{prefix}:no:{item_id}")
    kb.adjust(2)
    return kb.as_markup()


def approve_kb(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Agent qil", callback_data=f"appr:agent:{user_id}")
    kb.button(text="✅ Menejer qil", callback_data=f"appr:manager:{user_id}")
    kb.button(text="❌ Rad et", callback_data=f"appr:no:{user_id}")
    kb.adjust(2, 1)
    return kb.as_markup()


def sessions_kb(sessions: list) -> InlineKeyboardMarkup:
    """Sanash sessiyalari ro'yxati (oxirgi N ta)."""
    kb = InlineKeyboardBuilder()
    for s in sessions:
        items_txt = ", ".join(
            f"{it['product_name']}: {it['quantity']:g}" for it in s.get("items", [])[:3]
        )
        label = f"📅 {s['count_date']} — {items_txt}"
        if len(label) > 60:
            label = label[:57] + "..."
        kb.button(text=label, callback_data=f"edit:cs:{s['id']}")
    kb.adjust(1)
    return kb.as_markup()


def edit_actions_kb(count_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Miqdorni tuzatish", callback_data=f"edit:fix:{count_id}")
    kb.button(text="🗑 Butunlay o'chirish", callback_data=f"edit:del:{count_id}")
    kb.adjust(1)
    return kb.as_markup()


def count_items_edit_kb(items: list, count_id: int) -> InlineKeyboardMarkup:
    """Sessiya ichidagi tovarlar (tuzatish uchun)."""
    kb = InlineKeyboardBuilder()
    for it in items:
        kb.button(
            text=f"{it['product_name']}: {it['quantity']:g} {it['unit']}",
            callback_data=f"edit:it:{count_id}:{it['product_id']}",
        )
    kb.adjust(1)
    kb.row(InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"edit:cs:{count_id}"))
    return kb.as_markup()

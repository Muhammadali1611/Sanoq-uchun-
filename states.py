"""FSM holatlari (suhbat bosqichlari)."""
from aiogram.fsm.state import State, StatesGroup


class AddUser(StatesGroup):          # admin qo'lda foydalanuvchi qo'shadi
    waiting_id = State()
    waiting_name = State()


class AddClient(StatesGroup):
    waiting_name = State()
    waiting_region = State()
    waiting_phone = State()


class AddProduct(StatesGroup):
    waiting_name = State()
    waiting_unit = State()
    waiting_price = State()


class Counting(StatesGroup):
    choosing_region = State()
    choosing_client = State()
    searching = State()
    choosing_product = State()
    entering_qty = State()


class SearchClient(StatesGroup):
    waiting = State()


class DelClient(StatesGroup):
    waiting = State()


class EditCount(StatesGroup):
    searching = State()
    choosing_session = State()
    choosing_item = State()
    entering_qty = State()


class ReportDate(StatesGroup):
    waiting_daily = State()
    waiting_monthly = State()

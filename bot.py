"""
CP Sklad Bot — asosiy fayl.
Ishga tushirish:  python bot.py
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

import config
import database as db
from handlers import common, admin, agent, reports, count_delete, merge_names
import import_from_site  # saytdan tiklash buyrug'i
import group_notify      # guruhga avto xabarlar (topiclar)
import bot_state         # xodimlar/sozlamalar zaxirasi (Supabase)
import catalog_sync      # tovar/klent ro'yxati saytdan

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi! .env faylga BOT_TOKEN yozing.")

    await db.init_db()
    await group_notify.init()
    await bot_state.restore()   # xodimlar + guruh sozlamalari Supabase'dan
    try:
        await catalog_sync.sync_from_site()   # tovar/klentlar — saytdagi nomlar bilan
    except Exception:
        logging.exception("Katalog saytdan olinmadi (eski ro'yxat bilan davom etiladi)")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Routerlar (tartib muhim: maxsus -> umumiy)
    dp.include_router(group_notify.router)   # /topic, /sotuv_tekshir (guruh)
    dp.include_router(count_delete.router)   # 🗑 Sanoqni o'chirish (admin)
    dp.include_router(merge_names.router)    # /nomlarni_birlashtir (admin)
    dp.include_router(agent.router)
    dp.include_router(import_from_site.router)
    dp.include_router(reports.router)
    dp.include_router(admin.router)
    dp.include_router(common.router)

    me = await bot.get_me()
    logging.info("Bot ishga tushdi: @%s", me.username)
    if config.ADMIN_IDS:
        logging.info("Adminlar: %s", config.ADMIN_IDS)

    # Saytga kiritilgan yangi sotuvlarni kuzatish (har SALES_CHECK_MIN daqiqa)
    watcher = asyncio.create_task(group_notify.sales_watcher(bot))

    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        logging.info("To'xtatildi: %s", e)

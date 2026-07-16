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
from handlers import common, admin, agent, reports
import import_from_site  # saytdan tiklash buyrug'i

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi! .env faylga BOT_TOKEN yozing.")

    await db.init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Routerlar (tartib muhim: maxsus -> umumiy)
    dp.include_router(agent.router)
    dp.include_router(import_from_site.router)
    dp.include_router(reports.router)
    dp.include_router(admin.router)
    dp.include_router(common.router)

    me = await bot.get_me()
    logging.info("Bot ishga tushdi: @%s", me.username)
    if config.ADMIN_IDS:
        logging.info("Adminlar: %s", config.ADMIN_IDS)

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        logging.info("To'xtatildi: %s", e)

"""
CP Sklad Bot — asosiy fayl.
Ishga tushirish:  python bot.py
"""
import asyncio
import logging
import os

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
import agent_topics      # agent -> o'z topici (avtomatik)
import ish_vaqti         # 8:00-20:00 ish vaqti (WORK_HOURS)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi! .env faylga BOT_TOKEN yozing.")
    if not ish_vaqti.ish_vaqtimi():
        logging.info("Ish vaqtidan tashqari — bot ishga tushmaydi (WORK_HOURS=%s)",
                     os.getenv("WORK_HOURS"))
        return

    await db.init_db()
    await group_notify.init()
    await bot_state.restore()   # xodimlar + guruh sozlamalari Supabase'dan
    try:
        await agent_topics.seed()   # Abduqodir/Abdumalik -> o'z topiclari (bir marta)
    except Exception:
        logging.exception("agent/topic boshlang'ich sozlash xatosi")
    try:
        await catalog_sync.sync_from_site()   # tovar/klentlar — saytdagi nomlar bilan
    except Exception:
        logging.exception("Katalog saytdan olinmadi (eski ro'yxat bilan davom etiladi)")
    if config.FRESH_DB:
        # Yangi (volume) baza: oldingi sanoqlarni saytdan avtomatik tiklaymiz
        try:
            st = await import_from_site.run_import()
            logging.info("Yangi baza: saytdan tiklandi — %s", st)
        except Exception:
            logging.exception("Saytdan avtomatik tiklash xatosi (/import_sayt bilan qo'lda qiling)")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(agent_topics.TopicLearner())   # topic nomlarini o'rganadi

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

    guard = asyncio.create_task(ish_vaqti.tugash_kutuvchi(dp.stop_polling))
    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()
        guard.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        logging.info("To'xtatildi: %s", e)

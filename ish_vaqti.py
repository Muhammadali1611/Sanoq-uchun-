# -*- coding: utf-8 -*-
"""
ish_vaqti.py — botni faqat ish vaqtida ishlatish (Railway pulini tejash uchun)
==========================================================================
Railway'da `WORK_HOURS=8-20` o'zgaruvchisi qo'yilsa:
  - bot 20:00 (Toshkent) da o'zi to'xtaydi (exit 0 -> Railway qayta yoqmaydi);
  - ertalab 8:00 da Railway cron (`0 3 * * *` UTC) uni qayta yoqadi;
  - ish vaqtidan tashqari qo'lda ishga tushirilsa — darhol chiqib ketadi.
Kechasi yozilgan xabarlar yo'qolmaydi: Telegram ularni 24 soatgacha saqlaydi,
bot ertalab yonganda hammasini oladi.

`WORK_HOURS` bo'sh bo'lsa — bot oddiygidek 24/7 ishlaydi (hech narsa o'zgarmaydi).
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
log = logging.getLogger("ish_vaqti")

# Cron biroz kechikib yoki erta yoqsa ham ishlashi uchun boshlanishga 10 daqiqa zaxira
_START_GRACE = timedelta(minutes=10)


def _parse():
    raw = (os.getenv("WORK_HOURS") or "").strip()
    if not raw:
        return None
    try:
        a, b = raw.split("-")
        start, end = int(a), int(b)
        if 0 <= start < end <= 24:
            return start, end
    except ValueError:
        pass
    log.warning("WORK_HOURS noto'g'ri: %r — e'tiborsiz qoldirildi (24/7 ishlaydi)", raw)
    return None


def _window(now):
    hours = _parse()
    if not hours:
        return None
    start_h, end_h = hours
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day + timedelta(hours=start_h), day + timedelta(hours=end_h)


def ish_vaqtimi() -> bool:
    """Hozir ishlash kerakmi? WORK_HOURS yo'q bo'lsa doim True."""
    now = datetime.now(TZ)
    w = _window(now)
    if not w:
        return True
    start, end = w
    return start - _START_GRACE <= now < end


async def tugash_kutuvchi(stop_coro_factory):
    """Ish vaqti tugaguncha kutadi, keyin polling'ni to'xtatadi."""
    now = datetime.now(TZ)
    w = _window(now)
    if not w:
        return
    _, end = w
    wait = (end - now).total_seconds()
    log.info("Ish vaqti: bot %s da to'xtaydi (%.0f daqiqadan keyin)",
             end.strftime("%H:%M"), wait / 60)
    await asyncio.sleep(max(wait, 0))
    log.info("Ish vaqti tugadi — bot to'xtatilmoqda (ertalab cron qayta yoqadi)")
    await stop_coro_factory()

# -*- coding: utf-8 -*-
"""
count_sync.py — BOTDAGI SANOQ O'ZGARSA, SAYT VA GURUH HAM O'ZGARADI
==================================================================
"✏️ Tuzatish" orqali sanoq o'chirilsa yoki soni tuzatilsa, avval faqat botning
ichki bazasi o'zgarardi — saytda va guruhda eski holat qolib ketardi.

  find_site_session(...)  — bot sanog'iga mos saytdagi sanoqni topadi
                            (klent nomi + sana + tovar/son to'plami)
  delete_site_session(...) — saytdan o'chiradi
  update_site_qty(...)     — saytda bitta tovar sonini tuzatadi
  delete_group_report(...) / note_group_report(...) — guruhdagi rasm
"""
import asyncio
import logging

import group_notify as gn
import site_analysis as sa
import sklad_sync
from sklad_sync import _http_get_blob, _norm

log = logging.getLogger("count_sync")


def _site_client_id(blob, client_name):
    for c in blob.get("clients", []):
        if isinstance(c, dict) and _norm(c.get("name")) == _norm(client_name):
            return c.get("id")
    return None


def _groups(blob, site_cid, date_str):
    """Saytdagi shu klent+sana sanoqlari, vaqt bo'yicha guruhlangan."""
    _, products = sa.maps(blob)
    out = {}
    for c in blob.get("counts", []):
        if (isinstance(c, dict) and sa._same(c.get("clientId"), site_cid)
                and str(c.get("date") or "") == date_str):
            g = out.setdefault(str(c.get("time") or ""), {"items": set(), "agentId": None})
            g["items"].add((_norm(products.get(str(c.get("productId")), {}).get("name", "?")),
                            round(sa._num(c.get("qty")), 3)))
            if c.get("agentId") is not None:
                g["agentId"] = c.get("agentId")
    return out


def find_site_session_in(blob, client_name, date_str, items, agent_id=None):
    """items: [(tovar_nomi, son), ...] (botdagi). Qaytaradi (site_cid, vaqt) yoki None."""
    site_cid = _site_client_id(blob, client_name)
    if site_cid is None:
        return None
    groups = _groups(blob, site_cid, date_str)
    want = {(_norm(n), round(float(q), 3)) for n, q in items}
    exact = [t for t, g in groups.items() if g["items"] == want]
    if exact:
        return site_cid, max(exact)
    # aniq mos kelmasa — o'sha agentning o'sha kundagi YAGONA sanog'i
    if agent_id is not None:
        mine = [t for t, g in groups.items() if sa._same(g["agentId"], agent_id)]
        if len(mine) == 1:
            return site_cid, mine[0]
    return None


async def find_site_session(client_name, date_str, items, agent_id=None):
    blob = (await asyncio.to_thread(_http_get_blob))[1]
    return find_site_session_in(blob, client_name, date_str, items, agent_id)


async def delete_site_session(site_cid, date_str, time_str):
    def mut(blob):
        before = len(blob.get("counts", []))
        blob["counts"] = [c for c in blob.get("counts", []) if not (
            isinstance(c, dict) and sa._same(c.get("clientId"), site_cid)
            and str(c.get("date") or "") == date_str and str(c.get("time") or "") == time_str)]
        n = before - len(blob["counts"])
        return n or None
    return await sklad_sync.update_blob(mut) or 0


async def update_site_qty(site_cid, date_str, time_str, product_name, new_qty):
    def mut(blob):
        _, products = sa.maps(blob)
        n = 0
        for c in blob.get("counts", []):
            if (isinstance(c, dict) and sa._same(c.get("clientId"), site_cid)
                    and str(c.get("date") or "") == date_str
                    and str(c.get("time") or "") == time_str
                    and _norm(products.get(str(c.get("productId")), {}).get("name"))
                    == _norm(product_name)):
                c["qty"] = new_qty
                n += 1
        return n or None
    return await sklad_sync.update_blob(mut) or 0


async def delete_group_report(bot, site_cid, date_str, time_str):
    """Guruhdagi hisobot rasmini o'chiradi. Qaytaradi: holat matni."""
    ref = await gn.recall_message(site_cid, date_str, time_str)
    if not ref:
        return "—"
    chat_id, msg_id = ref
    try:
        await bot.delete_message(chat_id, msg_id)
        res = "rasm o'chirildi"
    except Exception:
        try:
            await bot.send_message(
                chat_id, f"❌ Bu sanoq ({sa.ddmm(date_str)} {time_str}) o'chirildi.",
                reply_to_message_id=msg_id)
            res = "o'chirildi deb belgilandi (48 soatdan eski)"
        except Exception:
            res = "topilmadi"
    await gn.set_setting(gn._msg_key(site_cid, date_str, time_str), "")
    return res


async def note_group_report(bot, site_cid, date_str, time_str, text):
    """Guruhdagi hisobotga javob qilib izoh yozadi (masalan tuzatish)."""
    ref = await gn.recall_message(site_cid, date_str, time_str)
    if not ref:
        return False
    try:
        await bot.send_message(ref[0], text, reply_to_message_id=ref[1])
        return True
    except Exception:
        log.exception("guruhga tuzatish izohi yuborilmadi")
        return False

# -*- coding: utf-8 -*-
"""
agent_topics.py — AGENT QO'SHILSA, O'Z TOPICIGA AVTOMATIK ULANADI
================================================================
1) Bot guruhdagi topic nomlarini o'zi o'rganadi (topic ochilganda, nomi
   o'zgarganda yoki topicga biror xabar yozilganda) -> sozlama `topics_known`.
2) Admin "➕ Agent qo'shish" orqali agent qo'shsa, agent ismi topic nomiga
   solishtiriladi: "Abduqodir ..." -> "Abduqodir sanoq". Bitta aniq mos
   kelsa — topic:<agentId> avtomatik yoziladi (/topic kerak emas).
3) seed() — bir martalik boshlang'ich sozlash (ma'lum agentlar va topiclar).
"""
import json
import logging

from aiogram import BaseMiddleware

import database as db
import group_notify as gn
from sklad_sync import _norm

log = logging.getLogger("agent_topics")

GROUP_CHAT_ID = -1003913010631
KNOWN_TOPICS = {"Abduqodir sanoq": 2, "Muhammadamin sanoq": 4}
# (telegram_id, ism, topic_id) — bir marta qo'shiladi (seed_v1)
SEED_AGENTS = [
    (8317612695, "Abduqodir", 2),
    (8317562764, "Muhammadamin", 4),
]
OWNER_TEST_ID = 5774173398   # Muhammadali — sinov sanoqlari Generalga
SKIP_WORDS = {"aka", "opa", "sanoq", "agent", "hisobot", "general"}


async def known_topics() -> dict:
    try:
        d = json.loads(await gn.get_setting("topics_known") or "{}")
    except Exception:
        d = {}
    return {**KNOWN_TOPICS, **d}


async def learn_topic(chat_id, name, thread_id):
    if not name or not thread_id:
        return
    group = await gn.get_group_chat()
    if group and chat_id != group:
        return
    cur = await known_topics()
    if cur.get(name) == thread_id:
        return
    try:
        stored = json.loads(await gn.get_setting("topics_known") or "{}")
    except Exception:
        stored = {}
    stored = {k: v for k, v in stored.items() if v != thread_id}
    stored[name] = thread_id
    await gn.set_setting("topics_known", json.dumps(stored, ensure_ascii=False))
    log.info("Topic o'rganildi: %s -> %s", name, thread_id)


def _words(s):
    return [w for w in _norm(s).replace("'", "").split() if len(w) >= 4 and w not in SKIP_WORDS]


def match_topic(full_name, topics: dict):
    """Agent ismiga mos YAGONA topicni qaytaradi: (nom, thread_id) yoki None."""
    nw = _words(full_name)
    hits = []
    for tname, tid in topics.items():
        tw = _words(tname)
        if any(a == b or (len(a) >= 5 and len(b) >= 5 and (a in b or b in a))
               for a in nw for b in tw):
            hits.append((tname, tid))
    return hits[0] if len(hits) == 1 else None


async def auto_assign(user_id, full_name):
    """Agent qo'shilganda chaqiriladi. Qaytaradi: topic nomi yoki None."""
    if (await gn.get_topic_map()).get(int(user_id)):
        return None  # allaqachon ulangan
    m = match_topic(full_name, await known_topics())
    if not m:
        return None
    await gn.set_setting(f"topic:{int(user_id)}", m[1])
    if not await gn.get_group_chat():
        await gn.set_setting("group_chat_id", GROUP_CHAT_ID)
    return m[0]


async def seed():
    """Bir martalik: ma'lum agentlarni qo'shadi va topiclariga ulaydi."""
    if await gn.get_setting("seed_v1_done"):
        return
    if not await gn.get_group_chat():
        await gn.set_setting("group_chat_id", GROUP_CHAT_ID)
    for uid, name, tid in SEED_AGENTS:
        u = await db.get_user(uid)
        if not u:
            await db.add_user(uid, name, "agent", added_by=None)
            log.info("Agent qo'shildi (seed): %s %s", uid, name)
        await gn.set_setting(f"topic:{uid}", tid)
    # sinov uchun vaqtincha Abduqodir topiciga ulangan edi -> General
    tm = await gn.get_topic_map()
    if tm.get(OWNER_TEST_ID) in {t for _, _, t in SEED_AGENTS}:
        await gn.set_setting(f"topic:{OWNER_TEST_ID}", 0)
    await gn.set_setting("seed_v1_done", "1")


class TopicLearner(BaseMiddleware):
    """Guruhdagi har bir xabardan topic nomini o'rganadi (xabarni to'xtatmaydi)."""

    async def __call__(self, handler, event, data):
        try:
            chat = getattr(event, "chat", None)
            if chat is not None and getattr(chat, "is_forum", False):
                tid = event.message_thread_id
                name = None
                if event.forum_topic_created:
                    name = event.forum_topic_created.name
                elif event.forum_topic_edited and event.forum_topic_edited.name:
                    name = event.forum_topic_edited.name
                elif (event.reply_to_message is not None
                      and event.reply_to_message.forum_topic_created):
                    name = event.reply_to_message.forum_topic_created.name
                if name and tid:
                    await learn_topic(chat.id, name, tid)
        except Exception:
            log.exception("topic o'rganishda xato")
        return await handler(event, data)

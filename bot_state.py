# -*- coding: utf-8 -*-
"""
bot_state.py — BOT XOTIRASINI SUPABASE'DA SAQLASH (Railway qayta ishga tushsa ham o'chmaydi)
=========================================================================================
Muammo: Railway'da Volume bo'lmasa, har deploy'da sklad.db (SQLite) boshidan
boshlanadi -> xodimlar (agentlar) va guruh/topic sozlamalari o'chib ketadi.

Yechim: shu ma'lumotlar Supabase'dagi `cp_sklad` jadvalining ALOHIDA qatorida
(id = 'bot_state') ham saqlanadi. Sayt faqat id='main' qatorini ishlatadi —
bu qatorga tegmaydi. Agar alohida qator yaratib bo'lmasa (ruxsat yo'q),
zaxira sifatida asosiy blok ichida `_botState` kalitida saqlanadi.

  restore()          — bot ishga tushganda: Supabase -> SQLite
  user_saved(...)    — xodim qo'shilganda/o'zgarganda
  user_deleted(uid)  — xodim o'chirilganda
  setting_saved(k,v) — guruh/topic va boshqa sozlamalar

Barcha yozuvlar fonda; xato bo'lsa bot to'xtamaydi (faqat log).
"""
import json
import asyncio
import logging
import datetime as dt
import urllib.request
import urllib.error

import aiosqlite

from config import DB_PATH
import sklad_sync

log = logging.getLogger("bot_state")
ROW_ID = "bot_state"
FALLBACK_KEY = "_botState"
_TIMEOUT = 20

_lock = asyncio.Lock()
_mode = {"row": True}      # False -> asosiy blok ichida saqlaymiz
_bg = set()


# ---------------------------------------------------------------------------
# HTTP (bloklovchi — to_thread orqali)
# ---------------------------------------------------------------------------
def _hdr(extra=None):
    h = {"apikey": sklad_sync.ANON_KEY, "Authorization": f"Bearer {sklad_sync.ANON_KEY}"}
    if extra:
        h.update(extra)
    return h


def _row_get():
    url = f"{sklad_sync.SUPABASE_URL}/rest/v1/{sklad_sync.TABLE}?id=eq.{ROW_ID}&select=data"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_hdr()), timeout=_TIMEOUT) as r:
        rows = json.loads(r.read().decode())
    if not rows:
        return None
    d = rows[0].get("data")
    if isinstance(d, str):
        d = json.loads(d)
    return d if isinstance(d, dict) else None


def _row_put(state):
    url = f"{sklad_sync.SUPABASE_URL}/rest/v1/{sklad_sync.TABLE}"
    body = json.dumps([{"id": ROW_ID, "data": state,
                        "updated_at": dt.datetime.utcnow().isoformat() + "Z"}],
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=_hdr({
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"}))
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.status


def _load_blocking():
    if _mode["row"]:
        try:
            st = _row_get()
            if st is not None:
                return st
            # alohida qator hali yo'q — balki avval asosiy blokda saqlangan
            blob = sklad_sync._http_get_blob()[1]
            old = blob.get(FALLBACK_KEY)
            return old if isinstance(old, dict) else {}
        except urllib.error.HTTPError as ex:
            log.warning("bot_state qatorini o'qib bo'lmadi (HTTP %s) — asosiy blokdan o'qiladi", ex.code)
            _mode["row"] = False
    blob = sklad_sync._http_get_blob()[1]
    st = blob.get(FALLBACK_KEY)
    return st if isinstance(st, dict) else {}


def _modify_blocking(fn):
    """Eng yangi holatni o'qib, fn(state) bilan o'zgartirib, qaytarib yozadi."""
    if _mode["row"]:
        try:
            st = _row_get() or {}
            fn(st)
            _row_put(st)
            return
        except urllib.error.HTTPError as ex:
            log.warning("bot_state qatoriga yozib bo'lmadi (HTTP %s) — asosiy blokka yoziladi", ex.code)
            _mode["row"] = False
    def mut(blob):
        st = blob.get(FALLBACK_KEY)
        if not isinstance(st, dict):
            st = {}
        fn(st)
        blob[FALLBACK_KEY] = st
        return True
    sklad_sync.update_blob_blocking(mut)


def _prune(settings):
    """Guruhdagi xabar id'lari (msg:...) 3 kundan eskisini tozalaydi."""
    limit = (dt.datetime.utcnow() + dt.timedelta(hours=5) - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    for k in list(settings):
        if k.startswith("msg:"):
            try:
                d = k.split("|")[1]
            except IndexError:
                continue
            if d < limit or not settings[k]:
                settings.pop(k, None)


# ---------------------------------------------------------------------------
# Async API
# ---------------------------------------------------------------------------
async def _apply(fn):
    async with _lock:
        try:
            await asyncio.to_thread(_modify_blocking, fn)
        except Exception:
            log.exception("bot_state Supabase'ga yozilmadi (bot davom etadi)")


def _bg_run(coro):
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def user_saved(user: dict):
    u = {k: user.get(k) for k in ("id", "full_name", "role", "added_by", "created_at")}

    def fn(st):
        st.setdefault("users", {})[str(u["id"])] = u
    _bg_run(_apply(fn))


def user_deleted(user_id):
    def fn(st):
        st.setdefault("users", {}).pop(str(user_id), None)
    _bg_run(_apply(fn))


def setting_saved(key, value):
    def fn(st):
        s = st.setdefault("settings", {})
        s[key] = value
        _prune(s)
    _bg_run(_apply(fn))


async def restore():
    """Bot ishga tushganda: Supabase'dagi xodimlar va sozlamalarni SQLite'ga qaytaradi.
    Supabase bo'sh bo'lsa — hozirgi lokal holatni u yerga yuklaydi (birinchi marta)."""
    try:
        state = await asyncio.to_thread(_load_blocking)
    except Exception:
        log.exception("bot_state o'qilmadi — lokal baza bilan davom etiladi")
        return

    users = state.get("users") or {}
    settings = state.get("settings") or {}
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)")
        for u in users.values():
            try:
                await conn.execute(
                    "INSERT OR REPLACE INTO users (id, full_name, role, added_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (int(u["id"]), u.get("full_name") or "—", u.get("role") or "agent",
                     u.get("added_by"), u.get("created_at") or ""))
            except Exception:
                log.warning("xodim tiklanmadi: %s", u)
        for k, v in settings.items():
            await conn.execute(
                "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
        await conn.commit()

        # Supabase'da yo'q, lekin lokal bazada bor narsalarni ham yuklab qo'yamiz
        cur = await conn.execute("SELECT * FROM users")
        local_users = {str(r["id"]): dict(r) for r in await cur.fetchall()}
        cur = await conn.execute("SELECT key, value FROM bot_settings")
        local_settings = {r[0]: r[1] for r in await cur.fetchall()}

    missing_u = {k: v for k, v in local_users.items() if k not in users}
    missing_s = {k: v for k, v in local_settings.items() if k not in settings}
    if missing_u or missing_s:
        def fn(st):
            st.setdefault("users", {}).update(missing_u)
            s = st.setdefault("settings", {})
            for k, v in missing_s.items():
                s.setdefault(k, v)
            _prune(s)
        await _apply(fn)
    log.info("bot_state tiklandi: %s xodim, %s sozlama (rejim: %s)",
             len(users), len(settings), "alohida qator" if _mode["row"] else "asosiy blok")

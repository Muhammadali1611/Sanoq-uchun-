"""
Ma'lumotlar bazasi (SQLite + aiosqlite).
Barcha jadvallar va so'rovlar shu yerda.
"""
import datetime as dt

import aiosqlite

from config import DB_PATH, ADMIN_IDS

# ---------------------------------------------------------------------------
# Jadvallar
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,          -- Telegram user_id
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL,                -- admin | manager | agent
    added_by    INTEGER,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    region      TEXT,
    phone       TEXT,
    address     TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'dona',
    price       REAL NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

-- Har bir sanash sessiyasi (agent klentga borib sanaganda 1 ta yoziladi)
CREATE TABLE IF NOT EXISTS counts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL,
    agent_id    INTEGER NOT NULL,
    count_date  TEXT NOT NULL,                -- YYYY-MM-DD
    created_at  TEXT NOT NULL,               -- to'liq vaqt
    note        TEXT,
    FOREIGN KEY (client_id) REFERENCES clients(id),
    FOREIGN KEY (agent_id)  REFERENCES users(id)
);

-- Sessiyadagi har bir tovar qoldig'i
CREATE TABLE IF NOT EXISTS count_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    count_id    INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    quantity    REAL NOT NULL,               -- qoldiq (sanab chiqilgan soni)
    FOREIGN KEY (count_id)   REFERENCES counts(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    # .env dagi adminlarni avtomatik ro'yxatga olish
    for admin_id in ADMIN_IDS:
        existing = await get_user(admin_id)
        if not existing:
            await add_user(admin_id, "Admin", "admin", added_by=None)


def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Foydalanuvchilar
# ---------------------------------------------------------------------------
async def add_user(user_id: int, full_name: str, role: str, added_by=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (id, full_name, role, added_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, full_name, role, added_by, _now()),
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_users_by_role(role: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY full_name", (role,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_all_admins():
    return await get_users_by_role("admin")


async def delete_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Klentlar
# ---------------------------------------------------------------------------
async def add_client(name: str, region: str = None, phone: str = None, address: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO clients (name, region, phone, address, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, region, phone, address, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_clients(active_only: bool = True):
    q = "SELECT * FROM clients"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY region, name"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def get_regions():
    """Mavjud regionlar ro'yxati (klentlar soni bilan)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT COALESCE(region, 'Boshqa') AS region, COUNT(*) AS cnt "
            "FROM clients WHERE active = 1 GROUP BY region ORDER BY region"
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_clients_by_region(region: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM clients WHERE active = 1 AND COALESCE(region,'Boshqa') = ? ORDER BY name",
            (region,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def search_clients(query: str, limit: int = 30):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM clients WHERE active = 1 AND name LIKE ? ORDER BY name LIMIT ?",
            (f"%{query}%", limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_client(client_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_client(client_id: int):
    """Yumshoq o'chirish (tarix saqlanadi)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clients SET active = 0 WHERE id = ?", (client_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Tovarlar
# ---------------------------------------------------------------------------
async def add_product(name: str, unit: str, price: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO products (name, unit, price, created_at) VALUES (?, ?, ?, ?)",
            (name, unit, price, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_products(active_only: bool = True):
    q = "SELECT * FROM products"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY name"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def get_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
        await db.commit()


# ---------------------------------------------------------------------------
# Sanash (counts)
# ---------------------------------------------------------------------------
async def create_count(client_id: int, agent_id: int, count_date: str, note: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO counts (client_id, agent_id, count_date, created_at, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (client_id, agent_id, count_date, _now(), note),
        )
        await db.commit()
        return cur.lastrowid


async def add_count_item(count_id: int, product_id: int, quantity: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO count_items (count_id, product_id, quantity) VALUES (?, ?, ?)",
            (count_id, product_id, quantity),
        )
        await db.commit()


async def _get_counts_by_date_sqlite(date_str: str):
    """Berilgan sanadagi barcha sanash qatorlari (tovar darajasida). [ESKI/zaxira]"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT c.id AS count_id, c.count_date, c.created_at,
                   cl.name AS client_name,
                   u.full_name AS agent_name,
                   p.name AS product_name, p.unit AS unit, p.price AS price,
                   ci.quantity AS quantity
            FROM counts c
            JOIN clients cl ON cl.id = c.client_id
            JOIN users   u  ON u.id = c.agent_id
            JOIN count_items ci ON ci.count_id = c.id
            JOIN products p ON p.id = ci.product_id
            WHERE c.count_date = ?
            ORDER BY u.full_name, cl.name, p.name
            """,
            (date_str,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def _get_counts_in_period_sqlite(start_date: str, end_date: str):
    """[start, end] oralig'idagi barcha sanash qatorlari. [ESKI/zaxira]"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT c.id AS count_id, c.client_id, c.count_date, c.created_at,
                   cl.name AS client_name,
                   u.full_name AS agent_name,
                   p.id AS product_id, p.name AS product_name,
                   p.unit AS unit, p.price AS price,
                   ci.quantity AS quantity
            FROM counts c
            JOIN clients cl ON cl.id = c.client_id
            JOIN users   u  ON u.id = c.agent_id
            JOIN count_items ci ON ci.count_id = c.id
            JOIN products p ON p.id = ci.product_id
            WHERE c.count_date BETWEEN ? AND ?
            ORDER BY cl.name, p.name, c.count_date, c.created_at
            """,
            (start_date, end_date),
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# YO'L B: hisobot tarixini SAYTDAN o'qish (asosiy manba).
# Sayt yiqilsa yoki tarmoq yo'q bo'lsa -> avtomatik SQLite zaxiraga tushadi
# (bot yiqilmaydi). Odatda esa to'liq tarix (1488+) saytdan keladi.
# ---------------------------------------------------------------------------
async def get_counts_by_date(date_str: str):
    try:
        from sklad_read import counts_by_date_from_site
        return await counts_by_date_from_site(date_str)
    except Exception as e:
        import logging
        logging.getLogger("database").warning(
            "get_counts_by_date: sayt o'qishda xato (%s) -> SQLite zaxira", e)
        return await _get_counts_by_date_sqlite(date_str)


async def get_counts_in_period(start_date: str, end_date: str):
    try:
        from sklad_read import counts_in_period_from_site
        return await counts_in_period_from_site(start_date, end_date)
    except Exception as e:
        import logging
        logging.getLogger("database").warning(
            "get_counts_in_period: sayt o'qishda xato (%s) -> SQLite zaxira", e)
        return await _get_counts_in_period_sqlite(start_date, end_date)


async def get_last_session_for_client(client_id: int, before_date: str = None):
    """Klentning eng oxirgi sanash sessiyasi (ixtiyoriy: berilgan sanadan oldin)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if before_date:
            cur = await db.execute(
                "SELECT * FROM counts WHERE client_id = ? AND count_date < ? "
                "ORDER BY count_date DESC, created_at DESC LIMIT 1",
                (client_id, before_date),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM counts WHERE client_id = ? "
                "ORDER BY count_date DESC, created_at DESC LIMIT 1",
                (client_id,),
            )
        row = await cur.fetchone()
        if not row:
            return None
        session = dict(row)
        cur2 = await db.execute(
            "SELECT product_id, quantity FROM count_items WHERE count_id = ?",
            (session["id"],),
        )
        session["items"] = {r["product_id"]: r["quantity"] for r in await cur2.fetchall()}
        return session


# ---------------------------------------------------------------------------
# Sanashni tuzatish / o'chirish
# ---------------------------------------------------------------------------
async def get_client_recent_counts(client_id: int, limit: int = 5):
    """Klentning oxirgi N ta sanash sessiyasi (tovarlar bilan)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.*, u.full_name AS agent_name FROM counts c "
            "JOIN users u ON u.id = c.agent_id "
            "WHERE c.client_id = ? ORDER BY c.count_date DESC, c.created_at DESC LIMIT ?",
            (client_id, limit),
        )
        sessions = [dict(r) for r in await cur.fetchall()]
        for s in sessions:
            cur2 = await db.execute(
                "SELECT ci.product_id, ci.quantity, p.name AS product_name, p.unit, p.price "
                "FROM count_items ci JOIN products p ON p.id = ci.product_id "
                "WHERE ci.count_id = ? ORDER BY p.name",
                (s["id"],),
            )
            s["items"] = [dict(r) for r in await cur2.fetchall()]
        return sessions


async def delete_count(count_id: int):
    """Sanash sessiyasini butunlay o'chirish."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM count_items WHERE count_id = ?", (count_id,))
        await db.execute("DELETE FROM counts WHERE id = ?", (count_id,))
        await db.commit()


async def update_count_item(count_id: int, product_id: int, new_qty: float):
    """Sanashdagi tovar miqdorini tuzatish."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE count_items SET quantity = ? WHERE count_id = ? AND product_id = ?",
            (new_qty, count_id, product_id),
        )
        await db.commit()


async def get_count_by_id(count_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT c.*, cl.name AS client_name, u.full_name AS agent_name "
            "FROM counts c JOIN clients cl ON cl.id = c.client_id "
            "JOIN users u ON u.id = c.agent_id WHERE c.id = ?",
            (count_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

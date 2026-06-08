"""Namuna ma'lumot bilan Excel hisobotlarni sinash."""
import asyncio
import os

import database as db
db.DB_PATH = "/tmp/demo_sklad.db"  # demo uchun alohida baza
import analytics
import excel_report as xls

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)


async def seed():
    await db.init_db()
    # Agent
    await db.add_user(1001, "Qodirjon", "agent")
    # Tovarlar
    shp = await db.add_product("Shpaklovka", "dona", 34500)
    gips = await db.add_product("Gips", "qop", 28000)
    kley = await db.add_product("Kley", "qop", 45000)
    # Klentlar
    c1 = await db.add_client("Qurilish Baza", "+998901112233")
    c2 = await db.add_client("Stroy Market", "+998935556677")
    c3 = await db.add_client("Dom Servis")

    async def cnt(cid, date, items):
        cnt_id = await db.create_count(cid, 1001, date)
        for pid, q in items:
            await db.add_count_item(cnt_id, pid, q)

    # Qurilish Baza — tez sotyapti
    await cnt(c1, "2026-05-01", [(shp, 135), (gips, 50)])
    await cnt(c1, "2026-05-10", [(shp, 100), (gips, 48)])
    await cnt(c1, "2026-05-20", [(shp, 60), (gips, 45)])
    await cnt(c1, "2026-05-30", [(shp, 30), (gips, 44)])
    # Stroy Market — qotib qolgan (o'zgarmagan)
    await cnt(c2, "2026-05-05", [(shp, 50), (kley, 20)])
    await cnt(c2, "2026-05-25", [(shp, 50), (kley, 20)])
    # Dom Servis — yangi yuk olgan (ko'paygan)
    await cnt(c3, "2026-05-08", [(kley, 10)])
    await cnt(c3, "2026-05-22", [(kley, 40)])


async def main():
    await seed()
    os.makedirs("/mnt/user-data/outputs", exist_ok=True)

    # Oylik
    rows = await db.get_counts_in_period("2026-05-01", "2026-05-31")
    analysis = analytics.analyze_period(rows)
    data = xls.build_monthly_report("May 2026", rows, analysis)
    with open("/mnt/user-data/outputs/NAMUNA_oylik_2026_05.xlsx", "wb") as f:
        f.write(data)

    # Kunlik
    drows = await db.get_counts_by_date("2026-05-30")
    ddata = xls.build_daily_report("2026-05-30", drows)
    with open("/mnt/user-data/outputs/NAMUNA_kunlik_2026_05_30.xlsx", "wb") as f:
        f.write(ddata)

    print("OK. Klentlar tahlili:")
    for cid, a in analysis.items():
        print(f"  {a['client_name']}: holat={a['status']}, "
              f"sotilgan={a['sold_units']:g}, yangi_yuk={a['delivered_units']:g}, "
              f"qoplama_kun={a['cover_days']}")


asyncio.run(main())

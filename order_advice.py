# -*- coding: utf-8 -*-
"""
order_advice.py — AQLLI BUYURTMA TAKLIFI + XULOSALAR (AI'siz, aniq formula)
==========================================================================
Har bir tovar uchun:
  tezlik   = oxirgi ~60 kundagi sotuv / kun (bitta oraliqqa emas — barqarorroq)
  maqsad   = max(MIN_STOCK, tezlik * TARGET_DAYS)
  taklif   = maqsad - bugungi qoldiq  -> 10 ga yuqoriga yaxlitlanadi
  turib qolgan (21+ kun sotilmagan) tovarga taklif berilmaydi.

Logistika: Qo'qon va yaqin joylarga zakaz kamida 1 t, uzoqroq joylarga 2 t.
  Taklif minimumdan kam chiqsa -> eng tez sotilayotgan tovarlardan qo'shib minimumga
  yetkaziladi (eng kam kunga yetadiganiga birinchi). Hech narsa kerak bo'lmasa —
  "keyingi zakaz taxminan N kundan keyin" deb aytadi.

Xulosalar: eng tez / eng sekin tovar, sotuv tezlashdimi-sekinlashdimi,
keyingi tashrif sanasi.
"""
import math
import os
import re
import datetime as dt

import site_analysis as sa
import product_order as po

TARGET_DAYS = int(os.getenv("ORDER_TARGET_DAYS", "21") or 21)
MIN_STOCK = sa.LOW_STOCK                      # 30 qop
ROUND_TO = int(os.getenv("ORDER_ROUND", "10") or 10)
MIN_ORDER_KG = int(os.getenv("MIN_ORDER_KG", "1000") or 1000)          # Qo'qon va yaqin joylar
MIN_ORDER_KG_FAR = int(os.getenv("MIN_ORDER_KG_FAR", "2000") or 2000)  # uzoqroq joylar
# Yaqin hududlar (1 t). Ro'yxatda yo'q hudud — uzoq (2 t). ENV NEAR_REGIONS bilan o'zgartirsa bo'ladi.
NEAR_REGIONS = os.getenv("NEAR_REGIONS", "Qo'qon,Goriskiy,Dang'ara,Uchko'prik,Bog'dod,Rishton,"
                         "Beshariq,Oqjar,Bachqir,Yaypan,Buvayda,Rapqon")


def _rnorm(s):
    s = (s or "").lower().strip()
    for ch in "'`ʻʼ’‘":
        s = s.replace(ch, "")
    return s.replace(" ", "")


_NEAR = {_rnorm(x) for x in NEAR_REGIONS.split(",") if x.strip()}


def min_order_kg(region):
    """Hudud bo'yicha zakaz minimumi: yaqin — 1 t, uzoq — 2 t. Hudud noma'lum — 1 t."""
    r = _rnorm(region)
    if not r or r in ("—", "-"):
        return MIN_ORDER_KG
    return MIN_ORDER_KG if r in _NEAR else MIN_ORDER_KG_FAR
RATE_WINDOW = 60                              # kun
REORDER_COVER = 7                             # shuncha kunga qolganda zakaz vaqti

_KG = re.compile(r"(\d{1,2})\s?kg", re.I)


def bag_kg(name: str):
    """Qop og'irligi. Nomida yozilgan bo'lsa — o'sha; aks holda: shpaklovka (01) 20 kg,
    qolganlari 25 kg. Qaytaradi (kg, taxminmi)."""
    m = _KG.search(name or "")
    if m:
        return int(m.group(1)), False
    n = (name or "").lower()
    if "shpak" in n or re.match(r"\s*\S+\s+0?1\b", n):
        return 20, True
    return 25, True


def _round_up(x):
    return int(math.ceil(x / ROUND_TO) * ROUND_TO) if x > 0 else 0


def rate_60(blob, cid, pid, today_str, fallback=None):
    """Oxirgi ~60 kundagi o'rtacha kunlik sotuv (shubhali oraliqlar hisobga olinmaydi)."""
    a = sa.analyze_client_product(blob, cid, pid, today_str=today_str)
    lim = (dt.date.fromisoformat(today_str) - dt.timedelta(days=RATE_WINDOW)).isoformat()
    sold = days = 0.0
    for iv in a["intervals"]:
        if not iv["hasPrev"] or iv["to"] < lim or iv["days"] <= 0 or iv["rawSold"] < -0.001:
            continue
        sold += max(iv["rawSold"], 0.0)
        days += iv["days"]
    if days >= 5:
        return sold / days
    return fallback


def advise(blob, cid, rows, today_str, region=None):
    """rows — report_image.build_report() qatorlari. Qaytaradi: taklif lug'ati."""
    items = []
    for r in rows:
        kg, guessed = bag_kg(r["full_name"])
        rate = rate_60(blob, cid, r["pid"], today_str, fallback=r["daily"])
        stuck = r["is_stuck"] or (r["days_idle"] is not None and r["days_idle"] >= sa.STUCK_DAYS
                                  and r["today"] > 0)
        bought = any(sa._same(x.get("clientId"), cid) and sa._same(x.get("productId"), r["pid"])
                     and sa._num(x.get("qty")) > 0 for x in blob.get("sales", []))
        if not bought:
            base, reason = 0, "avval olmagan"   # faqat oladigan tovarlarini taklif qilamiz
        elif stuck:
            base, reason = 0, "turib qolgan"
        else:
            target = max(MIN_STOCK, (rate or 0) * TARGET_DAYS)
            base = _round_up(target - r["today"])
            reason = "kam qoldi" if r["today"] < MIN_STOCK else ("tez ketyapti" if base else "")
        items.append({"name": r["name"], "full_name": r["full_name"], "pid": r["pid"],
                      "price": r["price"], "today": r["today"], "rate": rate, "kg": kg,
                      "kg_guess": guessed, "stuck": stuck or not bought, "bought": bought, "base": base, "qty": base,
                      "extra": 0, "reason": reason})

    min_kg = min_order_kg(region)

    def total_kg():
        return sum(i["qty"] * i["kg"] for i in items)

    topped = 0
    if 0 < total_kg() < min_kg:
        # 1 t ga yetkazish: eng tez sotiladiganlardan, eng kam kunga yetadiganiga birinchi
        cand = [i for i in items if not i["stuck"] and (i["rate"] or 0) > 0]
        if not cand:
            cand = [i for i in items if not i["stuck"] and i["qty"] > 0]
        guard = 0
        while total_kg() < min_kg and cand and guard < 200:
            guard += 1
            pick = min(cand, key=lambda i: (i["today"] + i["qty"]) / (i["rate"] or 0.01))
            pick["qty"] += ROUND_TO
            pick["extra"] += ROUND_TO
            topped += ROUND_TO

    order = [i for i in items if i["qty"] > 0]
    tot_bags = sum(i["qty"] for i in order)
    tot_kg = total_kg()
    tot_sum = sum(i["qty"] * i["price"] for i in order)

    # Zakaz kerak bo'lmasa — qachon kerak bo'ladi?
    next_days = None
    if not order:
        ds = []
        for i in items:
            if i["stuck"] or not i["rate"]:
                continue
            trigger = max(MIN_STOCK, i["rate"] * REORDER_COVER)
            ds.append(max((i["today"] - trigger) / i["rate"], 0))
        next_days = round(min(ds)) if ds else None

    return {"items": items, "order": order, "bags": tot_bags, "kg": tot_kg, "sum": tot_sum,
            "topped": topped, "min_kg": min_kg, "far": min_kg > MIN_ORDER_KG, "target_days": TARGET_DAYS,
            "next_days": next_days, "kg_guess": any(i["kg_guess"] for i in order)}


def insights(rep, adv, today_str):
    """Qisqa aqlli xulosalar (3-4 ta)."""
    out = []
    movers = [i for i in adv["items"] if (i["rate"] or 0) > 0]
    if movers:
        f = max(movers, key=lambda i: i["rate"])
        out.append(("green", f"Eng tez sotilayotgani — {f['name']}: kuniga ~{_n(f['rate'])} qop."))
    slow = [r for r in rep["rows"] if r["cover"] is not None and r["cover"] >= sa.SLOW_COVER
            and r["today"] >= MIN_STOCK]
    if slow:
        s = max(slow, key=lambda r: r["cover"])
        out.append(("orange", f"{s['name']} sekin: {_n(s['today'])} qop ~{round(s['cover'])} kunga "
                    f"yetadi — hozircha qo'shimcha taklif qilmang."))
    # tezlik o'zgarishi: shu davr vs 60 kunlik
    if rep["sum_daily"]:
        r60 = sum((i["rate"] or 0) for i in adv["items"])
        if r60 > 0:
            ch = (rep["sum_daily"] - r60) / r60
            if ch >= 0.3:
                out.append(("green", f"Sotuv tezlashdi: shu davrda kuniga ~{_n(rep['sum_daily'])} qop "
                            f"(odatda ~{_n(r60)}). Zaxirani oshirish mumkin."))
            elif ch <= -0.3:
                out.append(("red", f"Sotuv sekinlashdi: shu davrda kuniga ~{_n(rep['sum_daily'])} qop "
                            f"(odatda ~{_n(r60)}). Sababini so'rang (raqobatchi? mavsum?)."))
    # keyingi tashrif
    covers = [ (i["today"] + i["qty"]) / i["rate"] for i in adv["items"]
               if (i["rate"] or 0) > 0 and not i["stuck"]]
    if covers:
        nd = max(3, min(14, round(min(covers) - REORDER_COVER)))
        day = (dt.date.fromisoformat(today_str) + dt.timedelta(days=nd))
        out.append(("blue", f"Keyingi tashrif: ~{nd} kundan keyin ({day.strftime('%d.%m')}) — "
                    f"qoldiqni qayta sanash."))
    return out


def _n(v):
    v = round((v or 0) * 10) / 10
    return f"{v:g}"


def tonnes(kg):
    return f"{kg / 1000:.2f}".rstrip("0").rstrip(".") + " t"

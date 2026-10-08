# -*- coding: utf-8 -*-
"""
report_image.py — SANOQ HISOBOTI RASMI (PNG) + qisqa izoh matni
================================================================
build_report()  -> hisob ma'lumotlari (site_analysis bilan, saytga 1:1)
render_png()    -> professional jadval-rasm (Pillow)
build_caption() -> rasm tagidagi qisqa matn (HTML)

Asosiy tamoyil: har bir "sotdi" raqami yonida DAVR yoziladi
(masalan "14 kunda 151 qop"), kunlik tezlik va "necha kunga yetadi"
aynan shu davrdagi sotuvdan hisoblanadi.

Shriftlar: fonts/Inter-*.otf (SIL OFL litsenziya, loyiha ichida).
"""
import io
import html
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import site_analysis as sa

FONT_DIR = Path(__file__).resolve().parent / "fonts"
MONTHS_UZ = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
             "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]


# ===========================================================================
# 1. MA'LUMOT
# ===========================================================================
def build_report(blob, site_client_id, product_ids, date_str, time_str,
                 agent_name=None, today_str=None):
    """Bitta sanoq bo'yicha to'liq hisobot ma'lumoti."""
    today_str = today_str or sa.today()
    clients, products = sa.maps(blob)
    client = clients.get(str(site_client_id), {})
    rows, prev_dates = [], []

    for pid in product_ids:
        p = products.get(str(pid), {})
        price = sa._num(p.get("price"))
        a = sa.analyze_client_product(blob, site_client_id, pid, today_str=today_str)
        st = sa.status_of(a)
        iv = next((i for i in reversed(a["intervals"])
                   if i["to"] == date_str and (i["toT"] or "") == (time_str or "")), None)
        if iv is None and a["intervals"] and a["intervals"][-1]["to"] == date_str:
            iv = a["intervals"][-1]

        if iv is not None:
            prev = iv["startQty"] if iv["hasPrev"] else None
            prev_dates.append(iv["from"])
            deliv, today_q, raw, days = iv["delivered"], iv["endQty"], iv["rawSold"], iv["days"]
            from_date = iv["from"]
        else:
            prev, deliv, today_q, raw, days, from_date = None, 0.0, a["current"], None, None, None

        sold = max(raw, 0.0) if raw is not None else None
        daily = (sold / days) if (sold is not None and days and days > 0) else None
        cover = (today_q / daily) if daily and daily > 0 else None

        is_susp = raw is not None and raw < -0.001
        is_low = today_q < sa.LOW_STOCK
        is_stuck = st == "turgan"
        if is_susp:
            state = "shubhali"
        elif is_low:
            state = "kam"
        elif is_stuck:
            state = "turgan"
        elif iv is None:
            state = "yangi"
        elif cover is not None and cover <= sa.FAST_COVER:
            state = "tez"
        elif sold == 0 or (cover is not None and cover >= sa.SLOW_COVER):
            state = "sekin"
        else:
            state = "normal"

        rows.append({
            "name": p.get("name", str(pid)), "price": price,
            "prev": prev, "deliv": deliv, "today": today_q, "raw": raw, "sold": sold,
            "days": days, "from": from_date, "daily": daily, "cover": cover,
            "state": state, "days_idle": a["daysSinceLastSale"],
            "is_low": is_low, "is_stuck": is_stuck, "is_susp": is_susp,
        })

    order = {"shubhali": 0, "kam": 1, "turgan": 2, "sekin": 3, "normal": 4, "tez": 5, "yangi": 6}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r["sold"] or 0), r["name"]))

    # Asosiy davr: ko'p mahsulotda uchraydigan oldingi sana
    prev_date = Counter(prev_dates).most_common(1)[0][0] if prev_dates else None
    period_days = sa.days_between(prev_date, date_str) if prev_date else None

    sum_sold = sum(r["sold"] or 0 for r in rows)
    # Sarlavhadagi "N kunda" — faqat aynan shu davrda sanalgan mahsulotlar
    main_sold = sum(r["sold"] or 0 for r in rows if r["days"] == period_days)
    other_sold = sum_sold - main_sold
    sum_today = sum(r["today"] for r in rows)
    # Kunlik tezlik — har bir mahsulot o'z davri bo'yicha, keyin yig'iladi
    sum_daily = sum(r["daily"] or 0 for r in rows) or None
    total_cover = (sum_today / sum_daily) if sum_daily else None

    excluded = [x.strip().lower() for x in sa.SHELF_EXCLUDE]
    shelf_total = len([p for p in blob.get("products", []) if isinstance(p, dict)
                       and not any(str(p.get("name", "")).lower().startswith(x) for x in excluded)])
    on_shelf = len([r for r in rows if r["today"] > 0
                    and not any(r["name"].lower().startswith(x) for x in excluded)])

    return {
        "client": client.get("name", str(site_client_id)),
        "region": client.get("region") or "",
        "agent": agent_name or "—",
        "date": date_str, "time": time_str or "",
        "prev_date": prev_date, "period_days": period_days,
        "rows": rows,
        "sum_prev": sum(r["prev"] or 0 for r in rows),
        "sum_deliv": sum(r["deliv"] for r in rows),
        "sum_today": sum_today, "sum_sold": sum_sold,
        "main_sold": main_sold, "other_sold": other_sold,
        "sum_daily": sum_daily, "total_cover": total_cover,
        "value_today": sum(r["today"] * r["price"] for r in rows),
        "value_sold": sum((r["sold"] or 0) * r["price"] for r in rows),
        "shelf": (on_shelf, shelf_total),
        "low": [r for r in rows if r["is_low"]],
        "stuck": [r for r in rows if r["is_stuck"]],
        "susp": [r for r in rows if r["is_susp"]],
        "is_today": date_str >= sa.today(),
    }


# ===========================================================================
# 2. RASM
# ===========================================================================
C = {
    "bg": "#F4F6FA", "card": "#FFFFFF", "ink": "#16202E", "muted": "#6B7686",
    "faint": "#98A2B3", "line": "#E3E8EF", "head": "#13294B", "head2": "#1E3A66",
    "accent": "#F2A900", "zebra": "#F8FAFC",
    "green": "#1E9E5A", "green_bg": "#E3F5EB",
    "red": "#D93838", "red_bg": "#FDE7E7",
    "orange": "#E07B00", "orange_bg": "#FFF1DC",
    "blue": "#2F6FD6", "blue_bg": "#E4EEFC",
    "grey_bg": "#EEF1F5", "purple": "#7A3DB8", "purple_bg": "#F1E8FB",
}
PILL = {
    "shubhali": ("Tekshiring", C["purple"], C["purple_bg"]),
    "kam":      ("Kam qoldi", C["red"], C["red_bg"]),
    "turgan":   ("Turib qolgan", C["red"], C["red_bg"]),
    "sekin":    ("Sekin", C["orange"], C["orange_bg"]),
    "normal":   ("Normal", C["muted"], C["grey_bg"]),
    "tez":      ("Tez", C["green"], C["green_bg"]),
    "yangi":    ("Yangi", C["blue"], C["blue_bg"]),
}


def _f(weight, size):
    name = {"r": "Inter-Regular.otf", "s": "Inter-SemiBold.otf", "b": "Inter-Bold.otf"}[weight]
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def _n(v):
    if v is None:
        return "—"
    v = round(v * 10) / 10
    s = f"{v:,.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return s.replace(",", " ")


def _money(v):
    v = v or 0
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + " mln"
    return f"{round(v):,}".replace(",", " ")


def _ddmm(d):
    return sa.ddmm(d) if d else "—"


def _kun(c):
    if c is None:
        return "—"
    return "1 kundan kam" if c < 1 else f"{round(c)} kun"


def render_png(rep, scale=2) -> bytes:
    S = scale
    W = 1000
    PAD = 28
    ROW_H = 50
    rows = rep["rows"]
    pdays = rep["period_days"]

    HEAD_H = 66  # ikki qatorli sarlavha: nom + sana/davr
    pd_txt = _ddmm(rep["prev_date"]) if rep["prev_date"] else "—"
    td_txt = _ddmm(rep["date"])
    cols = [("Mahsulot", 250, "l", ""),
            ("Oldingi", 84, "r", pd_txt),
            ("Berildi", 104, "r", f"{pd_txt}–{td_txt}" if rep["prev_date"] else "—"),
            ("Bugun", 80, "r", td_txt),
            ("Sotdi", 84, "r", f"{pdays} kunda" if pdays else "—"),
            ("Kuniga", 80, "r", "o'rtacha"),
            ("Yetadi", 100, "r", "qoldiq"),
            ("Holat", 162, "c", "")]
    table_w = sum(c[1] for c in cols)  # = W - 2*PAD

    alerts = []
    for r in rep["susp"]:
        alerts.append(("purple", f"{r['name']} — qoldiq hisobdan {_n(-r['raw'])} qop ko'p. "
                       + ("Bugun yuk berilgan bo'lsa, ertaga sotuv kiritilgach yangilanadi."
                          if rep["is_today"] else "Sotuv kiritilmagan yoki xato sanalgan.")))
    for r in rep["low"]:
        tail = f", ~{_kun(r['cover'])}ga yetadi" if r["cover"] is not None else ""
        alerts.append(("red", f"{r['name']} — {_n(r['today'])} qop qoldi{tail}. "
                       f"Min {sa.LOW_STOCK} qop bo'lishi kerak — akaga yuk taklif qiling."))
    for r in rep["stuck"]:
        alerts.append(("orange", f"{r['name']} — {r['days_idle']} kundan beri sotilmayapti "
                       f"({_n(r['today'])} qop turibdi)."))

    H = (PAD + 120 + 18 + 112 + 18 + HEAD_H + ROW_H * (len(rows) + 1) + 18
         + (46 + 34 * len(alerts) if alerts else 0) + 50 + PAD)
    img = Image.new("RGB", (W * S, H * S), C["bg"])
    d = ImageDraw.Draw(img)

    def rect(x, y, w, h, fill, r=0):
        d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S, fill=fill)

    def text(x, y, s, font, fill, anchor="la"):
        d.text((x * S, y * S), s, font=font, fill=fill, anchor=anchor)

    F = lambda w, s: _f(w, s * S)

    # --- Sarlavha: klent + DAVR katta ------------------------------------
    y = PAD
    rect(PAD, y, W - 2 * PAD, 120, C["head"], r=14)
    rect(PAD, y + 116, W - 2 * PAD, 4, C["accent"])
    text(PAD + 24, y + 20, "SANOQ HISOBOTI  ·  CP CONCRETE", F("b", 13), C["accent"])
    cname = rep["client"] if len(rep["client"]) <= 30 else rep["client"][:29] + "…"
    text(PAD + 24, y + 42, cname, F("b", 28), "#FFFFFF")
    sub = "  ·  ".join(x for x in [rep["region"], f"Agent: {rep['agent']}"] if x)
    text(PAD + 24, y + 84, sub, F("r", 16), "#C9D6EA")
    # Davr bloki (o'ngda)
    bx = W - PAD - 270
    rect(bx, y + 18, 250, 84, C["head2"], r=12)
    text(bx + 125, y + 30, "DAVR", F("s", 12), "#9FB3D1", "ma")
    per = f"{_ddmm(rep['prev_date'])} → {_ddmm(rep['date'])}" if rep["prev_date"] else _ddmm(rep["date"])
    text(bx + 125, y + 48, per, F("b", 20), "#FFFFFF", "ma")
    text(bx + 125, y + 76, f"{pdays} kun" if pdays else "birinchi sanoq", F("s", 15), C["accent"], "ma")
    y += 120 + 18

    # --- 3 ta asosiy raqam -----------------------------------------------
    kpis = [
        (f"{pdays} KUNDA SOTDI" if pdays else "SOTDI",
         f"{_n(rep['main_sold'] if pdays else rep['sum_sold'])} qop",
         (f"+{_n(rep['other_sold'])} qop boshqa davrda" if pdays and rep["other_sold"] > 0.001
          else (f"kuniga ~{_n(rep['sum_daily'])} qop · {_money(rep['value_sold'])} so'm"
                if rep["sum_daily"] else f"{_money(rep['value_sold'])} so'm")), C["green"]),
        ("QOLDIQ", f"{_n(rep['sum_today'])} qop",
         (f"~{_kun(rep['total_cover'])}ga yetadi" if rep["total_cover"] is not None
          else f"{_money(rep['value_today'])} so'm"), C["head2"]),
        ("BERILDI", f"{_n(rep['sum_deliv'])} qop",
         f"{pdays} kun ichida" if pdays else "—", C["blue"]),
    ]
    gap = 14
    kw = (W - 2 * PAD - gap * 2) / 3
    for i, (k, v, sub, col) in enumerate(kpis):
        x = PAD + i * (kw + gap)
        rect(x, y, kw, 112, C["card"], r=12)
        rect(x, y + 16, 4, 80, col, r=2)
        text(x + 22, y + 16, k, F("s", 12), C["muted"])
        text(x + 22, y + 38, v, F("b", 30), C["ink"])
        text(x + 22, y + 82, sub, F("r", 14), C["muted"])
    y += 112 + 18

    # --- Jadval -----------------------------------------------------------
    tx = PAD
    rect(tx, y, table_w, HEAD_H + ROW_H * (len(rows) + 1), C["card"], r=12)
    rect(tx, y, table_w, HEAD_H, C["head2"], r=12)
    rect(tx, y + HEAD_H - 12, table_w, 12, C["head2"])

    def cx(ci):
        x0 = tx + sum(c[1] for c in cols[:ci])
        w, al = cols[ci][1], cols[ci][2]
        return (x0 + 18, "lm") if al == "l" else ((x0 + w - 14, "rm") if al == "r" else (x0 + w / 2, "mm"))

    for ci, (name, _w, _al, sub) in enumerate(cols):
        x, anc = cx(ci)
        if sub:
            text(x, y + HEAD_H / 2 - 10, name, F("s", 15), "#FFFFFF", anc)
            text(x, y + HEAD_H / 2 + 12, sub, F("r", 13), C["accent"], anc)
        else:
            text(x, y + HEAD_H / 2, name, F("s", 15), "#FFFFFF", anc)

    yy = y + HEAD_H
    for ri, r in enumerate(rows):
        if ri % 2 == 1:
            rect(tx, yy, table_w, ROW_H, C["zebra"])
        cy = yy + ROW_H / 2
        nm = r["name"] if len(r["name"]) <= 24 else r["name"][:23] + "…"
        note = None
        if r["days"] is None:
            note = "birinchi sanoq"
        elif pdays is not None and r["days"] != pdays:
            note = f"{r['days']} kunda ({_ddmm(r['from'])} dan)"
        x, anc = cx(0)
        if note:
            text(x, cy - 9, nm, F("s", 16), C["ink"], anc)
            text(x, cy + 12, note, F("r", 12), C["orange"], anc)
        else:
            text(x, cy, nm, F("s", 16), C["ink"], anc)
        x, anc = cx(1); text(x, cy, _n(r["prev"]), F("r", 16), C["muted"], anc)
        x, anc = cx(2)
        has_d = r["deliv"] > 0.001
        text(x, cy, ("+" + _n(r["deliv"])) if has_d else "—", F("s", 16),
             C["blue"] if has_d else C["faint"], anc)
        x, anc = cx(3)
        text(x, cy, _n(r["today"]), F("b", 16), C["red"] if r["is_low"] else C["ink"], anc)
        x, anc = cx(4)
        if r["is_susp"]:
            text(x, cy, f"+{_n(-r['raw'])}?", F("b", 16), C["purple"], anc)
        elif r["sold"]:
            text(x, cy, _n(r["sold"]), F("b", 16), C["green"], anc)
        else:
            text(x, cy, "0" if r["sold"] is not None else "—", F("r", 16), C["faint"], anc)
        x, anc = cx(5)
        text(x, cy, _n(r["daily"]) if r["daily"] else "—", F("r", 16),
             C["ink"] if r["daily"] else C["faint"], anc)
        x, anc = cx(6)
        cov = _kun(r["cover"]) if r["today"] > 0 else "tugagan"
        col = (C["red"] if (r["cover"] is not None and r["cover"] <= 7) or r["today"] <= 0
               else (C["ink"] if r["cover"] is not None else C["faint"]))
        text(x, cy, cov, F("s" if col == C["red"] else "r", 15), col, anc)
        label, fg, bg = PILL.get(r["state"], PILL["normal"])
        pf = F("s", 13)
        tw = d.textlength(label, font=pf) / S
        px, _ = cx(7)
        rect(px - tw / 2 - 12, cy - 13, tw + 24, 26, bg, r=13)
        text(px, cy, label, pf, fg, "mm")
        d.line([(tx + 12) * S, (yy + ROW_H) * S, (tx + table_w - 12) * S, (yy + ROW_H) * S],
               fill=C["line"], width=S)
        yy += ROW_H

    # Jami
    cy = yy + ROW_H / 2
    rect(tx, yy, table_w, ROW_H, "#EEF3FA", r=12)
    rect(tx, yy, table_w, 12, "#EEF3FA")
    x, anc = cx(0); text(x, cy, "JAMI", F("b", 15), C["head"], anc)
    x, anc = cx(1); text(x, cy, _n(rep["sum_prev"]), F("s", 16), C["head"], anc)
    x, anc = cx(2); text(x, cy, ("+" + _n(rep["sum_deliv"])) if rep["sum_deliv"] else "—", F("s", 16), C["blue"], anc)
    x, anc = cx(3); text(x, cy, _n(rep["sum_today"]), F("b", 16), C["head"], anc)
    x, anc = cx(4); text(x, cy, _n(rep["sum_sold"]), F("b", 16), C["green"], anc)
    x, anc = cx(5); text(x, cy, _n(rep["sum_daily"]) if rep["sum_daily"] else "—", F("s", 16), C["head"], anc)
    x, anc = cx(6); text(x, cy, _kun(rep["total_cover"]), F("s", 15), C["head"], anc)
    on, tot = rep["shelf"]
    px, _ = cx(7)
    text(px, cy, f"Polka: {on}/{tot}", F("s", 14), C["head"], "mm")
    y = yy + ROW_H + 18

    # --- E'tibor bering ---------------------------------------------------
    if alerts:
        ah = 46 + 34 * len(alerts)
        rect(PAD, y, W - 2 * PAD, ah, C["card"], r=12)
        rect(PAD, y, 5, ah, C["red"], r=2)
        text(PAD + 22, y + 15, "E'TIBOR BERING", F("b", 15), C["red"])
        ay = y + 46
        for kind, msg in alerts:
            d.ellipse([(PAD + 24) * S, (ay + 6) * S, (PAD + 34) * S, (ay + 16) * S], fill=C[kind])
            m = msg if len(msg) <= 112 else msg[:110] + "…"
            text(PAD + 46, ay + 1, m, F("r", 15), C["ink"])
            ay += 34
        y += ah

    # --- Izoh -------------------------------------------------------------
    text(PAD + 4, y + 16, "Sotdi = oldingi + berildi − bugun   ·   Kuniga = sotdi ÷ kun   ·   "
         "Yetadi = bugun ÷ kuniga", F("r", 13), C["muted"])
    text(W - PAD - 4, y + 16, "CP Sklad", F("s", 13), C["muted"], "ra")

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ===========================================================================
# 3. IZOH (rasm tagidagi matn)
# ===========================================================================
def build_caption(rep) -> str:
    e = lambda s: html.escape(str(s), quote=False)
    pd = rep["period_days"]
    lines = [f"📋 <b>{e(rep['client'])}</b>" + (f" — {e(rep['region'])}" if rep["region"] else ""),
             f"👤 {e(rep['agent'])} · 📅 "
             + (f"{_ddmm(rep['prev_date'])} → {_ddmm(rep['date'])} ({pd} kun)" if pd
                else f"{_ddmm(rep['date'])} (birinchi sanoq)")]
    if pd:
        lines.append(f"🟢 <b>{pd} kunda {_n(rep['main_sold'])} qop sotdi</b>"
                     + (f" (+{_n(rep['other_sold'])} boshqa davrda)" if rep["other_sold"] > 0.001 else "")
                     + (f" · kuniga ~{_n(rep['sum_daily'])}" if rep["sum_daily"] else ""))
    lines.append(f"📦 Qoldiq: {_n(rep['sum_today'])} qop"
                 + (f", ~{_kun(rep['total_cover'])}ga yetadi" if rep["total_cover"] is not None else ""))
    warn = []
    if rep["low"]:
        warn.append("⚠️ <b>Kam qoldi:</b> " + ", ".join(
            f"{e(r['name'])} ({_n(r['today'])})" for r in rep["low"]))
    if rep["stuck"]:
        warn.append("🔴 <b>Turib qolgan:</b> " + ", ".join(e(r["name"]) for r in rep["stuck"]))
    if rep["susp"]:
        warn.append("❗ <b>Tekshiring:</b> " + ", ".join(
            f"{e(r['name'])} (+{_n(-r['raw'])})" for r in rep["susp"]))
    if warn:
        lines.append("")
        lines += warn
        if rep["low"]:
            lines.append("👉 Akaga yuk taklif qilish kerak!")
    cap = "\n".join(lines)
    return cap if len(cap) <= 1000 else cap[:990] + "…"

# -*- coding: utf-8 -*-
"""
product_order.py — TOVARLAR TARTIBI (segment bo'yicha) VA QISQA NOM
==================================================================
Tartib: KRETA -> BIORA -> DOM -> STANDART -> REMOST -> qolganlar
(Evromix, ForGips, Concrete ...). Segment ichida raqam bo'yicha:
01, 03, 07, 21, 22, 75, 77, keyin Rodband, Nalivnoy ...

Botdagi tovar tugmalari, guruhdagi hisobot jadvali va matn — hammasi shu tartibda.
"""
import re

SEGMENTS = [
    ("kreta",),
    ("biora",),
    ("dom",),
    ("standart", "standard"),
    ("remost",),
    ("evromix", "evro mix", "evro"),
    ("forgips", "for gips"),
    ("concrete",),
]


def _segment(name: str) -> int:
    n = (name or "").strip().lower()
    for i, prefixes in enumerate(SEGMENTS):
        if any(n.startswith(p) for p in prefixes):
            return i
    return len(SEGMENTS)


def _natural(name: str):
    """'Kreta 01' < 'Kreta 75' < 'Kreta Rodband' (raqamlilar oldin)."""
    m = re.match(r"\s*\S+\s+(\d{1,3})\b", name or "")   # brenddan keyingi kod
    return (0, int(m.group(1))) if m else (1, 0)


def sort_key(name: str):
    return (_segment(name), _natural(name), (name or "").lower())


def sort_products(items, key=lambda p: p["name"]):
    return sorted(items, key=lambda p: sort_key(key(p)))


_TAIL = re.compile(r"\s*\((suxoy|сухой)\)\s*$", re.I)
_KG = re.compile(r"\s*\b\d{1,2}\s?kg\b", re.I)


def short_name(name: str) -> str:
    """Ko'rsatish uchun: 'Kreta 75 Uselinniy 25kg (Suxoy)' -> 'Kreta 75 Uselinniy'."""
    s = _TAIL.sub("", name or "")
    s = _KG.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s or (name or "")

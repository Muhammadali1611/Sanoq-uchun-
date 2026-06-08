# CP Sklad Bot 🤖

Klentlardagi tovar qoldig'ini sanab boruvchi, sotuvni avtomatik hisoblovchi va
rangli Excel hisobotlar chiqaruvchi Telegram bot.

## Imkoniyatlar
- **Rollar:** Admin · Menejer · Agent
- **Sanoq:** agent regionni tanlaydi → klentni tanlaydi (yoki ism bo'yicha qidiradi)
  → tovar qoldig'ini kiritadi. Bot oldingi sanash bilan solishtirib **sotilgan**
  miqdorni o'zi hisoblaydi.
- **Avtomatik tahlil:** 🟢 tez · ⚪ normal · 🟠 sekin · 🔴 qotib qolgan · 🔵 yangi
- **Hisobotlar (rangli Excel):** kunlik · oylik (3 varaq) · tezkor matnli tahlil
- **Klent qidirish** — ism bo'yicha, oxirgi sanash kartochkasi bilan
- Klent qo'shish/o'chirish · Tovar qo'shish/o'chirish (narxi bilan)
- Begona odam `/start` bosganda **adminga avtomatik so'rov** keladi:
  "Kiritamizmi?" → admin tasdiqlaydi (agent/menejer) yoki rad etadi.

## Baza
Klent va tovar bazasi **oldindan yuklangan** (`sklad.db`):
139 klent · 22 region · 17 tovar.
Qayta yuklash kerak bo'lsa: `data/` ga yangi Excel qo'ying va `python import_data.py`.

## O'rnatish (lokal test)
1. `pip install -r requirements.txt`
2. `@BotFather` dan token, `@userinfobot` dan o'z ID'ingizni oling.
3. `.env.example` ni `.env` ga nusxalang va to'ldiring:
   ```
   BOT_TOKEN=12345:ABC...
   ADMIN_IDS=123456789      # o'z ID'ingiz — siz avtomatik admin bo'lasiz
   ```
4. `python bot.py`  → Telegramda botga `/start`.

## Ishlatish tartibi
1. **Admin** → `/start` (avtomatik admin) → «➕ Agent qo'shish» (Qodirjon),
   «➕ Menejer qo'shish» (Abbosxon).
   - Yoki yangi xodim `/start` bosadi → adminga so'rov boradi → admin tasdiqlaydi.
2. **Agent** → «📋 Sanash» → region → klent → tovar qoldiqlari → «✔️ Tugatdim».
   - Bot darhol oldingi sanash bilan solishtirib natijani ko'rsatadi.
3. **Menejer/Admin** → «📊 Kunlik» / «📈 Oylik» hisobot (Excel) / «📉 Tezkor tahlil».
4. **Qidirish:** «🔍 Klent qidirish» → ism → klentning oxirgi qoldig'i.

## Tahlil mantig'i
Ketma-ket ikki sanash orasida tovar qoldig'i:
- **kamaygan** → sotilgan
- **o'zgarmagan** + uzoq vaqt → qotib qolgan

«Qoplama (kun)» = qoldiq ÷ kunlik sotuv. Chegaralar `config.py` dan:
`FAST_COVER_DAYS=15`, `SLOW_COVER_DAYS=45`, `STUCK_MIN_DAYS=14`.

## Serverga chiqarish (keyinroq)
- `python bot.py` ni `systemd` yoki `screen`/`tmux` da doimiy ishlatish.
- SQLite (`sklad.db`) — bitta fayl, zaxira olish oson.

## Keyingi rejada
- Qarz (to'lov) moduli — joy tayyor.
- 1C 8.3 OData integratsiyasi.
- Klent/tovar tahrirlash.

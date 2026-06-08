"""
Bot sozlamalari. Barcha maxfiy ma'lumotlar .env faylidan o'qiladi.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Loyiha papkasi
BASE_DIR = Path(__file__).resolve().parent

# .env faylini yuklash
load_dotenv(BASE_DIR / ".env")

# Telegram bot tokeni (@BotFather dan olinadi)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Admin Telegram ID lari (vergul bilan ajratiladi). Bular avtomatik admin bo'ladi.
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()]

# SQLite ma'lumotlar bazasi fayli
DB_PATH = str(BASE_DIR / "sklad.db")

# --- Tahlil sozlamalari (keyin o'zgartirsa bo'ladi) ---
# Qoplama kuni: zaxira necha kunga yetadi (qoldiq / kunlik sotuv)
FAST_COVER_DAYS = 15      # bundan kam bo'lsa -> tez sotyapti (yashil)
SLOW_COVER_DAYS = 45      # bundan ko'p bo'lsa -> sekin sotyapti (qizil/sariq)
STUCK_MIN_DAYS = 14       # shuncha kun o'zgarmasa va sotuv 0 bo'lsa -> qotgan (qizil)

# Kam qolgan yuk chegarasi (Excelda qizil qilinadi)
LOW_STOCK_QTY = 30        # qoldiq shundan kam bo'lsa -> kam qolgan (qizil)

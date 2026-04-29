#soglom turmush tarzi
"""
🥗 HealthBot - Sog'lom Turmush Tarzi Telegram Boti
Muallif: AI Assistant
Versiya: 2.0.0

Imkoniyatlar:
- Gemini AI orqali rasm tahlili (kaloriya hisoblash)
- Shaxsiy profil
- Kunlik kaloriya maqsadi
- Ovqat tarixi va statistikalar
- Suv iste'moli kuzatuvi
- Vazn kuzatuvi
- Eslatmalar
- To'liq SQLite ma'lumotlar bazasi
"""

import asyncio
import logging
import sqlite3
import os
import base64
import json
import re
from datetime import datetime, date, timedelta
from typing import Optional
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BufferedInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ===================== KONFIGURATSIYA =====================
BOT_TOKEN = "8592351467:AAG2PbGI4TLsluoNgoLD6cmZxrkILmM_pu0"
GEMINI_API_KEY = "AIzaSyDYtVJnfyTcE2x00a_2nRiiCsLeIkyxWuk"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
DB_PATH = "healthbot.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("healthbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===================== FSM HOLATLAR =====================
class ProfileSetup(StatesGroup):
    name = State()
    age = State()
    gender = State()
    height = State()
    weight = State()
    goal = State()
    activity = State()

class LogFood(StatesGroup):
    manual_input = State()

class LogWater(StatesGroup):
    amount = State()

class LogWeight(StatesGroup):
    weight = State()

class SetGoal(StatesGroup):
    calories = State()

class SetReminder(StatesGroup):
    time = State()
    type = State()

# ===================== MA'LUMOTLAR BAZASI =====================
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    name TEXT,
                    age INTEGER,
                    gender TEXT,
                    height REAL,
                    weight REAL,
                    goal TEXT,
                    activity_level TEXT,
                    daily_calorie_goal INTEGER DEFAULT 2000,
                    daily_water_goal INTEGER DEFAULT 2000,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS food_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    food_name TEXT NOT NULL,
                    calories INTEGER NOT NULL,
                    protein REAL DEFAULT 0,
                    carbs REAL DEFAULT 0,
                    fat REAL DEFAULT 0,
                    meal_type TEXT DEFAULT 'other',
                    source TEXT DEFAULT 'manual',
                    notes TEXT,
                    logged_at TEXT DEFAULT (datetime('now')),
                    log_date TEXT DEFAULT (date('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS water_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    logged_at TEXT DEFAULT (datetime('now')),
                    log_date TEXT DEFAULT (date('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS weight_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    bmi REAL,
                    logged_at TEXT DEFAULT (datetime('now')),
                    log_date TEXT DEFAULT (date('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS workout_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    workout_type TEXT NOT NULL,
                    duration INTEGER,
                    calories_burned INTEGER,
                    notes TEXT,
                    logged_at TEXT DEFAULT (datetime('now')),
                    log_date TEXT DEFAULT (date('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    achievement_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    earned_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    reminder_type TEXT NOT NULL,
                    reminder_time TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
            """)
        logger.info("✅ Ma'lumotlar bazasi tayyor")

    # --- USERS ---
    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.get_conn() as conn:
            return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def create_user(self, user_id: int, username: str, full_name: str):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                (user_id, username, full_name)
            )

    def update_user(self, user_id: int, **kwargs):
        if not kwargs:
            return
        kwargs['updated_at'] = datetime.now().isoformat()
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [user_id]
        with self.get_conn() as conn:
            conn.execute(f"UPDATE users SET {cols} WHERE user_id = ?", vals)

    # --- FOOD LOGS ---
    def log_food(self, user_id: int, food_name: str, calories: int,
                 protein: float = 0, carbs: float = 0, fat: float = 0,
                 meal_type: str = "other", source: str = "manual", notes: str = ""):
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO food_logs
                   (user_id, food_name, calories, protein, carbs, fat, meal_type, source, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, food_name, calories, protein, carbs, fat, meal_type, source, notes)
            )

    def get_today_food(self, user_id: int) -> list:
        today = date.today().isoformat()
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT * FROM food_logs WHERE user_id = ? AND log_date = ? ORDER BY logged_at",
                (user_id, today)
            ).fetchall()

    def get_today_calories(self, user_id: int) -> int:
        today = date.today().isoformat()
        with self.get_conn() as conn:
            result = conn.execute(
                "SELECT COALESCE(SUM(calories), 0) FROM food_logs WHERE user_id = ? AND log_date = ?",
                (user_id, today)
            ).fetchone()
            return result[0] if result else 0

    def get_food_stats(self, user_id: int, days: int = 7) -> list:
        since = (date.today() - timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            return conn.execute(
                """SELECT log_date, SUM(calories) as total_cal,
                   SUM(protein) as total_protein, SUM(carbs) as total_carbs, SUM(fat) as total_fat
                   FROM food_logs WHERE user_id = ? AND log_date >= ?
                   GROUP BY log_date ORDER BY log_date""",
                (user_id, since)
            ).fetchall()

    # --- WATER LOGS ---
    def log_water(self, user_id: int, amount: int):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO water_logs (user_id, amount) VALUES (?, ?)",
                (user_id, amount)
            )

    def get_today_water(self, user_id: int) -> int:
        today = date.today().isoformat()
        with self.get_conn() as conn:
            result = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM water_logs WHERE user_id = ? AND log_date = ?",
                (user_id, today)
            ).fetchone()
            return result[0] if result else 0

    def get_water_stats(self, user_id: int, days: int = 7) -> list:
        since = (date.today() - timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            return conn.execute(
                """SELECT log_date, SUM(amount) as total_water
                   FROM water_logs WHERE user_id = ? AND log_date >= ?
                   GROUP BY log_date ORDER BY log_date""",
                (user_id, since)
            ).fetchall()

    # --- WEIGHT LOGS ---
    def log_weight(self, user_id: int, weight: float, height: float = None):
        bmi = None
        if height and height > 0:
            bmi = round(weight / ((height / 100) ** 2), 1)
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO weight_logs (user_id, weight, bmi) VALUES (?, ?, ?)",
                (user_id, weight, bmi)
            )
        return bmi

    def get_weight_history(self, user_id: int, days: int = 30) -> list:
        since = (date.today() - timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT * FROM weight_logs WHERE user_id = ? AND log_date >= ? ORDER BY log_date",
                (user_id, since)
            ).fetchall()

    # --- ACHIEVEMENTS ---
    def add_achievement(self, user_id: int, atype: str, title: str, desc: str = ""):
        with self.get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM achievements WHERE user_id = ? AND achievement_type = ?",
                (user_id, atype)
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO achievements (user_id, achievement_type, title, description) VALUES (?, ?, ?, ?)",
                    (user_id, atype, title, desc)
                )
                return True
        return False

    def get_achievements(self, user_id: int) -> list:
        with self.get_conn() as conn:
            return conn.execute(
                "SELECT * FROM achievements WHERE user_id = ? ORDER BY earned_at DESC",
                (user_id,)
            ).fetchall()

    def get_full_stats(self, user_id: int) -> dict:
        with self.get_conn() as conn:
            total_food = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(calories), 0) as total FROM food_logs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            total_water = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM water_logs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            weight_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM weight_logs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            streak = self._calc_streak(conn, user_id)
            return {
                "total_food_logs": total_food["cnt"],
                "total_calories_logged": total_food["total"],
                "total_water_ml": total_water["total"],
                "weight_logs": weight_count["cnt"],
                "streak_days": streak
            }

    def _calc_streak(self, conn, user_id: int) -> int:
        rows = conn.execute(
            "SELECT DISTINCT log_date FROM food_logs WHERE user_id = ? ORDER BY log_date DESC",
            (user_id,)
        ).fetchall()
        if not rows:
            return 0
        streak = 0
        check_date = date.today()
        for row in rows:
            row_date = date.fromisoformat(row["log_date"])
            if row_date == check_date:
                streak += 1
                check_date -= timedelta(days=1)
            elif row_date < check_date:
                break
        return streak


# ===================== GEMINI AI =====================
class GeminiAI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = f"{GEMINI_API_URL}?key={api_key}"

    async def analyze_food_image(self, image_bytes: bytes) -> dict:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = """Sen professional dietolog va oziq-ovqat mutaxassisissan.
Bu rasmni tahlil qil va quyidagi JSON formatda javob ber (FAQAT JSON, boshqa hech narsa yozma):

{
  "food_items": ["ovqat nomi 1", "ovqat nomi 2"],
  "total_calories": 000,
  "protein": 00.0,
  "carbs": 00.0,
  "fat": 00.0,
  "meal_type": "breakfast/lunch/dinner/snack",
  "health_score": 0,
  "analysis": "Ovqat haqida qisqacha tahlil (o'zbek tilida)",
  "recommendations": ["Maslahat 1", "Maslahat 2", "Maslahat 3"],
  "alternatives": ["Sog'lom alternativa 1", "Sog'lom alternativa 2"],
  "nutrients_detail": "Asosiy vitaminlar va minerallar haqida qisqacha"
}

health_score 1-10 orasida (10 eng sog'lom).
Barcha ma'lumotlar o'zbek tilida bo'lsin."""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Gemini API xato: {resp.status} - {error_text}")
                        return {"error": f"API xatosi: {resp.status}"}
                    data = await resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    # JSON tozalash
                    text = re.sub(r'```json\s*', '', text)
                    text = re.sub(r'```\s*', '', text)
                    text = text.strip()
                    return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse xato: {e}")
            return {"error": "AI javobi noto'g'ri formatda"}
        except Exception as e:
            logger.error(f"Gemini xato: {e}")
            return {"error": str(e)}

    async def get_nutrition_advice(self, user_data: dict) -> str:
        prompt = f"""Sen professional dietolog sifatida quyidagi foydalanuvchi uchun shaxsiy maslahat ber:

Foydalanuvchi ma'lumotlari:
- Ismi: {user_data.get('name', 'Noma\'lum')}
- Yoshi: {user_data.get('age', '?')} yosh
- Jinsi: {user_data.get('gender', '?')}
- Bo'yi: {user_data.get('height', '?')} sm
- Vazni: {user_data.get('weight', '?')} kg
- Maqsadi: {user_data.get('goal', '?')}
- Faollik darajasi: {user_data.get('activity_level', '?')}
- Bugungi kaloriya: {user_data.get('today_calories', 0)} kkal
- Maqsad kaloriya: {user_data.get('daily_calorie_goal', 2000)} kkal
- Bugungi suv: {user_data.get('today_water', 0)} ml

O'zbek tilida 3-4 ta amaliy maslahat ber. Har bir maslahat yangi qatorda emoji bilan boshlansin."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    data = await resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"Maslahat olishda xato: {e}"


# ===================== KLAVIATURALAR =====================
def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(
        KeyboardButton(text="🍽 Ovqat qo'sh"),
        KeyboardButton(text="💧 Suv qo'sh")
    )
    kb.row(
        KeyboardButton(text="📊 Bugungi holat"),
        KeyboardButton(text="📈 Statistika")
    )
    kb.row(
        KeyboardButton(text="⚖️ Vaznni kirgazish"),
        KeyboardButton(text="💪 Mashq qo'sh")
    )
    kb.row(
        KeyboardButton(text="👤 Profilim"),
        KeyboardButton(text="🏆 Yutuqlar")
    )
    kb.row(
        KeyboardButton(text="💡 Maslahat ol"),
        KeyboardButton(text="⚙️ Sozlamalar")
    )
    return kb.as_markup(resize_keyboard=True)

def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👨 Erkak", callback_data="gender_male"),
        InlineKeyboardButton(text="👩 Ayol", callback_data="gender_female")
    ]])

def goal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ Vazn yo'qotish", callback_data="goal_lose")],
        [InlineKeyboardButton(text="➡️ Vaznni saqlash", callback_data="goal_maintain")],
        [InlineKeyboardButton(text="⬆️ Vazn olish", callback_data="goal_gain")],
        [InlineKeyboardButton(text="💪 Muskullar qurish", callback_data="goal_muscle")],
    ])

def activity_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛋 Kam harakatli", callback_data="act_sedentary")],
        [InlineKeyboardButton(text="🚶 Biroz faol (haftada 1-3)", callback_data="act_light")],
        [InlineKeyboardButton(text="🏃 O'rtacha faol (haftada 3-5)", callback_data="act_moderate")],
        [InlineKeyboardButton(text="🏋️ Juda faol (haftada 6-7)", callback_data="act_active")],
        [InlineKeyboardButton(text="⚡ Sport musobaqa darajasi", callback_data="act_veryactive")],
    ])

def meal_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌅 Nonushta", callback_data="meal_breakfast"),
        InlineKeyboardButton(text="☀️ Tushlik", callback_data="meal_lunch"),
    ], [
        InlineKeyboardButton(text="🌙 Kechki ovqat", callback_data="meal_dinner"),
        InlineKeyboardButton(text="🍎 Kichik ovqat", callback_data="meal_snack"),
    ]])

def water_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🥤 150 ml", callback_data="water_150"),
            InlineKeyboardButton(text="🥛 200 ml", callback_data="water_200"),
            InlineKeyboardButton(text="🍶 250 ml", callback_data="water_250"),
        ],
        [
            InlineKeyboardButton(text="💧 300 ml", callback_data="water_300"),
            InlineKeyboardButton(text="🫙 500 ml", callback_data="water_500"),
            InlineKeyboardButton(text="🍾 1000 ml", callback_data="water_1000"),
        ],
        [InlineKeyboardButton(text="✏️ Boshqa miqdor", callback_data="water_custom")]
    ])

def stats_period_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="7 kun", callback_data="stats_7"),
        InlineKeyboardButton(text="14 kun", callback_data="stats_14"),
        InlineKeyboardButton(text="30 kun", callback_data="stats_30"),
    ]])

def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Kunlik kaloriya maqsadi", callback_data="set_calorie_goal")],
        [InlineKeyboardButton(text="💧 Kunlik suv maqsadi", callback_data="set_water_goal")],
        [InlineKeyboardButton(text="✏️ Profilni tahrirlash", callback_data="edit_profile")],
        [InlineKeyboardButton(text="🗑 Bugungi yozuvni o'chirish", callback_data="clear_today")],
    ])

def workout_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏃 Yugurish", callback_data="workout_running"),
            InlineKeyboardButton(text="🚶 Yurish", callback_data="workout_walking"),
        ],
        [
            InlineKeyboardButton(text="🏋️ Gym", callback_data="workout_gym"),
            InlineKeyboardButton(text="🚴 Velosiped", callback_data="workout_cycling"),
        ],
        [
            InlineKeyboardButton(text="🏊 Suzish", callback_data="workout_swimming"),
            InlineKeyboardButton(text="🧘 Yoga", callback_data="workout_yoga"),
        ],
        [InlineKeyboardButton(text="⚽ Sport o'yini", callback_data="workout_sport")],
    ])


# ===================== YORDAMCHI FUNKSIYALAR =====================
def calc_bmr(weight: float, height: float, age: int, gender: str) -> float:
    if gender == "male":
        return 88.362 + (13.397 * weight) + (4.799 * height) - (5.677 * age)
    else:
        return 447.593 + (9.247 * weight) + (3.098 * height) - (4.330 * age)

def calc_tdee(bmr: float, activity: str) -> float:
    multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "veryactive": 1.9
    }
    return bmr * multipliers.get(activity, 1.2)

def calc_goal_calories(tdee: float, goal: str) -> int:
    adjustments = {
        "lose": -500,
        "maintain": 0,
        "gain": 300,
        "muscle": 200
    }
    return int(tdee + adjustments.get(goal, 0))

def bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "⚠️ Kam vazn"
    elif bmi < 25:
        return "✅ Normal"
    elif bmi < 30:
        return "⚠️ Ortiqcha vazn"
    else:
        return "🚨 Semizlik"

def progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "▱" * length
    pct = min(current / total, 1.0)
    filled = int(pct * length)
    bar = "▰" * filled + "▱" * (length - filled)
    return f"{bar} {int(pct*100)}%"

def format_goal_names(goal: str) -> str:
    names = {
        "lose": "Vazn yo'qotish",
        "maintain": "Vaznni saqlash",
        "gain": "Vazn olish",
        "muscle": "Muskullar qurish"
    }
    return names.get(goal, goal)

def format_activity_names(act: str) -> str:
    names = {
        "sedentary": "Kam harakatli",
        "light": "Biroz faol",
        "moderate": "O'rtacha faol",
        "active": "Juda faol",
        "veryactive": "Sport darajasi"
    }
    return names.get(act, act)

def format_gender(gender: str) -> str:
    return "👨 Erkak" if gender == "male" else "👩 Ayol"


# ===================== ASOSIY ROUTER =====================
router = Router()
db = Database(DB_PATH)
gemini = GeminiAI(GEMINI_API_KEY)


# ===================== START =====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = message.from_user
    db.create_user(user.id, user.username or "", user.full_name or "")
    existing = db.get_user(user.id)

    await state.clear()

    if existing and existing["name"]:
        await message.answer(
            f"🌿 Xush kelibsiz, <b>{existing['name']}</b>!\n\n"
            "HealthBot'ga qaytdingiz 💪\n"
            "Bugun ham sog'lom turmush yo'lida davom eting!",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer(
            "🌿 <b>HealthBot'ga xush kelibsiz!</b>\n\n"
            "Men sizning sog'lom turmush yo'ldoshingizman.\n\n"
            "🍎 Ovqat kaloriyalarini kuzating\n"
            "💧 Suv iste'molini nazorat qiling\n"
            "⚖️ Vaznizni kuzating\n"
            "📊 Statistika va tahlil oling\n"
            "📸 Rasm orqali kaloriya aniqlang (AI)\n\n"
            "Keling, profil yaratamiz! Ismingizni kiriting:",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(ProfileSetup.name)


# ===================== PROFIL YARATISH =====================
@router.message(ProfileSetup.name)
async def profile_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Ism kamida 2 ta harf bo'lishi kerak. Qayta kiriting:")
        return
    await state.update_data(name=name)
    await message.answer(f"✅ Salom, <b>{name}</b>!\n\nYoshingizni kiriting (masalan: 25):", parse_mode=ParseMode.HTML)
    await state.set_state(ProfileSetup.age)

@router.message(ProfileSetup.age)
async def profile_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if not 10 <= age <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ Yoshni to'g'ri kiriting (10-100 orasida):")
        return
    await state.update_data(age=age)
    await message.answer("Jinsingizni tanlang:", reply_markup=gender_kb())
    await state.set_state(ProfileSetup.gender)

@router.callback_query(ProfileSetup.gender, F.data.startswith("gender_"))
async def profile_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split("_")[1]
    await state.update_data(gender=gender)
    await callback.message.edit_text(f"✅ {format_gender(gender)}\n\nBo'yingizni kiriting (sm, masalan: 175):")
    await state.set_state(ProfileSetup.height)

@router.message(ProfileSetup.height)
async def profile_height(message: Message, state: FSMContext):
    try:
        height = float(message.text.strip())
        if not 100 <= height <= 250:
            raise ValueError
    except ValueError:
        await message.answer("❌ Bo'yni to'g'ri kiriting (100-250 sm orasida):")
        return
    await state.update_data(height=height)
    await message.answer("Vaznizni kiriting (kg, masalan: 70):")
    await state.set_state(ProfileSetup.weight)

@router.message(ProfileSetup.weight)
async def profile_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip())
        if not 30 <= weight <= 300:
            raise ValueError
    except ValueError:
        await message.answer("❌ Vaznni to'g'ri kiriting (30-300 kg orasida):")
        return
    await state.update_data(weight=weight)
    await message.answer("Maqsadingizni tanlang:", reply_markup=goal_kb())
    await state.set_state(ProfileSetup.goal)

@router.callback_query(ProfileSetup.goal, F.data.startswith("goal_"))
async def profile_goal(callback: CallbackQuery, state: FSMContext):
    goal = callback.data.split("_")[1]
    await state.update_data(goal=goal)
    await callback.message.edit_text("Faollik darajangizni tanlang:", reply_markup=activity_kb())
    await state.set_state(ProfileSetup.activity)

@router.callback_query(ProfileSetup.activity, F.data.startswith("act_"))
async def profile_activity(callback: CallbackQuery, state: FSMContext):
    activity = callback.data.split("_")[1]
    data = await state.get_data()

    bmr = calc_bmr(data["weight"], data["height"], data["age"], data["gender"])
    tdee = calc_tdee(bmr, activity)
    goal_cal = calc_goal_calories(tdee, data["goal"])
    bmi = round(data["weight"] / ((data["height"] / 100) ** 2), 1)

    db.update_user(
        callback.from_user.id,
        name=data["name"],
        age=data["age"],
        gender=data["gender"],
        height=data["height"],
        weight=data["weight"],
        goal=data["goal"],
        activity_level=activity,
        daily_calorie_goal=goal_cal,
        daily_water_goal=2500 if data["weight"] * 30 > 2500 else int(data["weight"] * 30)
    )

    # Birinchi vazn yozuvi
    db.log_weight(callback.from_user.id, data["weight"], data["height"])

    # Birinchi yutuq
    db.add_achievement(callback.from_user.id, "first_login",
                       "🌟 Sog'lom hayot boshlanishi",
                       "Profil muvaffaqiyatli yaratildi!")

    await state.clear()
    await callback.message.edit_text(
        f"🎉 <b>Profil muvaffaqiyatli yaratildi!</b>\n\n"
        f"👤 {data['name']} | {data['age']} yosh | {format_gender(data['gender'])}\n"
        f"📏 Bo'y: {data['height']} sm | Vazn: {data['weight']} kg\n"
        f"📊 BMI: {bmi} ({bmi_category(bmi)})\n"
        f"🎯 Maqsad: {format_goal_names(data['goal'])}\n"
        f"⚡ Faollik: {format_activity_names(activity)}\n\n"
        f"🔥 Kunlik kaloriya maqsadi: <b>{goal_cal} kkal</b>\n"
        f"💧 Kunlik suv maqsadi: <b>{int(data['weight'] * 30)} ml</b>\n\n"
        "✨ Endi ovqat rasmini yuborib kaloriyani aniqlang!",
        parse_mode=ParseMode.HTML
    )
    await callback.message.answer("Asosiy menyu:", reply_markup=main_menu_kb())


# ===================== RASM TAHLILI (GEMINI AI) =====================
@router.message(F.photo)
async def handle_photo(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Avval /start bosing va profilingizni yarating!")
        return

    wait_msg = await message.answer("🔍 Rasm tahlil qilinmoqda... Biroz kuting ⏳")

    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        image_bytes = file_bytes.read()

        result = await gemini.analyze_food_image(image_bytes)

        if "error" in result:
            await wait_msg.edit_text(
                f"❌ Tahlilda xato: {result['error']}\n\n"
                "Iltimos, aniq ovqat rasmini yuboring yoki qo'lda qo'shing."
            )
            return

        foods = ", ".join(result.get("food_items", ["Noma'lum"]))
        calories = result.get("total_calories", 0)
        protein = result.get("protein", 0)
        carbs = result.get("carbs", 0)
        fat = result.get("fat", 0)
        health_score = result.get("health_score", 5)
        analysis = result.get("analysis", "")
        recommendations = result.get("recommendations", [])
        alternatives = result.get("alternatives", [])
        nutrients = result.get("nutrients_detail", "")
        meal_type = result.get("meal_type", "other")

        # Kaloriyani log
        db.log_food(
            user_id=message.from_user.id,
            food_name=foods,
            calories=calories,
            protein=protein,
            carbs=carbs,
            fat=fat,
            meal_type=meal_type,
            source="ai_image",
            notes=analysis[:200] if analysis else ""
        )

        today_cal = db.get_today_calories(message.from_user.id)
        goal_cal = user["daily_calorie_goal"] or 2000
        remaining = goal_cal - today_cal

        health_emoji = "🟢" if health_score >= 7 else "🟡" if health_score >= 4 else "🔴"
        recs_text = "\n".join(f"  • {r}" for r in recommendations[:3]) if recommendations else "  • Ovqatlanishingiz yaxshi!"
        alts_text = "\n".join(f"  🔄 {a}" for a in alternatives[:2]) if alternatives else ""

        text = (
            f"🍽 <b>AI Tahlil natijalari</b>\n\n"
            f"📌 Ovqat: <b>{foods}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 Kaloriya: <b>{calories} kkal</b>\n"
            f"🥩 Oqsil: {protein}g | 🌾 Uglevodlar: {carbs}g | 🧈 Yog': {fat}g\n\n"
            f"{health_emoji} Sog'liq bali: <b>{health_score}/10</b>\n\n"
        )

        if analysis:
            text += f"💬 <i>{analysis}</i>\n\n"

        if nutrients:
            text += f"🔬 {nutrients}\n\n"

        text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <b>Maslahatlar:</b>\n{recs_text}\n\n"
        )

        if alts_text:
            text += f"🥗 <b>Sog'lom alternativalar:</b>\n{alts_text}\n\n"

        text += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Bugungi holat:</b>\n"
            f"🔥 {today_cal}/{goal_cal} kkal {progress_bar(today_cal, goal_cal)}\n"
            f"{'✅ Maqsadga erishildi!' if remaining <= 0 else f'📉 Qoldi: {remaining} kkal'}"
        )

        await wait_msg.delete()
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

        # Yutuqlar tekshirish
        total_logs = len(db.get_today_food(message.from_user.id))
        if total_logs == 1:
            if db.add_achievement(message.from_user.id, "first_food_log",
                                  "🍽 Birinchi qadam", "Birinchi ovqatni qo'shdingiz!"):
                await message.answer("🏆 <b>Yangi yutuq!</b> 🍽 Birinchi qadam olindi!", parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Rasm tahlili xato: {e}", exc_info=True)
        await wait_msg.edit_text(f"❌ Xato yuz berdi: {str(e)}\n\nQayta urinib ko'ring.")


# ===================== OVQAT QO'SHISH =====================
@router.message(F.text == "🍽 Ovqat qo'sh")
async def add_food_menu(message: Message):
    await message.answer(
        "🍽 <b>Ovqat qo'shish</b>\n\n"
        "📸 Ovqat rasmini yuboring — AI avtomatik kaloriyasini hisoblab beradi!\n\n"
        "✍️ Yoki qo'lda kiriting (masalan):\n"
        "<code>Palov 350 30 45 12 lunch</code>\n"
        "<i>(nom kaloriya oqsil uglevod yog' nonushta/tushlik/kechki/snack)</i>",
        parse_mode=ParseMode.HTML
    )

@router.message(F.text == "💧 Suv qo'sh")
async def add_water_menu(message: Message):
    today_water = db.get_today_water(message.from_user.id)
    user = db.get_user(message.from_user.id)
    water_goal = user["daily_water_goal"] if user else 2000

    await message.answer(
        f"💧 <b>Suv qo'shish</b>\n\n"
        f"Bugun ichilgan: <b>{today_water} ml</b>\n"
        f"Maqsad: <b>{water_goal} ml</b>\n"
        f"{progress_bar(today_water, water_goal)}\n\n"
        "Qancha suv ichdingiz?",
        parse_mode=ParseMode.HTML,
        reply_markup=water_amount_kb()
    )

@router.callback_query(F.data.startswith("water_"))
async def handle_water(callback: CallbackQuery, state: FSMContext):
    amount_str = callback.data.split("_")[1]
    if amount_str == "custom":
        await callback.message.edit_text("Miqdorni ml da kiriting (masalan: 350):")
        await state.set_state(LogWater.amount)
        return

    amount = int(amount_str)
    await _log_water(callback.message, callback.from_user.id, amount)
    await callback.answer(f"✅ {amount} ml suv qo'shildi!")

@router.message(LogWater.amount)
async def log_water_custom(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if not 50 <= amount <= 5000:
            raise ValueError
    except ValueError:
        await message.answer("❌ To'g'ri miqdor kiriting (50-5000 ml):")
        return
    await state.clear()
    await _log_water(message, message.from_user.id, amount)

async def _log_water(message: Message, user_id: int, amount: int):
    db.log_water(user_id, amount)
    today_water = db.get_today_water(user_id)
    user = db.get_user(user_id)
    water_goal = user["daily_water_goal"] if user else 2000

    status = "✅ Maqsadga erishdingiz!" if today_water >= water_goal else f"Qoldi: {water_goal - today_water} ml"

    await message.answer(
        f"💧 <b>+{amount} ml suv qo'shildi!</b>\n\n"
        f"Bugun jami: <b>{today_water} ml</b>\n"
        f"Maqsad: {water_goal} ml\n"
        f"{progress_bar(today_water, water_goal)}\n"
        f"{status}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb()
    )

    # Suv maqsadi yutuq
    if today_water >= water_goal:
        if db.add_achievement(user_id, "water_goal", "💧 Suv chempioni", "Kunlik suv maqsadiga erishdingiz!"):
            await message.answer("🏆 <b>Yangi yutuq!</b> 💧 Suv chempioni!", parse_mode=ParseMode.HTML)


# ===================== QO'LDA OVQAT KIRISH =====================
@router.message(F.text.regexp(r'^\S.+\s+\d+'))
async def manual_food_input(message: Message):
    """Format: nom kaloriya [oqsil uglevod yog' [meal_type]]"""
    user = db.get_user(message.from_user.id)
    if not user:
        return

    parts = message.text.strip().split()
    try:
        # Oxirgi son - kaloriya, undan oldingi - nom
        cal_idx = None
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].isdigit():
                cal_idx = i
                break

        if cal_idx is None:
            return

        # Ovqat nomi oxirgi raqamdan oldingi qism
        food_name = " ".join(parts[:cal_idx])
        calories = int(parts[cal_idx])

        if calories < 1 or calories > 5000:
            return

        protein = float(parts[cal_idx + 1]) if cal_idx + 1 < len(parts) else 0
        carbs = float(parts[cal_idx + 2]) if cal_idx + 2 < len(parts) else 0
        fat = float(parts[cal_idx + 3]) if cal_idx + 3 < len(parts) else 0
        meal_types = {"breakfast": "breakfast", "lunch": "lunch", "dinner": "dinner",
                      "snack": "snack", "nonushta": "breakfast", "tushlik": "lunch",
                      "kechki": "dinner"}
        meal_type_str = parts[cal_idx + 4] if cal_idx + 4 < len(parts) else ""
        meal_type = meal_types.get(meal_type_str.lower(), "other")

        db.log_food(message.from_user.id, food_name, calories, protein, carbs, fat, meal_type)

        today_cal = db.get_today_calories(message.from_user.id)
        goal_cal = user["daily_calorie_goal"] or 2000

        await message.answer(
            f"✅ <b>{food_name}</b> qo'shildi!\n\n"
            f"🔥 {calories} kkal | 🥩 {protein}g | 🌾 {carbs}g | 🧈 {fat}g\n\n"
            f"📊 Bugun jami: <b>{today_cal}/{goal_cal} kkal</b>\n"
            f"{progress_bar(today_cal, goal_cal)}",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_kb()
        )
    except (ValueError, IndexError):
        pass  # Oddiy xabar, ovqat emas


# ===================== BUGUNGI HOLAT =====================
@router.message(F.text == "📊 Bugungi holat")
async def today_status(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("❌ Avval /start bosib profilingizni yarating!")
        return

    today_cal = db.get_today_calories(message.from_user.id)
    today_water = db.get_today_water(message.from_user.id)
    food_logs = db.get_today_food(message.from_user.id)

    goal_cal = user["daily_calorie_goal"] or 2000
    water_goal = user["daily_water_goal"] or 2000
    remaining_cal = goal_cal - today_cal

    total_protein = sum(f["protein"] for f in food_logs)
    total_carbs = sum(f["carbs"] for f in food_logs)
    total_fat = sum(f["fat"] for f in food_logs)

    cal_status = "✅ Maqsadga erishdingiz!" if remaining_cal <= 0 else f"Qoldi: {remaining_cal} kkal"

    text = (
        f"📊 <b>Bugungi holat</b> — {date.today().strftime('%d.%m.%Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 <b>Kaloriya:</b>\n"
        f"   {today_cal}/{goal_cal} kkal\n"
        f"   {progress_bar(today_cal, goal_cal)}\n"
        f"   {cal_status}\n\n"
        f"💧 <b>Suv:</b>\n"
        f"   {today_water}/{water_goal} ml\n"
        f"   {progress_bar(today_water, water_goal)}\n\n"
        f"🥗 <b>Makronutrientlar:</b>\n"
        f"   🥩 Oqsil: {total_protein:.1f}g\n"
        f"   🌾 Uglevodlar: {total_carbs:.1f}g\n"
        f"   🧈 Yog': {total_fat:.1f}g\n\n"
    )

    if food_logs:
        text += f"📋 <b>Bugungi ovqatlar ({len(food_logs)} ta):</b>\n"
        meal_emojis = {"breakfast": "🌅", "lunch": "☀️", "dinner": "🌙", "snack": "🍎", "other": "🍽"}
        for f in food_logs[-5:]:  # Oxirgi 5 ta
            emoji = meal_emojis.get(f["meal_type"], "🍽")
            source = "🤖" if f["source"] == "ai_image" else "✍️"
            text += f"   {emoji}{source} {f['food_name'][:20]} — {f['calories']} kkal\n"
        if len(food_logs) > 5:
            text += f"   ... va yana {len(food_logs) - 5} ta\n"
    else:
        text += "📋 Bugun hali ovqat qo'shilmagan\n📸 Rasm yuboring yoki qo'lda kiriting!"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ===================== STATISTIKA =====================
@router.message(F.text == "📈 Statistika")
async def show_stats(message: Message):
    await message.answer(
        "📈 <b>Statistika davri:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=stats_period_kb()
    )

@router.callback_query(F.data.startswith("stats_"))
async def show_stats_period(callback: CallbackQuery):
    days = int(callback.data.split("_")[1])
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Avval profil yarating!")
        return

    food_stats = db.get_food_stats(callback.from_user.id, days)
    water_stats = db.get_water_stats(callback.from_user.id, days)
    weight_hist = db.get_weight_history(callback.from_user.id, days)
    full_stats = db.get_full_stats(callback.from_user.id)

    goal_cal = user["daily_calorie_goal"] or 2000

    if not food_stats:
        await callback.message.edit_text(
            f"📈 So'nggi {days} kun uchun ma'lumot topilmadi.\n"
            "Ovqat qo'shishni boshlang!"
        )
        return

    avg_cal = sum(r["total_cal"] for r in food_stats) / len(food_stats)
    avg_water = (sum(r["total_water"] for r in water_stats) / len(water_stats)) if water_stats else 0
    days_on_goal = sum(1 for r in food_stats if abs(r["total_cal"] - goal_cal) <= 200)

    text = (
        f"📈 <b>So'nggi {days} kunlik statistika</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 Kuzatilgan kunlar: {len(food_stats)}\n"
        f"🔥 O'rtacha kaloriya: <b>{avg_cal:.0f} kkal/kun</b>\n"
        f"🎯 Maqsadga mos kunlar: {days_on_goal}/{len(food_stats)}\n"
        f"💧 O'rtacha suv: <b>{avg_water:.0f} ml/kun</b>\n\n"
    )

    if weight_hist and len(weight_hist) >= 2:
        first_w = weight_hist[0]["weight"]
        last_w = weight_hist[-1]["weight"]
        diff = last_w - first_w
        sign = "+" if diff > 0 else ""
        text += f"⚖️ Vazn o'zgarishi: <b>{sign}{diff:.1f} kg</b>\n"
        text += f"   {first_w} kg → {last_w} kg\n\n"

    text += (
        f"📊 <b>Umumiy statistika:</b>\n"
        f"   📝 Jami yozuvlar: {full_stats['total_food_logs']}\n"
        f"   🔥 Jami kaloriya: {full_stats['total_calories_logged']:,} kkal\n"
        f"   💧 Jami suv: {full_stats['total_water_ml']:,} ml\n"
        f"   🔥 Streak: {full_stats['streak_days']} kun ketma-ket!\n\n"
    )

    # Oxirgi 5 kun kaloriya
    if food_stats:
        text += "📅 <b>Oxirgi kunlar:</b>\n"
        for row in food_stats[-5:]:
            day = row["log_date"]
            cal = row["total_cal"]
            bar = progress_bar(cal, goal_cal, 6)
            text += f"   {day}: {cal} kkal {bar}\n"

    await callback.message.edit_text(text, parse_mode=ParseMode.HTML)


# ===================== VAZN =====================
@router.message(F.text == "⚖️ Vaznni kirgazish")
async def log_weight_start(message: Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    weight_hist = db.get_weight_history(message.from_user.id, 7)

    text = "⚖️ <b>Vaznni kiriting (kg):</b>\n"
    if weight_hist:
        last = weight_hist[-1]
        text += f"\nOxirgi vazn: {last['weight']} kg ({last['log_date']})"
        if last['bmi']:
            text += f"\nBMI: {last['bmi']} ({bmi_category(last['bmi'])})"
    text += "\n\nMasalan: 72.5"

    await message.answer(text, parse_mode=ParseMode.HTML)
    await state.set_state(LogWeight.weight)

@router.message(LogWeight.weight)
async def save_weight(message: Message, state: FSMContext):
    try:
        weight = float(message.text.strip())
        if not 30 <= weight <= 300:
            raise ValueError
    except ValueError:
        await message.answer("❌ To'g'ri vazn kiriting (30-300 kg):")
        return

    await state.clear()
    user = db.get_user(message.from_user.id)
    height = user["height"] if user else None
    bmi = db.log_weight(message.from_user.id, weight, height)

    if user:
        db.update_user(message.from_user.id, weight=weight)

    text = f"✅ <b>Vazn saqlandi: {weight} kg</b>\n"
    if bmi:
        text += f"\n📊 BMI: <b>{bmi}</b>\n"
        text += f"Holat: {bmi_category(bmi)}\n"

    weight_hist = db.get_weight_history(message.from_user.id, 30)
    if len(weight_hist) >= 2:
        start_w = weight_hist[0]["weight"]
        diff = weight - start_w
        sign = "+" if diff > 0 else ""
        text += f"\n📉 30 kun ichida: {sign}{diff:.1f} kg"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    # Yutuq
    if len(weight_hist) >= 7:
        if db.add_achievement(message.from_user.id, "weight_tracker",
                              "⚖️ Vazn kuzatuvchi", "7 marta vazn kiritdingiz!"):
            await message.answer("🏆 <b>Yangi yutuq!</b> ⚖️ Vazn kuzatuvchi!", parse_mode=ParseMode.HTML)


# ===================== MASHQ =====================
@router.message(F.text == "💪 Mashq qo'sh")
async def add_workout(message: Message):
    await message.answer("💪 <b>Mashq turini tanlang:</b>", parse_mode=ParseMode.HTML, reply_markup=workout_type_kb())

@router.callback_query(F.data.startswith("workout_"))
async def handle_workout(callback: CallbackQuery):
    workout_type = callback.data.split("_")[1]
    workout_names = {
        "running": ("🏃 Yugurish", 600),
        "walking": ("🚶 Yurish", 300),
        "gym": ("🏋️ Gym", 450),
        "cycling": ("🚴 Velosiped", 500),
        "swimming": ("🏊 Suzish", 550),
        "yoga": ("🧘 Yoga", 200),
        "sport": ("⚽ Sport o'yini", 480),
    }

    name, cal_per_hour = workout_names.get(workout_type, ("🏃 Mashq", 400))

    # 30 daqiqa uchun hisob
    calories_burned = int(cal_per_hour * 0.5)
    duration = 30

    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO workout_logs (user_id, workout_type, duration, calories_burned) VALUES (?, ?, ?, ?)",
            (callback.from_user.id, workout_type, duration, calories_burned)
        )

    await callback.message.edit_text(
        f"💪 <b>{name} qo'shildi!</b>\n\n"
        f"⏱ Davomiylik: {duration} daqiqa\n"
        f"🔥 Yoqilgan: {calories_burned} kkal\n\n"
        "✅ Mashqingiz saqlandi!",
        parse_mode=ParseMode.HTML
    )
    await callback.message.answer("Davom eting!", reply_markup=main_menu_kb())
    await callback.answer("✅ Mashq saqlandi!")


# ===================== PROFIL =====================
@router.message(F.text == "👤 Profilim")
async def show_profile(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("❌ Avval /start bosib profilingizni yarating!")
        return

    bmi = None
    if user["weight"] and user["height"]:
        bmi = round(user["weight"] / ((user["height"] / 100) ** 2), 1)

    text = (
        f"👤 <b>Shaxsiy Profil</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Ism: <b>{user['name']}</b>\n"
        f"🎂 Yosh: {user['age'] or '?'}\n"
        f"⚧ Jins: {format_gender(user['gender']) if user['gender'] else '?'}\n"
        f"📏 Bo'y: {user['height'] or '?'} sm\n"
        f"⚖️ Vazn: {user['weight'] or '?'} kg\n"
    )

    if bmi:
        text += f"📊 BMI: <b>{bmi}</b> ({bmi_category(bmi)})\n"

    text += (
        f"\n🎯 Maqsad: {format_goal_names(user['goal']) if user['goal'] else '?'}\n"
        f"⚡ Faollik: {format_activity_names(user['activity_level']) if user['activity_level'] else '?'}\n\n"
        f"🔥 Kunlik kaloriya maqsadi: <b>{user['daily_calorie_goal']} kkal</b>\n"
        f"💧 Kunlik suv maqsadi: <b>{user['daily_water_goal']} ml</b>\n"
        f"\n📅 A'zo bo'lgan: {user['created_at'][:10]}\n"
    )

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ===================== YUTUQLAR =====================
@router.message(F.text == "🏆 Yutuqlar")
async def show_achievements(message: Message):
    achievements = db.get_achievements(message.from_user.id)

    if not achievements:
        await message.answer(
            "🏆 <b>Yutuqlar</b>\n\n"
            "Hali yutuq yo'q. Faoliyatni boshlang!\n\n"
            "💡 Yutuqlar qanday qozoniladi:\n"
            "  • Profil yaratish\n"
            "  • Birinchi ovqat qo'shish\n"
            "  • Suv maqsadiga erishish\n"
            "  • Ketma-ket kunlar kuzatuvi\n"
            "  • Va ko'p boshqalar!",
            parse_mode=ParseMode.HTML
        )
        return

    text = f"🏆 <b>Yutuqlar ({len(achievements)} ta)</b>\n\n"
    for a in achievements:
        text += f"🥇 <b>{a['title']}</b>\n"
        if a['description']:
            text += f"   {a['description']}\n"
        text += f"   📅 {a['earned_at'][:10]}\n\n"

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


# ===================== MASLAHAT =====================
@router.message(F.text == "💡 Maslahat ol")
async def get_advice(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user["name"]:
        await message.answer("❌ Avval profilingizni yarating!")
        return

    wait_msg = await message.answer("🤖 AI maslahat tayyorlamoqda... ⏳")

    today_cal = db.get_today_calories(message.from_user.id)
    today_water = db.get_today_water(message.from_user.id)

    user_data = {
        "name": user["name"],
        "age": user["age"],
        "gender": user["gender"],
        "height": user["height"],
        "weight": user["weight"],
        "goal": format_goal_names(user["goal"]) if user["goal"] else "?",
        "activity_level": format_activity_names(user["activity_level"]) if user["activity_level"] else "?",
        "today_calories": today_cal,
        "daily_calorie_goal": user["daily_calorie_goal"],
        "today_water": today_water,
    }

    advice = await gemini.get_nutrition_advice(user_data)

    await wait_msg.delete()
    await message.answer(
        f"💡 <b>Shaxsiy maslahatlar</b>\n\n{advice}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb()
    )


# ===================== SOZLAMALAR =====================
@router.message(F.text == "⚙️ Sozlamalar")
async def show_settings(message: Message):
    await message.answer(
        "⚙️ <b>Sozlamalar</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=settings_kb()
    )

@router.callback_query(F.data == "set_calorie_goal")
async def set_calorie_goal(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🎯 Yangi kunlik kaloriya maqsadini kiriting (kkal):\nMasalan: 2200")
    await state.set_state(SetGoal.calories)

@router.message(SetGoal.calories)
async def save_calorie_goal(message: Message, state: FSMContext):
    try:
        cal = int(message.text.strip())
        if not 800 <= cal <= 6000:
            raise ValueError
    except ValueError:
        await message.answer("❌ To'g'ri kaloriya kiriting (800-6000):")
        return
    await state.clear()
    db.update_user(message.from_user.id, daily_calorie_goal=cal)
    await message.answer(
        f"✅ Kunlik kaloriya maqsadi <b>{cal} kkal</b> ga o'zgartirildi!",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb()
    )

@router.callback_query(F.data == "edit_profile")
async def edit_profile(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✏️ Profilni qayta to'ldirish uchun ismingizni kiriting:")
    await state.set_state(ProfileSetup.name)

@router.callback_query(F.data == "clear_today")
async def clear_today(callback: CallbackQuery):
    today = date.today().isoformat()
    with db.get_conn() as conn:
        conn.execute(
            "DELETE FROM food_logs WHERE user_id = ? AND log_date = ?",
            (callback.from_user.id, today)
        )
        conn.execute(
            "DELETE FROM water_logs WHERE user_id = ? AND log_date = ?",
            (callback.from_user.id, today)
        )
    await callback.message.edit_text("✅ Bugungi barcha yozuvlar o'chirildi!")
    await callback.message.answer("Qayta boshlang!", reply_markup=main_menu_kb())
    await callback.answer("O'chirildi!")


# ===================== HELP & ABOUT =====================
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>HealthBot Qo'llanma</b>\n\n"
        "📸 <b>Rasm yuborish:</b> Ovqat rasmini yuboring — AI avtomatik kaloriyasini hisoblab beradi!\n\n"
        "✍️ <b>Qo'lda qo'shish:</b>\n"
        "<code>Palov 350</code> — oddiy\n"
        "<code>Palov 350 10 45 12</code> — makronutrientlar bilan\n"
        "<code>Palov 350 10 45 12 lunch</code> — to'liq\n\n"
        "📊 <b>Buyruqlar:</b>\n"
        "/start — Boshlaш / Profil\n"
        "/help — Yordam\n"
        "/stats — Statistika\n"
        "/profile — Profil\n"
        "/reset — Profilni qayta yaratish\n\n"
        "💡 Kundalik foydalanish tavsiyasi:\n"
        "  🌅 Nonushtadan keyin rasm yuboring\n"
        "  💧 Suv ichgan sayin belgilang\n"
        "  ⚖️ Har kuni vazn kiriting\n"
        "  📊 Statistikani kuzating",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    await show_stats(message)

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    await show_profile(message)

@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔄 Profil qayta yaratilmoqda. Ismingizni kiriting:")
    await state.set_state(ProfileSetup.name)


# ===================== ASOSIY =====================
async def main():
    logger.info("🚀 HealthBot ishga tushmoqda...")

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ BOT_TOKEN o'rnatilmagan! main.py ni oching va tokenni kiriting.")
        return

    if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        logger.error("❌ GEMINI_API_KEY o'rnatilmagan! aistudio.google.com dan oling.")
        return

    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    logger.info("✅ Bot tayyor! Xabarlar qabul qilinmoqda...")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Bot xatosi: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

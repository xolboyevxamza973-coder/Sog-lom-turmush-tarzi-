import asyncio
from os import getenv
from dotenv import load_dotenv
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import google.generativeai as genai

load_dotenv()



# --- KONFIGURATSIYA ---
API_TOKEN =getenv("BOT_TOKEN")
GEMINI_KEY = "mAitaLmkHPPlz7IPvtfUqQ4"

# Gemini AI ni sozlash
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Gemini sozlashda xato: {e}")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


class BotStates(StatesGroup):
    waiting_for_input = State()


def main_menu():
    row1 = [KeyboardButton(text="🍎 Mevalar"), KeyboardButton(text="🥦 Sabzavotlar")]
    row2 = [KeyboardButton(text="🍲 Oziq-ovqatlar"), KeyboardButton(text="🍰 Shirinliklar")]
    return ReplyKeyboardMarkup(keyboard=[row1, row2], resize_keyboard=True)


@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    welcome_text = (
        "Assalomu aleykum bizning sog'lom turmush tarzi botiga xush kelibsiz. "
        "Siz bu yerda meva, sabzavot, oziq-ovqat va shirinliklarning taxminiy kaloriya miqdori "
        "va foydali xususiyatlarini aniqlashingiz mumkin."
    )
    await message.answer(welcome_text, reply_markup=main_menu())
    await message.answer("O'zingizga keraklisini tanlang:")


@dp.message(F.text.in_(["🍎 Mevalar", "🥦 Sabzavotlar", "🍲 Oziq-ovqatlar", "🍰 Shirinliklar"]))
async def category_chosen(message: types.Message, state: FSMContext):
    category = message.text
    await state.update_data(chosen_category=category)
    await message.answer(f"Hozir {category} bo'limidasiz. \nMahsulot rasmini yuboring yoki nomini yozing:")
    await state.set_state(BotStates.waiting_for_input)


@dp.message(BotStates.waiting_for_input)
async def analyze_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("chosen_category")

    await message.answer("Tahlil qilinmoqda... ⏳")

    try:
        prompt = (
            f"Foydalanuvchi {category} bo'limini tanladi. "
            "Ushbu mahsulotning 100 gramm uchun taxminiy kaloriya miqdorini va "
            "3 ta foydali xususiyatini o'zbek tilida chiroyli tartibda sanab bering."
        )

        if message.photo:
            # Rasmni yuklab olish va xotirada saqlash
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            # download_file o'rniga io.BytesIO ishlatish xatoliklarni kamaytiradi
            import io
            dest = io.BytesIO()
            await bot.download_file(file.file_path, dest)

            response = model.generate_content([
                prompt,
                {"mime_type": "image/jpeg", "data": dest.getvalue()}
            ])
        else:
            # Matn yuborilsa
            response = model.generate_content(f"{prompt}. Mahsulot nomi: {message.text}")

        if response.text:
            await message.reply(response.text)
        else:
            await message.reply("AI javob bera olmadi. Iltimos, boshqa rasm yuborib ko'ring.")

        await message.answer("Yana biror narsani tekshiramizmi?", reply_markup=main_menu())
        await state.clear()

    except Exception as e:
        logging.error(f"Xatolik tafsiloti: {e}")
        await message.answer(f"Xatolik yuz berdi. \nXato turi: {str(e)[:50]}...")
        await state.clear()


async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
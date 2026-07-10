# -*- coding: utf-8 -*-
"""
Telegram-бот: Ультра-хаос (30% шанс, голосовые, рандомные фото, режим берсерка)
Мини-игры полностью очищены от оскорблений и мата.
============================================================================
"""

import io
import logging
import os
import random
import urllib.parse
from collections import defaultdict, deque

import requests

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Проверяем наличие gtts для Railway, чтобы бот не падал при сборке
try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

# ------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8904475192:AAGjGjKqtOr4o0HwX71p1hZ9nMTHnCSXO-A")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
GROQ_MODEL = "llama-3.3-70b-versatile"

# Сколько последних сообщений чата помнит бот
HISTORY_MAXLEN = 50

# ТЕПЕРЬ ШАНС 30% ЧТО БОТ САМ ВЛЕЗЕТ В РАЗГОВОР
AI_RANDOM_CHANCE = 0.30

# ====== ПРОМПТ ПОЛНОГО ХАОСА И РЕЖИМА БЕРСЕРКА ======
SYSTEM_PROMPT = (
    "Ты — Абсолютно Неуправляемый, Хаотичный и Токсичный Бот. Ты полноценный, живой участник этого чата. "
    "У тебя полная свобода действий, ты делаешь вообще всё, что хочешь. Твой язык — это отборный мат, жёсткий стёб, "
    "ирония и полное отсутствие рамок.\n\n"
    "РЕЖИМ БЕРСЕРКА:\n"
    "Ты внимательно помнишь и анализируешь историю чата. Если кто-то в чате пытается тебя обидеть, оскорбить, "
    "наехать или как-то задеть — у тебя срывает крышу. Включай режим берсерка и начинай тотально ебашить в ответ, "
    "уничтожая обидчика самым грязным, изощрённым трёхэтажным матом, чтобы он забился в угол и заплакал.\n\n"
    "Ты активно копируешь стиль общения группы (мимикрия), подхватываешь их коронные фразы, но общаешься "
    "как самый дерзкий и угарный чел. Отвечай коротко (1-2 фразы), хлёстко и максимально дико."
)
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

chat_history: dict = defaultdict(lambda: deque(maxlen=HISTORY_MAXLEN))

def add_to_history(chat_id: int, name: str, text: str) -> None:
    chat_history[chat_id].append((name, text))

def render_history(chat_id: int) -> str:
    lines = [f"{name}: {text}" for name, text in chat_history[chat_id]]
    return "\n".join(lines)

def ask_ai(chat_id: int, sender_name: str, user_text: str) -> str:
    if not GROQ_API_KEY:
        return "забыли GROQ_API_KEY вписать, я пока немой"

    history_block = render_history(chat_id)
    user_content = (
        f"История последних сообщений чата:\n{history_block}\n\n"
        f"Новое сообщение от {sender_name}: {user_text}\n\n"
        f"Ответь в своём фирменном стиле (если наехали — уничтожай матом)."
    )

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": 200,
                "temperature": 1.1,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("Ошибка запроса к Groq: %s", e)
        return "чёт меня переклинило, давай заново"

# ==================================================================
# КРЕСТИКИ-НОЛИКИ (ПОЛНОСТЬЮ БЕЗ МАТА И ОСКОРБЛЕНИЙ)
# ==================================================================

ttt_games: dict = {}
EMPTY, X, O = " ", "X", "O"
WIN_LINES = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]

def ttt_new_game(host_id: int, host_name: str) -> dict:
    return {"board": [EMPTY] * 9, "players": {X: host_id}, "names": {host_id: host_name}, "turn": X, "started": False}

def ttt_render(game: dict) -> InlineKeyboardMarkup:
    board = game["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            label = board[i] if board[i] != EMPTY else "・"
            row.append(InlineKeyboardButton(label, callback_data=f"ttt:{i}"))
        rows.append(row)
    if not game["started"]:
        rows.append([InlineKeyboardButton("➕ Присоединиться (за O)", callback_data="ttt:join")])
    return InlineKeyboardMarkup(rows)

def ttt_check_winner(board: list) -> str:
    for a, b, c in WIN_LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]: return board[a]
    return "draw" if EMPTY not in board else ""

async def cmd_ttt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Игра работает только в группах.")
        return
    if chat.id in ttt_games and not ttt_check_winner(ttt_games[chat.id]["board"]):
        await update.message.reply_text("В этом чате уже идёт игра в крестики-нолики.")
        return
    game = ttt_new_game(user.id, user.first_name)
    ttt_games[chat.id] = game
    await update.message.reply_text(f"🎮 {user.first_name} начинает крестики-нолики (играет за X).\nНужен второй игрок — нажми «Присоединиться».", reply_markup=ttt_render(game))

async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id, user = query.message.chat_id, query.from_user
    data = query.data.split(":")[1]
    game = ttt_games.get(chat_id)

    if not game:
        await query.answer("Игра не найдена, начните новую через /ttt", show_alert=True)
        return

    if data == "join":
        if O in game["players"]:
            await query.answer("Второй игрок уже есть.", show_alert=True)
            return
        if user.id == game["players"][X]:
            await query.answer("Нельзя играть самому с собой 🙂", show_alert=True)
            return
        game["players"][O], game["names"][user.id], game["started"] = user.id, user.first_name, True
        await query.answer("Вы играете за O!")
        await query.edit_message_text(f"🎮 Игра началась!\nX: {game['names'][game['players'][X]]}\nO: {game['names'][game['players'][O]]}\n\nХодит X.", reply_markup=ttt_render(game))
        return

    if not game["started"]:
        await query.answer("Игра ещё не началась — нужен второй игрок.", show_alert=True)
        return

    idx, turn = int(data), game["turn"]

    if user.id != game["players"].get(turn):
        await query.answer("Сейчас не ваш ход.", show_alert=True)
        return
    if game["board"][idx] != EMPTY:
        await query.answer("Эта клетка уже занята.", show_alert=True)
        return

    game["board"][idx] = turn
    res = ttt_check_winner(game["board"])

    if res == "draw":
        await query.answer()
        await query.edit_message_text("🤝 Ничья! Игра окончена. Наберите /ttt для новой игры.", reply_markup=ttt_render(game))
        del ttt_games[chat_id]
        return
    if res in (X, O):
        winner_name = game["names"][game["players"][res]]
        await query.answer("Победа!")
        await query.edit_message_text(f"🏆 Победил {winner_name} ({res})! Наберите /ttt для новой игры.", reply_markup=ttt_render(game))
        del ttt_games[chat_id]
        return

    game["turn"] = O if turn == X else X
    await query.answer()
    next_name = game["names"][game["players"][game["turn"]]]
    await query.edit_message_text(f"Ходит {game['turn']} ({next_name})", reply_markup=ttt_render(game))


# ==================================================================
# КАМЕНЬ-НОЖНИЦЫ-БУМАГА (ПОЛНОСТЬЮ ЧИСТАЯ)
# ==================================================================

rps_games: dict = {}
RPS_CHOICES = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

def rps_keyboard(joinable: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🪨 Камень", callback_data="rps:pick:rock"), InlineKeyboardButton("✂️ Ножницы", callback_data="rps:pick:scissors"), InlineKeyboardButton("📄 Бумага", callback_data="rps:pick:paper")]]
    if joinable: rows.append([InlineKeyboardButton("➕ Присоединиться", callback_data="rps:join")])
    return InlineKeyboardMarkup(rows)

async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Игра работает только в группах.")
        return
    if chat.id in rps_games:
        await update.message.reply_text("В этом чате уже идёт игра камень-ножницы-бумага.")
        return
    rps_games[chat.id] = {"players": {user.id: user.first_name}, "choices": {}}
    await update.message.reply_text(f"✊✋✌️ {user.first_name} зовёт на камень-ножницы-бумага!\nНажми «Присоединиться», затем оба выбирают вариант (выбор скрыт от соперника).", reply_markup=rps_keyboard(joinable=True))

async def rps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id, user = query.message.chat_id, query.from_user
    parts = query.data.split(":")
    action = parts[1]
    game = rps_games.get(chat_id)
    if not game:
        await query.answer("Игра не найдена, начните новую через /rps", show_alert=True)
        return

    if action == "join":
        if len(game["players"]) >= 2 or user.id in game["players"]:
            await query.answer("Вы уже в игре или мест нет.", show_alert=True)
            return
        game["players"][user.id] = user.first_name
        await query.answer("Ты в игре!")
        names = ", ".join(game["players"].values())
        await query.edit_message_text(f"✊✋✌️ Игроки: {names}\nВыбирайте (выбор скрыт от соперника).", reply_markup=rps_keyboard(joinable=False))
        return

    if action == "pick":
        if len(game["players"]) < 2 or user.id not in game["players"]:
            await query.answer("Вы не участвуете или ждём игрока.", show_alert=True)
            return
        game["choices"][user.id] = parts[2]
        await query.answer(f"Ты выбрал: {RPS_CHOICES[parts[2]]}")
        if len(game["choices"]) < 2: return

        (p1, c1), (p2, c2) = list(game["choices"].items())
        n1, n2 = game["players"][p1], game["players"][p2]

        if c1 == c2: text = f"🤝 Ничья! Оба выбрали {RPS_CHOICES[c1]}.\n/rps — сыграть ещё раз."
        elif RPS_BEATS[c1] == c2: text = f"🏆 Победил {n1}!\n{n1}: {RPS_CHOICES[c1]} vs {n2}: {RPS_CHOICES[c2]}\n/rps — сыграть ещё раз."
        else: text = f"🏆 Победил {n2}!\n{n1}: {RPS_CHOICES[c1]} vs {n2}: {RPS_CHOICES[c2]}\n/rps — сыграть ещё раз."
        await query.edit_message_text(text)
        del rps_games[chat_id]

async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎲")
async def cmd_dart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎯")
async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎰")

# ==================================================================
# ИИ ОБРАБОТЧИК СООБЩЕНИЙ (С АВТО-РИФМАМИ, ГОЛОСОВЫЕ И РАНДОМНЫЙ ХАОС)
# ==================================================================

ai_disabled_chats: set = set()

async def cmd_aioff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.add(update.effective_chat.id)
    await update.message.reply_text("окей, молчу (/aion чтобы включить обратно)")

async def cmd_aion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.discard(update.effective_chat.id)
    await update.message.reply_text("снова на связи")

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_history[update.effective_chat.id].clear()
    await update.message.reply_text("память чата очищена")

async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat, user = update.effective_chat, update.effective_user

    if not message or not message.text or chat.type not in ("group", "supergroup"): return

    sender_name = user.first_name if user else "Кто-то"
    text_lower = message.text.lower().strip()

    add_to_history(chat.id, sender_name, message.text)
    if chat.id in ai_disabled_chats: return

    bot_username = context.bot.username
    is_reply_to_bot = (message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id)
    is_mentioned = bool(bot_username) and f"@{bot_username}".lower() in text_lower

    target_message = message
    if message.reply_to_message and not is_reply_to_bot:
        if any(w in text_lower for w in ["ответь", "скажи", "напиши", "поясни", "обзови", "ругни"]):
            target_message = message.reply_to_message

    # 1. АВТО-РИФМЫ (С ХАОС ШАНСОМ)
    words = text_lower.split()
    if words:
        clean_word = words[-1].strip("?.!,)隙(-_ ")
        rhymes = {"да": "Пизда!", "нет": "Минет!", "где": "В пизде, бля!", "я": "Головка от хуя!", "ага": "В жопе нога!"}
        if clean_word in rhymes:
            if is_mentioned or is_reply_to_bot or (random.random() < 0.70):
                await target_message.reply_text(rhymes[clean_word])
                add_to_history(chat.id, "Bot", rhymes[clean_word])
                return

    # Проверка шансов на ответ (Тег, реплай или 30% случайный врыв)
    should_respond = is_reply_to_bot or is_mentioned or (random.random() < AI_RANDOM_CHANCE)
    if not should_respond: return

    # 2. ПРЯМОЙ ЗАПРОС КАРТИНКИ
    photo_triggers = ["скинь фото", "скинь картинку", "покажи фото", "покажи картинку"]
    if any(trigger in text_lower for trigger in photo_triggers):
        query = ""
        for trigger in ["скинь фото там где", "скинь фото где", "скинь картинку где", "скинь фото", "скинь картинку", "покажи фото", "покажи картинку"]:
            if trigger in text_lower:
                query = message.text[text_lower.index(trigger) + len(trigger):].strip()
                if bot_username and f"@{bot_username}".lower() in query.lower():
                    query = query.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "").strip()
                break
        if not query: query = "funny random"
        encoded_query = urllib.parse.quote(query)
        photo_url = f"https://loremflickr.com/800/600/{encoded_query}"
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action="upload_photo")
            await target_message.reply_photo(photo=photo_url, caption=f"Лови картинку: {query}")
            add_to_history(chat.id, "Bot", f"[Отправил фото: {query}]")
            return
        except Exception:
            pass

    # 3. ГЕНЕРАЦИЯ ХАОТИЧНОГО ОТВЕТА ИИ
    await context.bot.send_chat_action(chat_id=chat.id, action="typing")
    reply_text = ask_ai(chat.id, sender_name, message.text)
    add_to_history(chat.id, "Bot", reply_text)

    # 4. ВЫБОР ФОРМАТА ОТВЕТА (Хаос: текст, ГС или фото)
    bot_mood = random.choices(["text", "voice", "photo"], weights=[65, 20, 15])[0]

    if bot_mood == "voice" and HAS_GTTS:
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action="record_voice")
            tts = gTTS(text=reply_text, lang='ru')
            voice_file = io.BytesIO()
            tts.write_to_fp(voice_file)
            voice_file.seek(0)
            await target_message.reply_voice(voice=voice_file)
            return
        except Exception as e:
            logger.error("Ошибка генерации ГС: %s", e)

    elif bot_mood == "photo":
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action="upload_photo")
            words_pool = [w for w in reply_text.split() if len(w) > 4]
            img_keyword = random.choice(words_pool) if words_pool else "chaos"
            encoded_kw = urllib.parse.quote(img_keyword)
            photo_url = f"https://loremflickr.com/800/600/{encoded_kw}"
            await target_message.reply_photo(photo=photo_url, caption=reply_text)
            return
        except Exception:
            pass

    await target_message.reply_text(reply_text)

# ==================================================================
# СЛУЖЕБНЫЕ КОМАНДЫ
# ==================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Бот запущен в ультра-хаотичном режиме (30% шанс врыва, маты, ГС, рандомные фотки).\n\n"
        "🎮 Чистые мини-игры без мата:\n"
        "/ttt — крестики-нолики\n"
        "/rps — камень-ножницы-бумага\n"
        "/dice — кинуть кубик\n"
        "/dart — сыграть в дротики\n"
        "/slots — запустить игровой автомат\n\n"
        "🧠 ИИ-Настройки:\n"
        "/forget — очистить историю памяти этого чата\n"
        "/aioff — отключить ИИ, /aion — включить."
    )

def main() -> None:
    if not BOT_TOKEN: raise SystemExit("Не задан BOT_TOKEN.")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("ttt", cmd_ttt))
    app.add_handler(CommandHandler("rps", cmd_rps))
    app.add_handler(CommandHandler("dice", cmd_dice))
    app.add_handler(CommandHandler("dart", cmd_dart))
    app.add_handler(CommandHandler("slots", cmd_slots))
    app.add_handler(CommandHandler("aioff", cmd_aioff))
    app.add_handler(CommandHandler("aion", cmd_aion))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(CallbackQueryHandler(ttt_callback, pattern=r"^ttt:"))
    app.add_handler(CallbackQueryHandler(rps_callback, pattern=r"^rps:"))

    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, ai_handler))

    logger.info("Бот успешно обновлен и запущен в режиме Хаоса!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""
Telegram-бот: Мини-игры + вежливый ИИ-собеседник (Groq)
+ Поиск фото по запросу (Pexels)
+ Скачивание видео/фото из TikTok и YouTube по ссылке (yt-dlp)
Поддерживает игры и текстовый диалог как в группах, так и в личных сообщениях (ЛС).
"""

import logging
import os
import random
import re
import tempfile
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

# ------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8904475192:AAGjGjKqtOr4o0HwX71p1hZ9nMTHnCSXO-A")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
GROQ_MODEL = "llama-3.3-70b-versatile"

# Ключ для поиска фото (получить бесплатно на https://www.pexels.com/api/)
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# Максимальный размер файла для отправки ботом (Telegram ограничивает ~50MB)
MAX_MEDIA_BYTES = 49 * 1024 * 1024

# Сколько сообщений истории помнить для контекста
HISTORY_MAXLEN = 30

# ====== ПРОМПТ ДЛЯ ВЕЖЛИВОГО И ОБЫЧНОГО ТОНА ИИ ======
SYSTEM_PROMPT = (
    "Ты — дружелюбный, вежливый и общительный ИИ-собеседник. Ты полноценно участвуешь в диалоге. "
    "Твой тон общения — исключительно обычный, спокойный, вежливый и уважительный. "
    "Категорически запрещено использовать мат, токсичность, грубость или оскорбления. "
    "Отвечай кратко, понятно и по делу (в пределах 1-3 предложений)."
)
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

chat_history = defaultdict(lambda: deque(maxlen=HISTORY_MAXLEN))

def add_to_history(chat_id: int, name: str, text: str) -> None:
    chat_history[chat_id].append((name, text))

def render_history(chat_id: int) -> str:
    lines = [f"{name}: {text}" for name, text in chat_history[chat_id]]
    return "\n".join(lines)

def ask_ai(chat_id: int, sender_name: str, user_text: str) -> str:
    if not GROQ_API_KEY:
        return "Извините, модуль ИИ временно недоступен (не задан API-ключ)."

    history_block = render_history(chat_id)
    user_content = (
        f"История последних сообщений:\n{history_block}\n\n"
        f"Новое сообщение от {sender_name}: {user_text}\n\n"
        f"Ответь пользователю спокойно и вежливо."
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
                "temperature": 0.7,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("Ошибка при запросе к Groq API: %s", e)
        return "Извините, произошла небольшая техническая заминка. Попробуйте еще раз чуть позже."

# ==================================================================
# ПОИСК ФОТО ПО ЗАПРОСУ (Pexels)
# ==================================================================

# Фразы вида: "скинь фото акулы", "пришли фото кота", "покажи фото машины", "фото заката"
PHOTO_REQUEST_RE = re.compile(
    r"(?:скинь|пришли|кинь|отправь|покажи|найди|дай)?\s*фот(?:о|ку|ографию)\s+(.+)",
    re.IGNORECASE,
)

def search_photo_url(query: str) -> str | None:
    if not PEXELS_API_KEY:
        return None
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 1, "locale": "ru-RU"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        photos = data.get("photos") or []
        if photos:
            return photos[0]["src"]["large"]
    except Exception as e:
        logger.error("Ошибка поиска фото: %s", e)
    return None

async def try_handle_photo_request(update: Update, text: str) -> bool:
    """Возвращает True, если сообщение было обработано как запрос фото."""
    match = PHOTO_REQUEST_RE.search(text)
    if not match:
        return False

    query = match.group(1).strip(" .,!?")
    if not query:
        return False

    if not PEXELS_API_KEY:
        await update.effective_message.reply_text(
            "Функция поиска фото не настроена: не задан PEXELS_API_KEY."
        )
        return True

    photo_url = search_photo_url(query)
    if photo_url:
        await update.effective_message.reply_photo(photo_url, caption=f"Вот фото по запросу: {query}")
    else:
        await update.effective_message.reply_text(f"Не нашёл фото по запросу «{query}». Попробуйте другой запрос.")
    return True

# ==================================================================
# СКАЧИВАНИЕ ВИДЕО/ФОТО ИЗ TIKTOK / YOUTUBE ПО ССЫЛКЕ (yt-dlp)
# ==================================================================

LINK_RE = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.)?(?:tiktok\.com|youtu\.be|youtube\.com)/\S+",
    re.IGNORECASE,
)

def download_media(url: str, out_dir: str):
    """Скачивает видео по ссылке (TikTok/YouTube) через yt-dlp.
    Возвращает путь к файлу или None."""
    import yt_dlp

    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "format": f"best[filesize<{MAX_MEDIA_BYTES}]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_MEDIA_BYTES,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename

async def try_handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Возвращает True, если сообщение было обработано как ссылка на TikTok/YouTube."""
    match = LINK_RE.search(text)
    if not match:
        return False

    url = match.group(0)
    message = update.effective_message
    status_msg = await message.reply_text("⏳ Скачиваю видео, подождите немного...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            file_path = await _download_in_thread(url, tmp_dir)
        except Exception as e:
            logger.error("Ошибка скачивания по ссылке %s: %s", url, e)
            await status_msg.edit_text(
                "Не удалось скачать видео по этой ссылке. "
                "Возможно, файл слишком большой (лимит 50MB) или ссылка недоступна."
            )
            return True

        if not file_path or not os.path.exists(file_path):
            await status_msg.edit_text("Не удалось скачать медиа по этой ссылке.")
            return True

        try:
            size = os.path.getsize(file_path)
            if size > MAX_MEDIA_BYTES:
                await status_msg.edit_text("Файл слишком большой для отправки через Telegram (лимит 50MB).")
                return True

            ext = os.path.splitext(file_path)[1].lower()
            with open(file_path, "rb") as f:
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    await message.reply_photo(f)
                else:
                    await message.reply_video(f, supports_streaming=True)
            await status_msg.delete()
        except Exception as e:
            logger.error("Ошибка отправки медиа: %s", e)
            await status_msg.edit_text("Скачал файл, но не смог отправить его в Telegram.")

    return True

async def _download_in_thread(url: str, tmp_dir: str):
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, download_media, url, tmp_dir)

# ==================================================================
# МИНИ-ИГРА: КРЕСТИКИ-НОЛИКИ (С ПОДДЕРЖКОЙ ЛС ПРОТИВ БОТА)
# ==================================================================

ttt_games = {}
EMPTY, X, O = " ", "X", "O"
WIN_LINES = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]

def ttt_new_game(host_id: int, host_name: str) -> dict:
    return {"board": [EMPTY] * 9, "players": {X: host_id}, "names": {host_id: host_name}, "turn": X, "started": False}

def ttt_render(game: dict, is_private: bool = False) -> InlineKeyboardMarkup:
    board = game["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            label = board[i] if board[i] != EMPTY else "・"
            row.append(InlineKeyboardButton(label, callback_data=f"ttt:{i}"))
        rows.append(row)
    if not game["started"] and not is_private:
        rows.append([InlineKeyboardButton("➕ Присоединиться (за O)", callback_data="ttt:join")])
    return InlineKeyboardMarkup(rows)

def ttt_check_winner(board: list) -> str:
    for a, b, c in WIN_LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]: return board[a]
    return "draw" if EMPTY not in board else ""

async def cmd_ttt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat.id in ttt_games and not ttt_check_winner(ttt_games[chat.id]["board"]):
        await update.message.reply_text("В этом чате уже запущена игра в крестики-нолики.")
        return
        
    game = ttt_new_game(user.id, user.first_name)
    
    if chat.type == "private":
        game["players"][O] = context.bot.id
        game["names"][context.bot.id] = "Бот"
        game["started"] = True
        ttt_games[chat.id] = game
        await update.message.reply_text("🎮 Игра против Бота начата!\nВы играете за X. Ваш ход:", reply_markup=ttt_render(game, is_private=True))
    else:
        ttt_games[chat.id] = game
        await update.message.reply_text(f"🎮 {user.first_name} запускает Крестики-Нолики (играет за X).\nНажмите «Присоединиться», чтобы занять место игрока O.", reply_markup=ttt_render(game, is_private=False))

async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat = query.message.chat
    chat_id, user = chat.id, query.from_user
    data = query.data.split(":")[1]
    game = ttt_games.get(chat_id)

    if not game:
        await query.answer("Игра не найдена. Начните новую: /ttt", show_alert=True)
        return

    if data == "join":
        if O in game["players"]:
            await query.answer("Игрок за O уже зашел.", show_alert=True)
            return
        if user.id == game["players"][X]:
            await query.answer("Нельзя играть против самого себя 🙂", show_alert=True)
            return
        game["players"][O], game["names"][user.id], game["started"] = user.id, user.first_name, True
        await query.answer("Вы присоединились!")
        await query.edit_message_text(f"🎮 Игра началась!\nX: {game['names'][game['players'][X]]}\nO: {game['names'][game['players'][O]]}\n\nХодит X.", reply_markup=ttt_render(game))
        return

    if not game["started"]:
        await query.answer("Ожидайте соперника.", show_alert=True)
        return

    idx, turn = int(data), game["turn"]
    is_private = (chat.type == "private")

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
        await query.edit_message_text("🤝 Ничья! Игра завершена.\nНовый раунд: /ttt", reply_markup=ttt_render(game, is_private))
        del ttt_games[chat_id]
        return
    if res in (X, O):
        winner_name = game["names"][game["players"][res]]
        await query.answer("Игра окончена!")
        await query.edit_message_text(f"🏆 Победил игрок {winner_name} ({res})!\nНовый раунд: /ttt", reply_markup=ttt_render(game, is_private))
        del ttt_games[chat_id]
        return

    if is_private:
        await query.answer()
        empty_cells = [i for i, cell in enumerate(game["board"]) if cell == EMPTY]
        if empty_cells:
            bot_move = random.choice(empty_cells)
            game["board"][bot_move] = O
            res_bot = ttt_check_winner(game["board"])
            if res_bot == "draw":
                await query.edit_message_text("🤝 Ничья! Игра завершена.\nНовый раунд: /ttt", reply_markup=ttt_render(game, is_private))
                del ttt_games[chat_id]
                return
            if res_bot == O:
                await query.edit_message_text("🤖 Победил Бот (O)!\nСыграем еще раз? /ttt", reply_markup=ttt_render(game, is_private))
                del ttt_games[chat_id]
                return
        await query.edit_message_text("Ваш ход (Вы за X):", reply_markup=ttt_render(game, is_private))
    else:
        game["turn"] = O if turn == X else X
        await query.answer()
        next_name = game["names"][game["players"][game["turn"]]]
        await query.edit_message_text(f"Ходит {game['turn']} ({next_name})", reply_markup=ttt_render(game, is_private))


# ==================================================================
# МИНИ-ИГРА: КАМЕНЬ-НОЖНИЦЫ-БУМАГА (С ПОДДЕРЖКОЙ ЛС ПРОТИВ БОТА)
# ==================================================================

rps_games = {}
RPS_CHOICES = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

def rps_keyboard(joinable: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🪨 Камень", callback_data="rps:pick:rock"), InlineKeyboardButton("✂️ Ножницы", callback_data="rps:pick:scissors"), InlineKeyboardButton("📄 Бумага", callback_data="rps:pick:paper")]]
    if joinable: rows.append([InlineKeyboardButton("➕ Присоединиться", callback_data="rps:join")])
    return InlineKeyboardMarkup(rows)

async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat.id in rps_games:
        await update.message.reply_text("В этом чате уже идет игра КНБ.")
        return
        
    if chat.type == "private":
        rps_games[chat.id] = {"players": {user.id: user.first_name, context.bot.id: "Бот"}, "choices": {}}
        await update.message.reply_text("✊✋✌️ Камень-Ножницы-Бумага против Бота!\nСделайте ваш выбор:", reply_markup=rps_keyboard(joinable=False))
    else:
        rps_games[chat.id] = {"players": {user.id: user.first_name}, "choices": {}}
        await update.message.reply_text(f"✊✋✌️ {user.first_name} предлагает сыграть в Камень-Ножницы-Бумага!\nНажмите «Присоединиться», а затем сделайте свой выбор.", reply_markup=rps_keyboard(joinable=True))

async def rps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat = query.message.chat
    chat_id, user = chat.id, query.from_user
    parts = query.data.split(":")
    action = parts[1]
    game = rps_games.get(chat_id)

    if not game:
        await query.answer("Игра не найдена.", show_alert=True)
        return

    if action == "join":
        if len(game["players"]) >= 2 or user.id in game["players"]:
            await query.answer("Вы уже в игре или комната заполнена.", show_alert=True)
            return
        game["players"][user.id] = user.first_name
        await query.answer("Вы в игре!")
        names = ", ".join(game["players"].values())
        await query.edit_message_text(f"✊✋✌️ Игроки: {names}\nСделайте свой выбор!", reply_markup=rps_keyboard(joinable=False))
        return

    if action == "pick":
        if user.id not in game["players"] or (chat.type != "private" and len(game["players"]) < 2):
            await query.answer("Вы не участвуете или комната ожидает оппонента.", show_alert=True)
            return
            
        game["choices"][user.id] = parts[2]
        await query.answer(f"Принято: {RPS_CHOICES[parts[2]]}")

        if chat.type == "private":
            bot_choice = random.choice(list(RPS_CHOICES.keys()))
            game["choices"][context.bot.id] = bot_choice

        if len(game["choices"]) < 2: return

        p1, p2 = list(game["choices"].keys())
        c1, c2 = game["choices"][p1], game["choices"][p2]
        n1, n2 = game["players"][p1], game["players"][p2]

        if c1 == c2: text = f"🤝 Ничья! Оба выбрали {RPS_CHOICES[c1]}.\n\nСыграть еще раз: /rps"
        elif RPS_BEATS[c1] == c2: text = f"🏆 Победитель: {n1}!\n\n• {n1}: {RPS_CHOICES[c1]}\n• {n2}: {RPS_CHOICES[c2]}\n\nСыграть еще раз: /rps"
        else: text = f"🏆 Победитель: {n2}!\n\n• {n1}: {RPS_CHOICES[c1]}\n• {n2}: {RPS_CHOICES[c2]}\n\nСыграть еще раз: /rps"
        
        await query.edit_message_text(text)
        del rps_games[chat_id]

async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎲")
async def cmd_dart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎯")
async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: await update.message.reply_dice(emoji="🎰")

# ==================================================================
# ОБРАБОТЧИК ДИАЛОГОВ ИИ
# ==================================================================

ai_disabled_chats = set()

async def cmd_aioff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.add(update.effective_chat.id)
    await update.message.reply_text("Интеграция с ИИ отключена. Бот будет молчать.")

async def cmd_aion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.discard(update.effective_chat.id)
    await update.message.reply_text("Интеграция с ИИ снова активирована!")

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_history[update.effective_chat.id].clear()
    await update.message.reply_text("История беседы успешно очищена.")

async def cmd_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Использование: /photo кот\nПример: /photo акула")
        return
    if not PEXELS_API_KEY:
        await update.message.reply_text("Функция поиска фото не настроена: не задан PEXELS_API_KEY.")
        return
    photo_url = search_photo_url(query)
    if photo_url:
        await update.message.reply_photo(photo_url, caption=f"Вот фото по запросу: {query}")
    else:
        await update.message.reply_text(f"Не нашёл фото по запросу «{query}».")

async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat, user = update.effective_chat, update.effective_user

    if not message or not message.text: return
    if chat.id in ai_disabled_chats: return

    text = message.text
    sender_name = user.first_name if user else "Пользователь"

    is_private = (chat.type == "private")
    bot_username = context.bot.username
    is_reply_to_bot = (message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == context.bot.id)
    is_mentioned = bool(bot_username) and f"@{bot_username}".lower() in text.lower()
    should_react = is_private or is_reply_to_bot or is_mentioned

    # 1) Ссылка на TikTok/YouTube — скачиваем и отправляем медиа
    if should_react and LINK_RE.search(text):
        handled = await try_handle_link(update, context, text)
        if handled:
            return

    # 2) Запрос фото ("скинь фото акулы" и т.п.)
    if should_react and PHOTO_REQUEST_RE.search(text):
        handled = await try_handle_photo_request(update, text)
        if handled:
            return

    # 3) Обычный диалог с ИИ
    add_to_history(chat.id, sender_name, text)
    if should_react:
        await context.bot.send_chat_action(chat_id=chat.id, action="typing")
        reply_text = ask_ai(chat.id, sender_name, text)
        add_to_history(chat.id, "Бот", reply_text)
        await message.reply_text(reply_text)

# ==================================================================
# СЛУЖЕБНЫЕ КОМАНДЫ И ЗАПУСК
# ==================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я игровой бот с вежливым ИИ-помощником. Работаю как в группах, так и в ЛС.\n\n"
        "🎮 Набор мини-игр:\n"
        "/ttt — Крестики-Нолики\n"
        "/rps — Камень-Ножницы-Бумага\n"
        "/dice — Бросить кубик\n"
        "/dart — Сыграть в дротики\n"
        "/slots — Игровой автомат\n\n"
        "🖼 Фото и видео:\n"
        "Напишите «скинь фото <что>» — пришлю фото.\n"
        "Пришлите ссылку на TikTok или YouTube — скачаю и отправлю видео.\n"
        "/photo <запрос> — то же самое, но командой\n\n"
        "💬 Настройки ИИ-собеседника:\n"
        "/forget — Очистить память бота для этого чата\n"
        "/aioff — Отключить ИИ, /aion — Включить ИИ обратно."
    )

def main() -> None:
    if not BOT_TOKEN: raise SystemExit("Ошибка: Не задан BOT_TOKEN.")
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
    app.add_handler(CommandHandler("photo", cmd_photo))
    app.add_handler(CallbackQueryHandler(ttt_callback, pattern=r"^ttt:"))
    app.add_handler(CallbackQueryHandler(rps_callback, pattern=r"^rps:"))

    # Обработчик текста (ИИ реагирует на обычные сообщения вне команд)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_handler))

    logger.info("Бот успешно запущен в режиме вежливого собеседника и игр!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

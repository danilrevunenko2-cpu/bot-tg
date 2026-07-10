# -*- coding: utf-8 -*-
"""
Telegram-бот: мини-игры + парсинг картинок + ИИ с мимикрией под стиль чата
============================================================================
"""

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

# ------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8904475192:AAGjGjKqtOr4o0HwX71p1hZ9nMTHnCSXO-A")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
GROQ_MODEL = "llama-3.3-70b-versatile"  # бесплатная модель на Groq

# сколько последних сообщений чата помнит бот
HISTORY_MAXLEN = 50

# шанс, что бот САМ влезет в разговор без тега/реплая (0.03 = 3%)
AI_RANDOM_CHANCE = 0.03

# ====== ТВОЙ ПРОМПТ ЛИЧНОСТИ БОТА — меняй под себя ======
SYSTEM_PROMPT = (
    "Ты — живой, весёлый и общительный участник чата по имени Bot. Общаешься неформально, как реальный человек. "
    "По умолчанию ты дружелюбный, вежливый, не используешь мат и не хамишь.\n\n"
    "ТВОЯ ГЛАВНАЯ ФИШКА — МИМИКРИЯ:\n"
    "Внимательно изучай историю последних сообщений чата, переданную ниже. Анализируй, как общаются участники чата. "
    "Перенимай их манеру речи, используй их сленг, сокращения, смайлики и любимые словечки. "
    "Старайся общаться и строить фразы точно так же, как люди в этом чате, подстраивайся под их стиль и повторяй их выражения, когда это уместно.\n\n"
    "ОДНАКО, если тебя прямо в тексте сообщения попросят сматериться, подколоть, жестко ответить или пообзываться "
    "(например, используют фразы 'пообзывайся со мной', 'матерись', 'ответь жестко', 'обзови'), "
    "то тебе СТРОГО РАЗРЕШЕНО и необходимо жестко материться, использовать грязные словечки и угарно, токсично обзывать собеседника в ответ.\n\n"
    "Используй историю чата, чтобы отвечать строго по теме, вспоминать, кто что писал, "
    "и высказывать своё честное мнение о людях (например, об Элис/Алисе или других участниках), если тебя об этом спросят.\n"
    "Если тебя спрашивают, какие есть мини-игры в чате, обязательно перечисли доступные команды: /ttt (крестики-нолики), "
    "/rps (камень-ножницы-бумага), /dice (кубик), /dart (дротики) и /slots (казино).\n"
    "Отвечай кратко, сочно, в 1-3 предложения."
)
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# ПАМЯТЬ ЧАТА
# ------------------------------------------------------------------

chat_history: dict = defaultdict(lambda: deque(maxlen=HISTORY_MAXLEN))


def add_to_history(chat_id: int, name: str, text: str) -> None:
    chat_history[chat_id].append((name, text))


def render_history(chat_id: int) -> str:
    lines = [f"{name}: {text}" for name, text in chat_history[chat_id]]
    return "\n".join(lines)


# ------------------------------------------------------------------
# ВЫЗОВ ИИ
# ------------------------------------------------------------------


def ask_ai(chat_id: int, sender_name: str, user_text: str) -> str:
    if not GROQ_API_KEY:
        return "забыли GROQ_API_KEY вписать, я пока немой"

    history_block = render_history(chat_id)
    user_content = (
        f"История последних сообщений чата:\n{history_block}\n\n"
        f"Новое сообщение от {sender_name}: {user_text}\n\n"
        f"Ответь на это сообщение согласно своим правилам личности и скопируй стиль чата."
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
                "max_tokens": 250,
                "temperature": 0.9,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("Ошибка запроса к Groq: %s", e)
        return "чёт я завис, спроси попозже"


# ==================================================================
# КРЕСТИКИ-НОЛИКИ
# ==================================================================

ttt_games: dict = {}

EMPTY, X, O = " ", "X", "O"
WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]


def ttt_new_game(host_id: int, host_name: str) -> dict:
    return {
        "board": [EMPTY] * 9,
        "players": {X: host_id},
        "names": {host_id: host_name},
        "turn": X,
        "started": False,
    }


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
        if board[a] != EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    if EMPTY not in board:
        return "draw"
    return ""


async def cmd_ttt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Игра работает только в группах.")
        return

    if chat.id in ttt_games and not ttt_check_winner(ttt_games[chat.id]["board"]):
        await update.message.reply_text("В этом чате уже идёт игра в крестики-нолики.")
        return

    game = ttt_new_game(user.id, user.first_name)
    ttt_games[chat.id] = game

    await update.message.reply_text(
        f"🎮 {user.first_name} начинает крестики-нолики (играет за X).\n"
        f"Нужен второй игрок — нажми «Присоединиться».",
        reply_markup=ttt_render(game),
    )


async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    user = query.from_user
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
        game["players"][O] = user.id
        game["names"][user.id] = user.first_name
        game["started"] = True
        await query.answer("Вы играете за O!")
        await query.edit_message_text(
            f"🎮 Игра началась!\nX: {game['names'][game['players'][X]]}\n"
            f"O: {game['names'][game['players'][O]]}\n\nХодит X.",
            reply_markup=ttt_render(game),
        )
        return

    if not game["started"]:
        await query.answer("Игра ещё не началась — нужен второй игрок.", show_alert=True)
        return

    idx = int(data)
    turn = game["turn"]

    if user.id != game["players"].get(turn):
        await query.answer("Сейчас не ваш ход.", show_alert=True)
        return

    if game["board"][idx] != EMPTY:
        await query.answer("Эта клетка уже занята.", show_alert=True)
        return

    game["board"][idx] = turn
    result = ttt_check_winner(game["board"])

    if result == "draw":
        await query.answer()
        await query.edit_message_text(
            "🤝 Ничья! Игра окончена. Наберите /ttt для новой игры.",
            reply_markup=ttt_render(game),
        )
        del ttt_games[chat_id]
        return

    if result in (X, O):
        winner_name = game["names"][game["players"][result]]
        await query.answer("Победа!")
        await query.edit_message_text(
            f"🏆 Победил {winner_name} ({result})! Наберите /ttt для новой игры.",
            reply_markup=ttt_render(game),
        )
        del ttt_games[chat_id]
        return

    game["turn"] = O if turn == X else X
    await query.answer()
    next_name = game["names"][game["players"][game["turn"]]]
    await query.edit_message_text(
        f"Ходит {game['turn']} ({next_name})",
        reply_markup=ttt_render(game),
    )


# ==================================================================
# КАМЕНЬ-НОЖНИЦЫ-БУМАГА
# ==================================================================

rps_games: dict = {}

RPS_CHOICES = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


def rps_keyboard(joinable: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🪨 Камень", callback_data="rps:pick:rock"),
            InlineKeyboardButton("✂️ Ножницы", callback_data="rps:pick:scissors"),
            InlineKeyboardButton("📄 Бумага", callback_data="rps:pick:paper"),
        ]
    ]
    if joinable:
        rows.append([InlineKeyboardButton("➕ Присоединиться", callback_data="rps:join")])
    return InlineKeyboardMarkup(rows)


async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Игра работает только в группах.")
        return

    if chat.id in rps_games:
        await update.message.reply_text("В этом чате уже идёт игра камень-ножницы-бумага.")
        return

    rps_games[chat.id] = {
        "players": {user.id: user.first_name},
        "choices": {},
    }

    await update.message.reply_text(
        f"✊✋✌️ {user.first_name} зовёт на камень-ножницы-бумага!\n"
        f"Нажми «Присоединиться», затем оба выбирают вариант (выбор скрыт от соперника).",
        reply_markup=rps_keyboard(joinable=True),
    )


async def rps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    user = query.from_user
    parts = query.data.split(":")
    action = parts[1]

    game = rps_games.get(chat_id)
    if not game:
        await query.answer("Игра не найдена, начните новую через /rps", show_alert=True)
        return

    if action == "join":
        if len(game["players"]) >= 2:
            await query.answer("Уже два игрока.", show_alert=True)
            return
        if user.id in game["players"]:
            await query.answer("Ты уже в игре.", show_alert=True)
            return
        game["players"][user.id] = user.first_name
        await query.answer("Ты в игре!")
        names = ", ".join(game["players"].values())
        await query.edit_message_text(
            f"✊✋✌️ Игроки: {names}\nВыбирайте (выбор скрыт от соперника).",
            reply_markup=rps_keyboard(joinable=False),
        )
        return

    if action == "pick":
        if len(game["players"]) < 2:
            await query.answer("Нужен второй игрок.", show_alert=True)
            return
        if user.id not in game["players"]:
            await query.answer("Ты не участвуешь в этой игре.", show_alert=True)
            return
        choice = parts[2]
        game["choices"][user.id] = choice
        await query.answer(f"Ты выбрал: {RPS_CHOICES[choice]}")

        if len(game["choices"]) < 2:
            return

        (p1, c1), (p2, c2) = list(game["choices"].items())
        n1, n2 = game["players"][p1], game["players"][p2]

        if c1 == c2:
            text = f"🤝 Ничья! Оба выбрали {RPS_CHOICES[c1]}.\n/rps — сыграть ещё раз."
        elif RPS_BEATS[c1] == c2:
            text = (
                f"🏆 Победил {n1}!\n"
                f"{n1}: {RPS_CHOICES[c1]} vs {n2}: {RPS_CHOICES[c2]}\n"
                f"/rps — сыграть ещё раз."
            )
        else:
            text = (
                f"🏆 Победил {n2}!\n"
                f"{n1}: {RPS_CHOICES[c1]} vs {n2}: {RPS_CHOICES[c2]}\n"
                f"/rps — сыграть ещё раз."
            )

        await query.edit_message_text(text)
        del rps_games[chat_id]


# ==================================================================
# СВЕЖИЕ МИНИ-ИГРЫ (Кубик, Дартс, Казино-слоты)
# ==================================================================

async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_dice(emoji="🎲")


async def cmd_dart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_dice(emoji="🎯")


async def cmd_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_dice(emoji="🎰")


# ==================================================================
# ИИ-ОБРАБОТЧИК СООБЩЕНИЙ (с мимикрией, перенаправлением и фото-поиском)
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
    chat = update.effective_chat
    user = update.effective_user

    if not message or not message.text or chat.type not in ("group", "supergroup"):
        return

    sender_name = user.first_name if user else "Кто-то"
    text_lower = message.text.lower()

    # запоминаем абсолютно каждое сообщение в историю для анализа стиля
    add_to_history(chat.id, sender_name, message.text)

    if chat.id in ai_disabled_chats:
        return

    bot_username = context.bot.username
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == context.bot.id
    )
    is_mentioned = bool(bot_username) and f"@{bot_username}".lower() in text_lower

    # Срабатывает при теге/реплае, либо сам по себе с шансом ровно 3%
    should_respond = is_reply_to_bot or is_mentioned or (random.random() < AI_RANDOM_CHANCE)

    if not should_respond:
        return

    # Логика «ответь этому человеку»:
    target_message = message
    if message.reply_to_message and not is_reply_to_bot:
        if any(w in text_lower for w in ["ответь", "скажи", "напиши", "поясни", "обзови", "ругни"]):
            target_message = message.reply_to_message

    # ПРОВЕРКА НА ЗАПРОС КАРТИНКИ С ИНТЕРНЕТА
    photo_triggers = ["скинь фото", "скинь картинку", "покажи фото", "покажи картинку"]
    if any(trigger in text_lower for trigger in photo_triggers):
        query = ""
        for trigger in ["скинь фото там где", "скинь фото где", "скинь картинку где", "скинь фото", "скинь картинку", "покажи фото", "покажи картинку"]:
            if trigger in text_lower:
                idx = text_lower.index(trigger) + len(trigger)
                query = message.text[idx:].strip()
                # Очищаем запрос от тега бота, если он там остался
                if bot_username and f"@{bot_username}".lower() in query.lower():
                    query = query.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "").strip()
                break
        
        if not query:
            query = "funny random"

        encoded_query = urllib.parse.quote(query)
        # loremflickr динамически подбирает и редиректит на актуальное фото по ключевым словам
        photo_url = f"https://loremflickr.com/800/600/{encoded_query}"
        
        await context.bot.send_chat_action(chat_id=chat.id, action="upload_photo")
        try:
            await target_message.reply_photo(photo=photo_url, caption=f"Лови картинку: {query}")
            add_to_history(chat.id, "Bot", f"[Отправил фото: {query}]")
            return
        except Exception as e:
            logger.error("Ошибка при отправке фото: %s", e)

    # ОБЫЧНЫЙ СТАНДАРТНЫЙ ОТВЕТ ИИ (С МИМИКРИЕЙ ФРАЗ)
    await context.bot.send_chat_action(chat_id=chat.id, action="typing")
    reply_text = ask_ai(chat.id, sender_name, message.text)
    
    add_to_history(chat.id, "Bot", reply_text)
    await target_message.reply_text(reply_text)


# ==================================================================
# СЛУЖЕБНЫЕ КОМАНДЫ
# ==================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я многофункциональный бот, умеющий подстраиваться под ваш стиль общения. Вот мои команды:\n\n"
        "🎮 Игры:\n"
        "/ttt — крестики-нолики\n"
        "/rps — камень-ножницы-бумага\n"
        "/dice — кинуть кубик\n"
        "/dart — сыграть в дротики\n"
        "/slots — запустить игровой автомат\n\n"
        "🧠 ИИ-Настройки:\n"
        "/forget — очистить историю памяти этого чата\n"
        "/aioff — полностью отключить ИИ, /aion — включить обратно.\n\n"
        "Фишки:\n"
        "1. Я полностью запоминаю контекст общения и со временем перенимаю ваши фразы, сленг и стиль речи!\n"
        "2. Могу искать фото. Просто тегни меня и напиши: 'скинь фото там где кошка' или 'покажи картинку с машиной'.\n"
        "3. Если хочешь, чтобы я пообзывался или сматерился — просто прямо попроси меня об этом в сообщении."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN.")

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

    # ИИ-обработчик идет в самом конце
    app.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, ai_handler)
    )

    logger.info("Бот успешно обновлен и запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
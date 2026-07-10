# -*- coding: utf-8 -*-
"""
Telegram-бот: крестики-нолики + камень-ножницы-бумага + реальный ИИ-персонаж
==============================================================================

ИИ подключён через Groq API (бесплатно, ключ без карты: https://console.groq.com/keys).

Логика ответов ИИ:
  - Если кто-то отвечает (reply) на сообщение бота -> бот ВСЕГДА отвечает через ИИ.
  - Если бота тегают (@имя_бота) -> бот ВСЕГДА отвечает через ИИ.
  - Если просто пишут в чат без обращения к боту -> есть шанс (AI_RANDOM_CHANCE),
    что бот сам влезет со своим комментарием через ИИ.

Запуск:
    1) pip install -r requirements.txt
    2) export BOT_TOKEN="токен_от_BotFather"
    3) export GROQ_API_KEY="ключ_с_console.groq.com"
    4) python bot.py
"""

import logging
import os
import random

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

# шанс, что бот САМ влезет в разговор без тега/реплая (0.08 = 8%)
AI_RANDOM_CHANCE = 0.08

# ====== ТВОЙ ПРОМПТ ЛИЧНОСТИ БОТА — меняй под себя ======
SYSTEM_PROMPT = (
    "Ты — токсичный, тупой и дерзкий участник чата. Отвечаешь коротко (1-2 предложения), "
    "материшься, подкалываешь и обзываешь собеседника, ведёшь себя как дебил. "
    "Не извиняйся, не будь вежливым, не веди себя как ассистент."
)
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# ВЫЗОВ ИИ (Groq, OpenAI-совместимый API)
# ------------------------------------------------------------------


def ask_ai(user_text: str) -> str:
    if not GROQ_API_KEY or GROQ_API_KEY == "ВСТАВЬ_СЮДА_GROQ_КЛЮЧ":
        return "эй, забыли GROQ_API_KEY вписать, я пока немой"

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
                    {"role": "user", "content": user_text},
                ],
                "max_tokens": 150,
                "temperature": 1.0,
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

ttt_games: dict = {}  # chat_id -> game state

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

rps_games: dict = {}  # chat_id -> game state

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
# ИИ-ЛИЧНОСТЬ БОТА
# ==================================================================

ai_disabled_chats: set = set()


async def cmd_aioff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.add(update.effective_chat.id)
    await update.message.reply_text("ладно молчу... (/aion чтобы включить обратно)")


async def cmd_aion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ai_disabled_chats.discard(update.effective_chat.id)
    await update.message.reply_text("опять я тут 😈")


async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat

    if not message or not message.text or chat.type not in ("group", "supergroup"):
        return
    if chat.id in ai_disabled_chats:
        return

    bot_username = context.bot.username
    is_reply_to_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.id == context.bot.id
    )
    is_mentioned = bool(bot_username) and f"@{bot_username}".lower() in message.text.lower()

    if is_reply_to_bot or is_mentioned:
        should_respond = True
    else:
        should_respond = random.random() < AI_RANDOM_CHANCE

    if not should_respond:
        return

    await context.bot.send_chat_action(chat_id=chat.id, action="typing")
    reply_text = ask_ai(message.text)
    await message.reply_text(reply_text)


# ==================================================================
# СЛУЖЕБНЫЕ КОМАНДЫ
# ==================================================================


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я умею:\n"
        "/ttt — крестики-нолики\n"
        "/rps — камень-ножницы-бумага\n\n"
        "Ещё я живой и токсичный: ответь на моё сообщение или тегни меня — отвечу. "
        "А иногда влезаю в разговор сам.\n"
        "/aioff — выключить мою болтовню, /aion — включить обратно."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("ttt", cmd_ttt))
    app.add_handler(CommandHandler("rps", cmd_rps))
    app.add_handler(CommandHandler("aioff", cmd_aioff))
    app.add_handler(CommandHandler("aion", cmd_aion))
    app.add_handler(CallbackQueryHandler(ttt_callback, pattern=r"^ttt:"))
    app.add_handler(CallbackQueryHandler(rps_callback, pattern=r"^rps:"))

    # ИИ-обработчик должен идти последним и не трогать команды
    app.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, ai_handler)
    )

    logger.info("Бот запущен, жду сообщений...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

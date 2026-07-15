#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Self Assistant / Personal UserBot
Single-file Python project for Pydroid 3, Termux, and Linux VPS.
"""

BOT_TOKEN = "Paste your Telegram Bot Token here"
API_ID = 0
API_HASH = ""
OWNER_ID = 0

import asyncio
import contextlib
import dataclasses
import datetime as _dt
import html
import json
import logging
import os
import re
import sqlite3
import sys
import time
import traceback
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

try:
    from telethon import TelegramClient, events, functions, types, errors
    from telethon.sessions import StringSession
except ImportError as exc:
    raise SystemExit("Telethon نصب نیست. اجرا کنید: pip install telethon") from exc

try:
    from aiogram import Bot, Dispatcher, F, Router
    from aiogram.enums import ParseMode
    from aiogram.filters import Command, CommandStart
    from aiogram.types import (CallbackQuery, Contact, InlineKeyboardButton, InlineKeyboardMarkup,
                               KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove)
    from aiogram.client.default import DefaultBotProperties
except ImportError as exc:
    raise SystemExit("aiogram نصب نیست. اجرا کنید: pip install aiogram") from exc

APP_VERSION = "3.0.0-single-file"
BASE_DIR = os.path.abspath(os.path.dirname(__file__) or ".")
DB_PATH = os.path.join(BASE_DIR, "self_assistant.sqlite3")
LOG_PATH = os.path.join(BASE_DIR, "self_assistant.log")
SESSION_FILE = os.path.join(BASE_DIR, "self_assistant.session")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("SelfAssistant")


def now_utc() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).lower() in {"1", "true", "yes", "on", "enabled", "فعال"}


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name or str(user_id))}</a>'


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[^0-9+]", "", phone or "")
    if cleaned and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()

    async def init(self) -> None:
        schema = [
            """CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                phone TEXT, role TEXT DEFAULT 'user', state TEXT, state_data TEXT,
                created_at TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER,
                message_id INTEGER, kind TEXT, text TEXT, raw TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS friends(
                user_id INTEGER PRIMARY KEY, note TEXT, reply TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS enemies(
                user_id INTEGER PRIMARY KEY, note TEXT, behavior TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, action TEXT, data TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY CHECK(id=1), phone TEXT, string_session TEXT,
                api_id INTEGER, api_hash TEXT, connected INTEGER DEFAULT 0,
                me TEXT, updated_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS auto_replies(
                id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT, response TEXT,
                chat_id INTEGER, enabled INTEGER DEFAULT 1, delay REAL DEFAULT 0, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS scheduled(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT, text TEXT, run_at TEXT,
                interval_seconds INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, last_run TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS muted(
                user_id INTEGER, chat_id INTEGER, until TEXT, reason TEXT, created_at TEXT,
                PRIMARY KEY(user_id, chat_id))""",
            """CREATE TABLE IF NOT EXISTS allowed_private(
                user_id INTEGER PRIMARY KEY, note TEXT, created_at TEXT)""",
        ]
        async with self.lock:
            cur = self.conn.cursor()
            for sql in schema:
                cur.execute(sql)
            self.conn.commit()
        await self.defaults()

    async def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> sqlite3.Cursor:
        async with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    async def fetchone(self, sql: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        async with self.lock:
            return self.conn.execute(sql, params).fetchone()

    async def fetchall(self, sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        async with self.lock:
            return self.conn.execute(sql, params).fetchall()

    async def defaults(self) -> None:
        defaults = {
            "name_clock_enabled": "0", "bio_clock_enabled": "0", "clock_format": "%H:%M",
            "private_lock": "0", "auto_react": "0", "auto_react_emoji": "❤️",
            "welcome_enabled": "0", "welcome_text": "سلام {name} عزیز، خوش آمدی 🌹",
            "action_enabled": "0", "action_type": "typing", "save_deleted": "1", "save_edited": "1",
            "friend_reply": "سلام دوست عزیز 🌟", "enemy_behavior": "ignore",
            "panel_theme": "dark", "startup_fast": "1", "last_restart": now_utc(),
        }
        for k, v in defaults.items():
            await self.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)", (k, v, now_utc()))

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def set(self, key: str, value: Any) -> None:
        await self.execute("INSERT OR REPLACE INTO settings(key,value,updated_at) VALUES(?,?,?)", (key, str(value), now_utc()))

    async def toggle(self, key: str) -> bool:
        new = not parse_bool(await self.get(key, "0"))
        await self.set(key, "1" if new else "0")
        return new

    async def add_log(self, level: str, action: str, data: Any = None) -> None:
        await self.execute("INSERT INTO logs(level,action,data,created_at) VALUES(?,?,?,?)", (level, action, safe_json(data), now_utc()))


class Keyboards:
    @staticmethod
    def contact() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 ارسال شماره من", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True, selective=True,
        )

    @staticmethod
    def inline(rows: List[List[Tuple[str, str]]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])

    @staticmethod
    def main() -> InlineKeyboardMarkup:
        return Keyboards.inline([
            [("👤 حساب من", "m:account"), ("⚙ تنظیمات", "m:settings")],
            [("⏰ ساعت و بیو", "m:clock"), ("✨ افکت متن", "m:effects")],
            [("🎭 حالت اکشن", "m:actions"), ("🤖 پاسخ خودکار", "m:auto_reply")],
            [("👁 ریکت خودکار", "m:react"), ("🔒 کنترل حریم خصوصی", "m:privacy")],
            [("💾 ذخیره پیام‌ها", "m:archive"), ("👥 مدیریت کاربران", "m:users")],
            [("🛠 ابزارها", "m:tools"), ("👋 خوشامدگویی", "m:welcome")],
            [("📊 وضعیت سیستم", "m:status")],
        ])

    @staticmethod
    def back() -> InlineKeyboardMarkup:
        return Keyboards.inline([[("⬅️ برگشت", "m:main")]])


class StateStore:
    def __init__(self):
        self.states: Dict[int, Tuple[str, Dict[str, Any]]] = {}

    def set(self, uid: int, state: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.states[uid] = (state, data or {})

    def get(self, uid: int) -> Tuple[Optional[str], Dict[str, Any]]:
        return self.states.get(uid, (None, {}))

    def clear(self, uid: int) -> None:
        self.states.pop(uid, None)


class UserClientManager:
    def __init__(self, db: Database):
        self.db = db
        self.client: Optional[TelegramClient] = None
        self.pending: Dict[int, Dict[str, Any]] = {}
        self.me: Optional[types.User] = None
        self.connected = asyncio.Event()
        self.handlers_ready = False
        self.original_first_name: Optional[str] = None
        self.original_last_name: Optional[str] = None
        self.original_about: Optional[str] = None

    async def start_from_db(self) -> None:
        row = await self.db.fetchone("SELECT * FROM sessions WHERE id=1")
        if not row or not row["string_session"] or not API_ID or not API_HASH:
            log.info("No saved user session or API credentials; panel will start without user client.")
            return
        try:
            await self._connect(StringSession(row["string_session"]))
            await self.db.add_log("INFO", "session_loaded", {"phone": row["phone"]})
        except Exception as exc:
            log.exception("Failed to restore session")
            await self.db.add_log("ERROR", "session_restore_failed", str(exc))

    async def _connect(self, session: Any) -> TelegramClient:
        if self.client and self.client.is_connected():
            await self.client.disconnect()
        self.client = TelegramClient(session, API_ID, API_HASH, device_model="SelfAssistant", system_version="Python", app_version=APP_VERSION)
        await self.client.connect()
        if await self.client.is_user_authorized():
            self.me = await self.client.get_me()
            self.connected.set()
            await self.persist_session()
            await self.capture_profile_defaults()
        return self.client

    async def send_code(self, owner_id: int, phone: str) -> str:
        if not API_ID or not API_HASH:
            raise RuntimeError("API_ID و API_HASH را ابتدای فایل وارد کنید.")
        phone = normalize_phone(phone)
        client = TelegramClient(StringSession(), API_ID, API_HASH, device_model="SelfAssistant", system_version="Python", app_version=APP_VERSION)
        await client.connect()
        sent = await client.send_code_request(phone, force_sms=False)
        self.pending[owner_id] = {"client": client, "phone": phone, "phone_code_hash": sent.phone_code_hash, "created": time.time(), "attempts": 0}
        await self.db.add_log("INFO", "login_code_sent", {"phone": phone})
        return phone

    async def sign_in_code(self, owner_id: int, code: str) -> str:
        info = self.pending.get(owner_id)
        if not info:
            raise RuntimeError("درخواست کد پیدا نشد. دوباره شماره را ارسال کنید.")
        if time.time() - info["created"] > 600:
            with contextlib.suppress(Exception):
                await info["client"].disconnect()
            self.pending.pop(owner_id, None)
            raise RuntimeError("کد واقعاً منقضی شده است. دوباره شماره را ارسال کنید.")
        client: TelegramClient = info["client"]
        info["attempts"] += 1
        code = re.sub(r"\D", "", code)
        try:
            await client.sign_in(phone=info["phone"], code=code, phone_code_hash=info["phone_code_hash"])
        except errors.SessionPasswordNeededError:
            self.pending[owner_id] = info
            return "PASSWORD_REQUIRED"
        except errors.PhoneCodeExpiredError as exc:
            raise RuntimeError("کد تلگرام منقضی شده است؛ از جدیدترین کد استفاده کنید و قبل از درخواست مجدد، کد قبلی را نفرستید.") from exc
        except errors.PhoneCodeInvalidError as exc:
            raise RuntimeError("کد وارد شده اشتباه است. فقط اعداد کد جدید تلگرام را بفرستید.") from exc
        await self.adopt_pending(owner_id)
        return "OK"

    async def sign_in_password(self, owner_id: int, password: str) -> None:
        info = self.pending.get(owner_id)
        if not info:
            raise RuntimeError("مرحله رمز دومرحله‌ای پیدا نشد.")
        await info["client"].sign_in(password=password)
        await self.adopt_pending(owner_id)

    async def adopt_pending(self, owner_id: int) -> None:
        info = self.pending.pop(owner_id)
        old = self.client
        self.client = info["client"]
        if old and old is not self.client:
            with contextlib.suppress(Exception):
                await old.disconnect()
        self.me = await self.client.get_me()
        self.connected.set()
        await self.persist_session(phone=info["phone"])
        await self.capture_profile_defaults()
        await self.db.add_log("INFO", "login_success", {"id": self.me.id, "phone": info["phone"]})

    async def persist_session(self, phone: Optional[str] = None) -> None:
        if not self.client:
            return
        session = self.client.session.save() if hasattr(self.client.session, "save") else ""
        me_raw = safe_json(dataclasses.asdict(self.me) if dataclasses.is_dataclass(self.me) else getattr(self.me, "to_dict", lambda: {})())
        await self.db.execute("INSERT OR REPLACE INTO sessions(id,phone,string_session,api_id,api_hash,connected,me,updated_at) VALUES(1,?,?,?,?,?,?,?)",
                              (phone or getattr(self.me, "phone", None), session, API_ID, API_HASH, 1, me_raw, now_utc()))

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
        self.connected.clear()
        await self.db.execute("UPDATE sessions SET connected=0, updated_at=? WHERE id=1", (now_utc(),))

    async def logout(self) -> None:
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.log_out()
            with contextlib.suppress(Exception):
                await self.client.disconnect()
        self.client = None
        self.me = None
        self.connected.clear()
        await self.db.execute("DELETE FROM sessions WHERE id=1")

    async def capture_profile_defaults(self) -> None:
        if not self.client or not self.me:
            return
        full = await self.client(functions.users.GetFullUserRequest(self.me.id))
        self.original_first_name = self.me.first_name or ""
        self.original_last_name = self.me.last_name or ""
        self.original_about = getattr(full.full_user, "about", "") or ""

    async def require(self) -> TelegramClient:
        if not self.client or not self.client.is_connected() or not await self.client.is_user_authorized():
            raise RuntimeError("اکانت متصل نیست. از بخش حساب من وارد شوید.")
        return self.client


class FeatureEngine:
    def __init__(self, db: Database, user: UserClientManager):
        self.db = db
        self.user = user
        self.tasks: List[asyncio.Task] = []
        self.deleted_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.rate: Dict[str, float] = {}

    async def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self.clock_loop(), name="clock_loop"),
            asyncio.create_task(self.schedule_loop(), name="schedule_loop"),
            asyncio.create_task(self.recovery_loop(), name="recovery_loop"),
        ]
        await self.install_handlers_when_ready()

    async def install_handlers_when_ready(self) -> None:
        async def waiter():
            while True:
                await self.user.connected.wait()
                if self.user.client and not self.user.handlers_ready:
                    self.user.client.add_event_handler(self.on_new_message, events.NewMessage(incoming=True))
                    self.user.client.add_event_handler(self.on_deleted, events.MessageDeleted())
                    self.user.client.add_event_handler(self.on_edited, events.MessageEdited(incoming=True))
                    self.user.client.add_event_handler(self.on_user_update, events.ChatAction())
                    self.user.handlers_ready = True
                    log.info("Userbot handlers installed")
                await asyncio.sleep(3)
        self.tasks.append(asyncio.create_task(waiter(), name="handler_installer"))

    async def clock_loop(self) -> None:
        last_text = None
        while True:
            try:
                if self.user.client and self.user.connected.is_set():
                    fmt = await self.db.get("clock_format", "%H:%M")
                    stamp = _dt.datetime.now().strftime(fmt)
                    if stamp != last_text:
                        last_text = stamp
                        name_on = parse_bool(await self.db.get("name_clock_enabled", "0"))
                        bio_on = parse_bool(await self.db.get("bio_clock_enabled", "0"))
                        if name_on:
                            first = (self.user.original_first_name or (self.user.me.first_name if self.user.me else "Me")).split(" | ")[0]
                            await self.user.client(functions.account.UpdateProfileRequest(first_name=f"{first} | {stamp}"))
                        if bio_on:
                            base = (self.user.original_about or "").split("\n⏰")[0]
                            await self.user.client(functions.account.UpdateProfileRequest(about=f"{base}\n⏰ {stamp}".strip()))
            except Exception as exc:
                log.warning("clock_loop error: %s", exc)
                await self.db.add_log("ERROR", "clock_loop", str(exc))
            await asyncio.sleep(45)

    async def schedule_loop(self) -> None:
        while True:
            try:
                if self.user.connected.is_set():
                    rows = await self.db.fetchall("SELECT * FROM scheduled WHERE enabled=1")
                    now = _dt.datetime.utcnow()
                    for row in rows:
                        run_at = _dt.datetime.fromisoformat(row["run_at"].replace("Z", ""))
                        if run_at <= now:
                            client = await self.user.require()
                            await client.send_message(row["chat"], row["text"])
                            if row["interval_seconds"]:
                                nxt = now + _dt.timedelta(seconds=int(row["interval_seconds"]))
                                await self.db.execute("UPDATE scheduled SET run_at=?, last_run=? WHERE id=?", (nxt.isoformat()+"Z", now_utc(), row["id"]))
                            else:
                                await self.db.execute("UPDATE scheduled SET enabled=0,last_run=? WHERE id=?", (now_utc(), row["id"]))
            except Exception as exc:
                log.warning("schedule_loop error: %s", exc)
            await asyncio.sleep(10)

    async def recovery_loop(self) -> None:
        while True:
            try:
                if self.user.client and not self.user.client.is_connected():
                    await self.user.client.connect()
            except Exception as exc:
                log.warning("recovery error: %s", exc)
            await asyncio.sleep(30)

    async def on_new_message(self, event: events.NewMessage.Event) -> None:
        try:
            msg = event.message
            sender = await event.get_sender()
            sid = getattr(sender, "id", 0) or 0
            self.deleted_cache[(event.chat_id, msg.id)] = {"chat_id": event.chat_id, "user_id": sid, "message_id": msg.id, "text": msg.message or "", "raw": msg.to_json(), "at": now_utc()}
            if len(self.deleted_cache) > 2000:
                for k in list(self.deleted_cache.keys())[:500]:
                    self.deleted_cache.pop(k, None)
            if event.is_private and parse_bool(await self.db.get("private_lock", "0")):
                allowed = await self.db.fetchone("SELECT user_id FROM allowed_private WHERE user_id=?", (sid,))
                friend = await self.db.fetchone("SELECT user_id FROM friends WHERE user_id=?", (sid,))
                if sid != (self.user.me.id if self.user.me else 0) and not allowed and not friend:
                    await event.reply("🔒 پیوی قفل است. پیام شما دریافت شد اما اجازه گفتگو ندارید.")
                    return
            await self.handle_auto_reply(event, sid)
            await self.handle_auto_react(event)
            await self.handle_action(event)
            friend = await self.db.fetchone("SELECT reply FROM friends WHERE user_id=?", (sid,))
            if friend and friend["reply"]:
                key = f"friend:{sid}"
                if time.time() - self.rate.get(key, 0) > 3600:
                    self.rate[key] = time.time()
                    await event.reply(friend["reply"])
        except Exception as exc:
            log.exception("new message handler failed")
            await self.db.add_log("ERROR", "new_message", str(exc))

    async def handle_auto_reply(self, event: events.NewMessage.Event, sid: int) -> None:
        rows = await self.db.fetchall("SELECT * FROM auto_replies WHERE enabled=1 AND (chat_id IS NULL OR chat_id=?)", (event.chat_id,))
        text = event.raw_text or ""
        for row in rows:
            if row["trigger"] and row["trigger"].lower() in text.lower():
                if row["delay"]:
                    await asyncio.sleep(float(row["delay"]))
                await event.reply(row["response"])
                break

    async def handle_auto_react(self, event: events.NewMessage.Event) -> None:
        if not parse_bool(await self.db.get("auto_react", "0")):
            return
        emoji = await self.db.get("auto_react_emoji", "❤️")
        with contextlib.suppress(Exception):
            await event.message.react(emoji)

    async def handle_action(self, event: events.NewMessage.Event) -> None:
        if not parse_bool(await self.db.get("action_enabled", "0")):
            return
        action_map = {
            "typing": types.SendMessageTypingAction(), "voice": types.SendMessageRecordAudioAction(),
            "photo": types.SendMessageUploadPhotoAction(1), "video": types.SendMessageUploadVideoAction(1),
            "file": types.SendMessageUploadDocumentAction(1), "sticker": types.SendMessageChooseStickerAction(),
        }
        kind = await self.db.get("action_type", "typing")
        with contextlib.suppress(Exception):
            await self.user.client(functions.messages.SetTypingRequest(peer=await event.get_input_chat(), action=action_map.get(kind, action_map["typing"])))

    async def on_deleted(self, event: events.MessageDeleted.Event) -> None:
        if not parse_bool(await self.db.get("save_deleted", "1")):
            return
        for mid in event.deleted_ids:
            data = self.deleted_cache.get((event.chat_id, mid), {"chat_id": event.chat_id, "message_id": mid, "text": "", "raw": "{}", "user_id": 0})
            await self.db.execute("INSERT INTO messages(chat_id,user_id,message_id,kind,text,raw,created_at) VALUES(?,?,?,?,?,?,?)",
                                  (data.get("chat_id"), data.get("user_id"), mid, "deleted", data.get("text"), data.get("raw"), now_utc()))

    async def on_edited(self, event: events.MessageEdited.Event) -> None:
        if not parse_bool(await self.db.get("save_edited", "1")):
            return
        msg = event.message
        await self.db.execute("INSERT INTO messages(chat_id,user_id,message_id,kind,text,raw,created_at) VALUES(?,?,?,?,?,?,?)",
                              (event.chat_id, getattr(await event.get_sender(), "id", 0), msg.id, "edited", msg.message or "", msg.to_json(), now_utc()))

    async def on_user_update(self, event: events.ChatAction.Event) -> None:
        try:
            if event.user_joined or event.user_added:
                if parse_bool(await self.db.get("welcome_enabled", "0")):
                    text = await self.db.get("welcome_text", "سلام {name} عزیز، خوش آمدی 🌹")
                    user = await event.get_user()
                    await event.reply(text.format(name=getattr(user, "first_name", "دوست"), id=getattr(user, "id", 0)))
        except Exception as exc:
            log.warning("welcome failed: %s", exc)


class TextEffects:
    @staticmethod
    def apply(kind: str, text: str) -> str:
        escaped = html.escape(text)
        return {
            "bold": f"<b>{escaped}</b>", "italic": f"<i>{escaped}</i>", "underline": f"<u>{escaped}</u>",
            "strike": f"<s>{escaped}</s>", "spoiler": f"<tg-spoiler>{escaped}</tg-spoiler>",
            "code": f"<code>{escaped}</code>", "pre": f"<pre>{escaped}</pre>",
        }.get(kind, escaped)

    @staticmethod
    async def typewriter(bot: Bot, chat_id: int, text: str) -> None:
        msg = await bot.send_message(chat_id, "▌")
        buf = ""
        for ch in text:
            buf += ch
            with contextlib.suppress(Exception):
                await msg.edit_text(html.escape(buf) + "▌", parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.08)
        with contextlib.suppress(Exception):
            await msg.edit_text(html.escape(buf), parse_mode=ParseMode.HTML)


class Panel:
    def __init__(self, db: Database, user: UserClientManager, engine: FeatureEngine):
        self.db = db
        self.user = user
        self.engine = engine
        self.state = StateStore()
        self.router = Router()
        self.register()

    def authed(self, uid: int) -> bool:
        return OWNER_ID == 0 or uid == OWNER_ID

    async def guard_msg(self, message: Message) -> bool:
        if not self.authed(message.from_user.id):
            await message.answer("⛔️ دسترسی فقط برای مالک مجاز است.")
            return False
        return True

    async def guard_cb(self, call: CallbackQuery) -> bool:
        if not self.authed(call.from_user.id):
            await call.answer("⛔️ غیرمجاز", show_alert=True)
            return False
        return True

    def register(self) -> None:
        r = self.router
        r.message.register(self.start, CommandStart())
        r.message.register(self.help_cmd, Command("help"))
        r.message.register(self.on_contact, F.contact)
        r.message.register(self.on_text)
        r.callback_query.register(self.on_callback)

    async def start(self, message: Message) -> None:
        if not await self.guard_msg(message):
            return
        await self.upsert_panel_user(message)
        await message.answer("🌟 پنل دستیار شخصی آماده است.", reply_markup=ReplyKeyboardRemove())
        await message.answer(await self.main_text(), reply_markup=Keyboards.main(), parse_mode=ParseMode.HTML)

    async def help_cmd(self, message: Message) -> None:
        if await self.guard_msg(message):
            await message.answer("برای ورود /start را بزنید. همه منوها با دکمه‌های شیشه‌ای مدیریت می‌شوند.")

    async def upsert_panel_user(self, message: Message) -> None:
        u = message.from_user
        await self.db.execute("INSERT OR REPLACE INTO users(user_id,username,first_name,last_name,role,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                              (u.id, u.username, u.first_name, u.last_name, "owner", now_utc(), now_utc()))

    async def main_text(self) -> str:
        status = "🟢 متصل" if self.user.connected.is_set() else "🔴 قطع"
        return f"<b>🏠 منوی اصلی Self Assistant</b>\n\nوضعیت اکانت: {status}\nنسخه: <code>{APP_VERSION}</code>"

    async def on_contact(self, message: Message) -> None:
        if not await self.guard_msg(message):
            return
        if not message.contact or message.contact.user_id != message.from_user.id:
            await message.answer("لطفاً شماره خودتان را با دکمه ارسال کنید.")
            return
        try:
            phone = await self.user.send_code(message.from_user.id, message.contact.phone_number)
            self.state.set(message.from_user.id, "login_code", {"phone": phone})
            await message.answer("✅ کد ارسال شد. کد عددی تلگرام را همینجا بفرستید.\nنکته: این نسخه phone_code_hash را نگه می‌دارد تا خطای منقضی شدن اشتباهی رخ ندهد.", reply_markup=ReplyKeyboardRemove())
        except Exception as exc:
            await message.answer(f"❌ خطا در ارسال کد: {html.escape(str(exc))}")

    async def on_text(self, message: Message) -> None:
        if not await self.guard_msg(message):
            return
        state, data = self.state.get(message.from_user.id)
        text = message.text or ""
        try:
            if state == "login_code":
                result = await self.user.sign_in_code(message.from_user.id, text)
                if result == "PASSWORD_REQUIRED":
                    self.state.set(message.from_user.id, "login_password", data)
                    await message.answer("🔐 رمز دومرحله‌ای فعال است. رمز را ارسال کنید.")
                else:
                    self.state.clear(message.from_user.id)
                    await message.answer("✅ اکانت با موفقیت متصل شد.", reply_markup=Keyboards.main())
                return
            if state == "login_password":
                await self.user.sign_in_password(message.from_user.id, text)
                self.state.clear(message.from_user.id)
                await message.answer("✅ ورود دومرحله‌ای کامل شد و Session ذخیره شد.", reply_markup=Keyboards.main())
                return
            if state and state.startswith("set:"):
                key = state.split(":", 1)[1]
                await self.db.set(key, text)
                self.state.clear(message.from_user.id)
                await message.answer("✅ ذخیره شد.", reply_markup=Keyboards.main())
                return
            if state == "effect":
                kind = data.get("kind", "bold")
                if kind == "typing":
                    await TextEffects.typewriter(message.bot, message.chat.id, text)
                else:
                    await message.answer(TextEffects.apply(kind, text), parse_mode=ParseMode.HTML)
                self.state.clear(message.from_user.id)
                return
            if state == "add_friend":
                uid, _, reply = text.partition(" ")
                await self.db.execute("INSERT OR REPLACE INTO friends(user_id,note,reply,created_at) VALUES(?,?,?,?)", (int(uid), "panel", reply or await self.db.get("friend_reply"), now_utc()))
                self.state.clear(message.from_user.id)
                await message.answer("✅ دوست افزوده شد.", reply_markup=Keyboards.main())
                return
            if state == "add_enemy":
                await self.db.execute("INSERT OR REPLACE INTO enemies(user_id,note,behavior,created_at) VALUES(?,?,?,?)", (int(text.strip()), "panel", await self.db.get("enemy_behavior"), now_utc()))
                self.state.clear(message.from_user.id)
                await message.answer("✅ کاربر محدود افزوده شد.", reply_markup=Keyboards.main())
                return
            if state == "calc":
                if not re.fullmatch(r"[0-9+\-*/(). %]+", text):
                    raise ValueError("عبارت غیرمجاز است.")
                await message.answer(f"🧮 نتیجه: <code>{eval(text, {'__builtins__': {}}, {})}</code>", parse_mode=ParseMode.HTML)
                self.state.clear(message.from_user.id)
                return
            await message.answer("از دکمه‌های پنل استفاده کنید.", reply_markup=Keyboards.main())
        except Exception as exc:
            self.state.clear(message.from_user.id)
            await message.answer(f"❌ خطا: {html.escape(str(exc))}", reply_markup=Keyboards.main())

    async def on_callback(self, call: CallbackQuery) -> None:
        if not await self.guard_cb(call):
            return
        data = call.data or ""
        try:
            if data == "m:main":
                await call.message.edit_text(await self.main_text(), reply_markup=Keyboards.main(), parse_mode=ParseMode.HTML)
            elif data == "m:account":
                await self.account(call)
            elif data == "acc:login":
                await call.message.answer("📱 برای اتصال اکانت، شماره را با دکمه زیر ارسال کنید.", reply_markup=Keyboards.contact())
            elif data == "acc:logout":
                await self.user.logout(); await call.message.edit_text("✅ اتصال حذف شد.", reply_markup=Keyboards.back())
            elif data == "acc:disconnect":
                await self.user.disconnect(); await call.message.edit_text("✅ کلاینت قطع شد ولی Session باقی ماند.", reply_markup=Keyboards.back())
            elif data.startswith("toggle:"):
                key = data.split(":", 1)[1]; val = await self.db.toggle(key); await call.answer("فعال شد" if val else "غیرفعال شد"); await self.refresh_menu(call, key)
            elif data.startswith("set:"):
                key = data.split(":", 1)[1]; self.state.set(call.from_user.id, f"set:{key}"); await call.message.answer("مقدار جدید را ارسال کنید:")
            elif data == "m:clock":
                await self.clock(call)
            elif data == "m:effects":
                await self.effects(call)
            elif data.startswith("effect:"):
                self.state.set(call.from_user.id, "effect", {"kind": data.split(":",1)[1]}); await call.message.answer("متن را ارسال کنید:")
            elif data == "m:actions":
                await self.actions(call)
            elif data.startswith("action:"):
                await self.db.set("action_type", data.split(":",1)[1]); await self.actions(call)
            elif data == "m:react":
                await self.react(call)
            elif data == "m:privacy":
                await self.privacy(call)
            elif data == "m:archive":
                await self.archive(call)
            elif data == "arch:clear":
                await self.db.execute("DELETE FROM messages"); await call.message.edit_text("🧹 آرشیو پاک شد.", reply_markup=Keyboards.back())
            elif data == "m:users":
                await self.users(call)
            elif data == "user:add_friend":
                self.state.set(call.from_user.id, "add_friend"); await call.message.answer("آیدی عددی دوست و در صورت نیاز متن پاسخ را بفرستید:")
            elif data == "user:add_enemy":
                self.state.set(call.from_user.id, "add_enemy"); await call.message.answer("آیدی عددی کاربر محدود را بفرستید:")
            elif data == "m:auto_reply":
                await self.auto_reply(call)
            elif data == "ar:add_default":
                await self.db.execute("INSERT INTO auto_replies(trigger,response,created_at) VALUES(?,?,?)", ("سلام", "سلام، الان در دسترس نیستم 🌹", now_utc())); await self.auto_reply(call)
            elif data == "m:welcome":
                await self.welcome(call)
            elif data == "m:tools":
                await self.tools(call)
            elif data == "tool:ping":
                await call.answer("Pong") ; await call.message.answer(f"🏓 Pong: <code>{int(time.time())}</code>", parse_mode=ParseMode.HTML)
            elif data == "tool:id":
                await call.message.answer(f"👤 Your ID: <code>{call.from_user.id}</code>\n💬 Chat ID: <code>{call.message.chat.id}</code>", parse_mode=ParseMode.HTML)
            elif data == "tool:calc":
                self.state.set(call.from_user.id, "calc"); await call.message.answer("عبارت ریاضی را ارسال کنید:")
            elif data == "m:settings":
                await self.settings(call)
            elif data == "m:status":
                await self.status(call)
            else:
                await call.answer("در حال توسعه نیست؛ همین نسخه کامل handler دارد.")
        except Exception as exc:
            log.exception("callback error")
            await call.message.answer(f"❌ خطا: {html.escape(str(exc))}")
        finally:
            with contextlib.suppress(Exception):
                await call.answer()

    async def refresh_menu(self, call: CallbackQuery, key: str) -> None:
        if "clock" in key: await self.clock(call)
        elif "react" in key: await self.react(call)
        elif "private" in key: await self.privacy(call)
        elif "welcome" in key: await self.welcome(call)
        else: await self.settings(call)

    async def account(self, call: CallbackQuery) -> None:
        me = self.user.me
        if me:
            text = f"<b>👤 حساب من</b>\nنام: {html.escape(me.first_name or '')}\nیوزرنیم: @{html.escape(me.username or '-')}\nآیدی: <code>{me.id}</code>\nشماره: <code>{html.escape(getattr(me,'phone','') or '-')}</code>"
        else:
            text = "<b>👤 حساب من</b>\nاکانت هنوز متصل نیست."
        await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔌 اتصال با شماره", "acc:login")], [("⛔️ قطع موقت", "acc:disconnect"), ("🗑 حذف Session", "acc:logout")], [("⬅️ برگشت", "m:main")]
        ]))

    async def clock(self, call: CallbackQuery) -> None:
        nf=parse_bool(await self.db.get("name_clock_enabled")); bf=parse_bool(await self.db.get("bio_clock_enabled")); fmt=await self.db.get("clock_format")
        await call.message.edit_text(f"<b>⏰ ساعت و بیو</b>\nنام: {'🟢' if nf else '🔴'}\nبیو: {'🟢' if bf else '🔴'}\nفرمت: <code>{html.escape(fmt)}</code>", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔁 ساعت روی نام", "toggle:name_clock_enabled"), ("🔁 ساعت روی بیو", "toggle:bio_clock_enabled")], [("🧩 تنظیم فرمت", "set:clock_format")], [("⬅️ برگشت", "m:main")]
        ]))

    async def effects(self, call: CallbackQuery) -> None:
        await call.message.edit_text("<b>✨ افکت متن</b>\nیک افکت انتخاب کنید و سپس متن را بفرستید.", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("B Bold", "effect:bold"), ("I Italic", "effect:italic"), ("U Underline", "effect:underline")],
            [("S Strike", "effect:strike"), ("🙈 Spoiler", "effect:spoiler")], [("⌨️ تایپی", "effect:typing"), ("💻 Code", "effect:code")], [("⬅️ برگشت", "m:main")]
        ]))

    async def actions(self, call: CallbackQuery) -> None:
        en=parse_bool(await self.db.get("action_enabled")); kind=await self.db.get("action_type")
        await call.message.edit_text(f"<b>🎭 حالت اکشن</b>\nوضعیت: {'🟢 فعال' if en else '🔴 غیرفعال'}\nنوع: <code>{kind}</code>", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔁 روشن/خاموش", "toggle:action_enabled")], [("Typing", "action:typing"), ("Voice", "action:voice"), ("Photo", "action:photo")],
            [("Video", "action:video"), ("File", "action:file"), ("Sticker", "action:sticker")], [("⬅️ برگشت", "m:main")]
        ]))

    async def react(self, call: CallbackQuery) -> None:
        en=parse_bool(await self.db.get("auto_react")); emoji=await self.db.get("auto_react_emoji")
        await call.message.edit_text(f"<b>👁 ریکت خودکار</b>\nوضعیت: {'🟢' if en else '🔴'}\nایموجی: {html.escape(emoji)}", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔁 روشن/خاموش", "toggle:auto_react"), ("😀 تنظیم ایموجی", "set:auto_react_emoji")], [("⬅️ برگشت", "m:main")]
        ]))

    async def privacy(self, call: CallbackQuery) -> None:
        en=parse_bool(await self.db.get("private_lock")); count=(await self.db.fetchone("SELECT COUNT(*) c FROM allowed_private"))["c"]
        await call.message.edit_text(f"<b>🔒 کنترل حریم خصوصی</b>\nقفل پیوی: {'🟢' if en else '🔴'}\nکاربران مجاز: {count}", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔁 قفل پیوی", "toggle:private_lock")], [("⬅️ برگشت", "m:main")]
        ]))

    async def archive(self, call: CallbackQuery) -> None:
        c=(await self.db.fetchone("SELECT COUNT(*) c FROM messages"))["c"]; rows=await self.db.fetchall("SELECT * FROM messages ORDER BY id DESC LIMIT 5")
        preview="\n".join([f"#{r['id']} {r['kind']} {str(r['text'])[:40]}" for r in rows]) or "خالی"
        await call.message.edit_text(f"<b>💾 ذخیره پیام‌ها</b>\nتعداد: {c}\n<pre>{html.escape(preview)}</pre>", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("ذخیره حذف‌شده", "toggle:save_deleted"), ("ذخیره ویرایش", "toggle:save_edited")], [("🧹 پاکسازی", "arch:clear")], [("⬅️ برگشت", "m:main")]
        ]))

    async def users(self, call: CallbackQuery) -> None:
        fc=(await self.db.fetchone("SELECT COUNT(*) c FROM friends"))["c"]; ec=(await self.db.fetchone("SELECT COUNT(*) c FROM enemies"))["c"]
        await call.message.edit_text(f"<b>👥 مدیریت کاربران</b>\nدوستان: {fc}\nمحدودها: {ec}", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("➕ افزودن دوست", "user:add_friend"), ("➕ افزودن محدود", "user:add_enemy")], [("💬 پاسخ دوستان", "set:friend_reply"), ("🚫 رفتار محدود", "set:enemy_behavior")], [("⬅️ برگشت", "m:main")]
        ]))

    async def auto_reply(self, call: CallbackQuery) -> None:
        c=(await self.db.fetchone("SELECT COUNT(*) c FROM auto_replies"))["c"]
        await call.message.edit_text(f"<b>🤖 پاسخ خودکار</b>\nقوانین: {c}\nبرای شروع یک قانون پیش‌فرض بسازید یا دیتابیس را توسعه دهید.", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("➕ قانون پیش‌فرض", "ar:add_default")], [("⬅️ برگشت", "m:main")]
        ]))

    async def welcome(self, call: CallbackQuery) -> None:
        en=parse_bool(await self.db.get("welcome_enabled")); txt=await self.db.get("welcome_text")
        await call.message.edit_text(f"<b>👋 خوشامدگویی</b>\nوضعیت: {'🟢' if en else '🔴'}\nمتن: {html.escape(txt)}", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🔁 روشن/خاموش", "toggle:welcome_enabled"), ("✏️ متن", "set:welcome_text")], [("⬅️ برگشت", "m:main")]
        ]))

    async def tools(self, call: CallbackQuery) -> None:
        await call.message.edit_text("<b>🛠 ابزارها</b>\nابزارهای سریع و امن.", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🏓 Ping", "tool:ping"), ("🆔 آیدی", "tool:id"), ("🧮 ماشین حساب", "tool:calc")], [("📊 وضعیت", "m:status")], [("⬅️ برگشت", "m:main")]
        ]))

    async def settings(self, call: CallbackQuery) -> None:
        await call.message.edit_text("<b>⚙ تنظیمات</b>\nمدیریت رفتار کلی سیستم.", parse_mode=ParseMode.HTML, reply_markup=Keyboards.inline([
            [("🚀 اجرای سریع", "toggle:startup_fast")], [("🧩 فرمت ساعت", "set:clock_format")], [("⬅️ برگشت", "m:main")]
        ]))

    async def status(self, call: CallbackQuery) -> None:
        db_size=os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        session="🟢" if self.user.connected.is_set() else "🔴"
        rows=(await self.db.fetchone("SELECT COUNT(*) c FROM logs"))["c"]
        await call.message.edit_text(f"<b>📊 وضعیت سیستم</b>\nاکانت: {session}\nDB: <code>{db_size} bytes</code>\nLogs: <code>{rows}</code>\nPython: <code>{html.escape(sys.version.split()[0])}</code>\nUptime: <code>{int(time.time()-START_TIME)}s</code>", parse_mode=ParseMode.HTML, reply_markup=Keyboards.back())


START_TIME = time.time()

async def main() -> None:
    if BOT_TOKEN == "Paste your Telegram Bot Token here" or not BOT_TOKEN.strip():
        raise SystemExit("BOT_TOKEN را ابتدای فایل self.py وارد کنید.")
    db = Database(DB_PATH)
    await db.init()
    user = UserClientManager(db)
    engine = FeatureEngine(db, user)
    panel = Panel(db, user, engine)
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(panel.router)
    await db.add_log("INFO", "startup", {"version": APP_VERSION})
    restore_task = asyncio.create_task(user.start_from_db(), name="restore_user_session")
    await engine.start()
    log.info("Bot panel is starting fast; user session restores in background.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        restore_task.cancel()
        with contextlib.suppress(Exception):
            await restore_task
        if user.client:
            await user.client.disconnect()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user")
    except Exception:
        traceback.print_exc()
        raise

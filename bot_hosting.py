"""
BOT HOSTING — Single File Version
All modules merged: config, database, utils, handlers, web_server, main
Set environment variables in .env or export them before running.

Requirements:
  pip install python-telegram-bot[all] aiosqlite aiofiles aiohttp psutil httpx python-dotenv
"""

# ══════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════
import asyncio
import html as html_mod
import json
import logging
import os
import platform
import re
import secrets
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from functools import wraps

import aiofiles
import aiosqlite
import psutil
from aiohttp import web
from dotenv import load_dotenv
from telegram import (
    BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, Update,
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters,
)

# ══════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════
load_dotenv()

BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
ADMIN_IDS    = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip()]
BOT_NAME     = os.getenv("BOT_NAME", "BOT HOSTING")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

FREE_MAX_BOTS      = int(os.getenv("FREE_MAX_BOTS",      "3"))
FREE_MAX_RAM_MB    = int(os.getenv("FREE_MAX_RAM_MB",    "256"))
PREMIUM_MAX_BOTS   = int(os.getenv("PREMIUM_MAX_BOTS",   "15"))
PREMIUM_MAX_RAM_MB = int(os.getenv("PREMIUM_MAX_RAM_MB", "1024"))

STARS_PRICE_MONTHLY = int(os.getenv("STARS_PRICE_MONTHLY", "100"))
STARS_PRICE_YEARLY  = int(os.getenv("STARS_PRICE_YEARLY",  "900"))

DB_PATH          = "bot_data.db"
USER_BOTS_DIR    = "user_bots"
WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "60"))
MAX_AUTO_RESTARTS = int(os.getenv("MAX_AUTO_RESTARTS", "10"))

# Premium emoji IDs — "0" means use fallback only
DEFAULT_EMOJIS: dict[str, str] = {
    "welcome":  "5364125616801073577",
    "upload":   "6323432151777809240",
    "files":    "0",
    "run":      "6296508771325707891",
    "stop":     "0",
    "restart":  "0",
    "status":   "0",
    "logs":     "0",
    "delete":   "5307659638810877853",
    "admin":    "6222247670086371092",
    "premium":  "5890847821728322055",
    "error":    "6298671811345254603",
    "success":  "6219532735359223977",
    "warning":  "6296577138615125756",
    "edit":     "0",
    "back":     "6172183602843882092",
    "settings": "0",
    "support":  "0",
    "bot":      "0",
}

DEFAULT_FALLBACK_EMOJIS: dict[str, str] = {
    "welcome":  "👋",
    "upload":   "📤",
    "files":    "📁",
    "run":      "▶️",
    "stop":     "⏹️",
    "restart":  "🔄",
    "status":   "📊",
    "logs":     "📋",
    "delete":   "🗑️",
    "admin":    "👑",
    "premium":  "⭐",
    "error":    "❌",
    "success":  "✅",
    "warning":  "⚠️",
    "edit":     "✏️",
    "back":     "◀️",
    "settings": "⚙️",
    "support":  "🆘",
    "bot":      "🤖",
}

# Button style shortcuts

# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════

async def _migrate(db):
    migrations = [
        "ALTER TABLE bots  ADD COLUMN bot_type       TEXT    DEFAULT 'python'",
        "ALTER TABLE bots  ADD COLUMN uptime_seconds  INTEGER DEFAULT 0",
        "ALTER TABLE bots  ADD COLUMN auto_restart    INTEGER DEFAULT 1",
        "ALTER TABLE bots  ADD COLUMN crash_count     INTEGER DEFAULT 0",
        "ALTER TABLE bots  ADD COLUMN started_at      TEXT",
        "ALTER TABLE users ADD COLUMN is_suspended    INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_activity   TEXT",
    ]
    for sql in migrations:
        try:
            await db.execute(sql)
        except Exception:
            pass
    await db.commit()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT    DEFAULT '',
            full_name     TEXT    DEFAULT '',
            plan          TEXT    DEFAULT 'free',
            plan_expires  TEXT,
            is_banned     INTEGER DEFAULT 0,
            is_suspended  INTEGER DEFAULT 0,
            referral_code TEXT    UNIQUE,
            referred_by   INTEGER,
            referral_count INTEGER DEFAULT 0,
            last_activity TEXT,
            joined_at     TEXT    DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            bot_name      TEXT,
            main_file     TEXT,
            folder_path   TEXT,
            bot_type      TEXT    DEFAULT 'python',
            status        TEXT    DEFAULT 'stopped',
            pid           INTEGER,
            started_at    TEXT,
            uptime_seconds INTEGER DEFAULT 0,
            restart_count INTEGER DEFAULT 0,
            auto_restart  INTEGER DEFAULT 1,
            crash_count   INTEGER DEFAULT 0,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            bot_id      INTEGER,
            filename    TEXT,
            filepath    TEXT,
            file_type   TEXT,
            size_bytes  INTEGER DEFAULT 0,
            uploaded_at TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS emoji_settings (
            key            TEXT PRIMARY KEY,
            custom_emoji_id TEXT,
            fallback        TEXT,
            updated_at     TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS button_settings (
            key        TEXT PRIMARY KEY,
            label      TEXT,
            color      TEXT DEFAULT 'default',
            emoji_key  TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bot_settings (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bot_texts (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            description TEXT,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            type        TEXT,
            amount      INTEGER,
            description TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS broadcast_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER,
            target      TEXT,
            total       INTEGER DEFAULT 0,
            sent        INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS admin_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER,
            action      TEXT,
            target_id   INTEGER,
            details     TEXT,
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        await db.commit()
        await _migrate(db)
        await _seed_default_emojis(db)
        await _seed_default_buttons(db)
        await _seed_default_settings(db)
        await _seed_default_texts(db)


async def _seed_default_emojis(db):
    for key, emoji_id in DEFAULT_EMOJIS.items():
        fallback = DEFAULT_FALLBACK_EMOJIS.get(key, "⭐")
        await db.execute(
            "INSERT OR IGNORE INTO emoji_settings (key, custom_emoji_id, fallback) VALUES (?,?,?)",
            (key, emoji_id, fallback),
        )
    await db.commit()


async def _seed_default_buttons(db):
    defaults = [
        ("my_files",      "My Files",       "primary", "files"),
        ("upload_file",   "Upload File",    "success", "upload"),
        ("edit_files",    "Edit Files",     "primary", "edit"),
        ("delete_folder", "Delete Folder",  "danger",  "delete"),
        ("run_module",    "Run Bot",        "success", "run"),
        ("status",        "Status",         "primary", "status"),
        ("my_logs",       "My Logs",        "primary", "logs"),
        ("upgrade",       "Buy Premium",    "danger",  "premium"),
        ("support",       "Support",        "danger",  "support"),
        ("admin_panel",   "Admin Panel 🔐", "danger",  "admin"),
    ]
    for key, label, color, emoji_key in defaults:
        await db.execute(
            "INSERT OR IGNORE INTO button_settings (key, label, color, emoji_key) VALUES (?,?,?,?)",
            (key, label, color, emoji_key),
        )
    await db.commit()


async def _seed_default_settings(db):
    for key, value in [
        ("welcome_photo_id",  ""),
        ("support_username",  "@YourSupportUsername"),
        ("channel_link",      "https://t.me/yourchannel"),
        ("maintenance_mode",  "0"),
    ]:
        await db.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?,?)", (key, value)
        )
    await db.commit()


async def _seed_default_texts(db):
    defaults = [
        ("welcome_title",
         "🚀 <b>Welcome to {bot_name}!</b>",
         "Title of /start message. HTML supported. Use [EMJ:key] for premium emoji."),
        ("welcome_body",
         "Host your Python &amp; Node.js bots 24/7 on our powerful servers.\n\n"
         "✅ <b>Free:</b> {free_bots} bots · {free_ram}MB RAM\n"
         "⭐ <b>Premium:</b> {premium_bots} bots · {premium_ram}MB RAM\n\n"
         "👤 {user_name}  |  Plan: {plan}\n"
         "👥 Users: {total_users}  |  🟢 Running: {running_bots}",
         "Body of /start message."),
        ("help_text",
         "📖 <b>Help &amp; Commands</b>\n\n"
         "📁 /files — My hosted bots\n"
         "📤 /upload — Upload a bot (.py, .js, .zip)\n"
         "▶️ /run — Start / stop / restart\n"
         "📊 /status — Server stats\n"
         "📋 /logs — Live logs\n"
         "🔥 /upgrade — Upgrade to Premium\n"
         "🆘 /support — Contact support\n"
         "❌ /cancel — Cancel action",
         "Help command message."),
        ("premium_title",
         "🔥 <b>Upgrade to Premium</b>",
         "Premium page title."),
        ("premium_body",
         "Unlock the full power of <b>{bot_name}</b>!\n\n"
         "🤖 Host up to <b>{premium_bots} bots</b>\n"
         "💾 <b>{premium_ram}MB</b> RAM each\n"
         "⚡ Priority resources\n"
         "📊 Advanced analytics\n"
         "🆘 Priority support",
         "Premium upgrade description."),
        ("support_text",
         "🆘 <b>Support</b>\n\nNeed help? Contact our team:\n\n"
         "📩 {support_username}\n\n"
         "📢 Join our channel: {channel_link}",
         "Support page message."),
        ("upload_prompt",
         "📤 <b>Upload Your Bot Files</b>\n\n"
         "Send me one of:\n"
         "• 🐍 Python file (<code>.py</code>)\n"
         "• 🟨 Node.js file (<code>.js</code>)\n"
         "• 📦 ZIP archive\n\n"
         "I'll auto-install <code>requirements.txt</code> or <code>package.json</code>!\n\n"
         "Send /cancel to abort.",
         "Upload file prompt message."),
        ("bot_started_notify",
         "🟢 <b>Bot Started!</b>\n\n"
         "🤖 <code>{bot_name}</code> is now running.\n"
         "PID: <code>{pid}</code>",
         "Notification when bot starts."),
        ("bot_crashed_notify",
         "🔴 <b>Bot Crashed!</b>\n\n"
         "🤖 <code>{bot_name}</code> has stopped unexpectedly.\n"
         "🔄 Auto-restarting... (attempt {restart_count})",
         "Notification when bot crashes and auto-restarts."),
        ("premium_expired_notify",
         "⚠️ <b>Premium Expired</b>\n\n"
         "Your Premium plan has expired. You've been moved to the Free plan.\n\n"
         "Use /upgrade to renew your subscription.",
         "Notification when premium expires."),
    ]
    for key, value, desc in defaults:
        await db.execute(
            "INSERT OR IGNORE INTO bot_texts (key, value, description) VALUES (?,?,?)",
            (key, value, desc),
        )
    await db.commit()


# ── DB helpers ────────────────────────────────────────────────────

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone()


async def create_user(user_id: int, username: str, full_name: str, referred_by: int = None):
    ref_code = secrets.token_urlsafe(6)
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users "
            "(user_id, username, full_name, referral_code, referred_by, last_activity) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, username, full_name, ref_code, referred_by, now),
        )
        if referred_by:
            await db.execute(
                "UPDATE users SET referral_count=referral_count+1 WHERE user_id=?",
                (referred_by,),
            )
        await db.commit()


async def touch_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_activity=? WHERE user_id=?",
            (datetime.now().isoformat(), user_id),
        )
        await db.commit()


async def update_user_plan(user_id: int, plan: str, days: int):
    expires = (datetime.now() + timedelta(days=days)).isoformat() if days > 0 else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET plan=?, plan_expires=? WHERE user_id=?",
            (plan, expires, user_id),
        )
        await db.commit()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY joined_at DESC") as c:
            return await c.fetchall()


async def get_users_by_plan(plan: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE plan=? AND is_banned=0 AND is_suspended=0", (plan,)
        ) as c:
            return await c.fetchall()


async def search_users(query: str):
    q = f"%{query}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE username LIKE ? OR full_name LIKE ? OR CAST(user_id AS TEXT) LIKE ? "
            "ORDER BY joined_at DESC LIMIT 20",
            (q, q, q),
        ) as c:
            return await c.fetchall()


async def ban_user(user_id: int, ban: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if ban else 0, user_id))
        await db.commit()


async def suspend_user(user_id: int, suspend: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_suspended=? WHERE user_id=?", (1 if suspend else 0, user_id))
        await db.commit()


async def delete_user_data(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT folder_path FROM bots WHERE user_id=?", (user_id,)) as c:
            rows = await c.fetchall()
        for (folder,) in rows:
            if folder and os.path.isdir(folder):
                shutil.rmtree(folder, ignore_errors=True)
        await db.execute("DELETE FROM bots  WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM files WHERE user_id=?", (user_id,))
        await db.commit()


async def get_expired_premium_users():
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE plan='premium' AND plan_expires IS NOT NULL AND plan_expires<?", (now,)
        ) as c:
            return await c.fetchall()


async def get_user_bots(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bots WHERE user_id=? ORDER BY created_at DESC", (user_id,)) as c:
            return await c.fetchall()


async def get_bot(bot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bots WHERE id=?", (bot_id,)) as c:
            return await c.fetchone()


async def get_all_bots():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bots") as c:
            return await c.fetchall()


async def get_running_bots():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bots WHERE status='running' AND auto_restart=1") as c:
            return await c.fetchall()


async def create_bot(user_id: int, bot_name: str, main_file: str, folder_path: str, bot_type: str = "python"):
    async with aiosqlite.connect(DB_PATH) as db:
        c = await db.execute(
            "INSERT INTO bots (user_id, bot_name, main_file, folder_path, bot_type) VALUES (?,?,?,?,?)",
            (user_id, bot_name, main_file, folder_path, bot_type),
        )
        await db.commit()
        return c.lastrowid


async def update_bot_status(bot_id: int, status: str, pid: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if status == "running":
            await db.execute(
                "UPDATE bots SET status=?, pid=?, started_at=? WHERE id=?",
                (status, pid, datetime.now().isoformat(), bot_id),
            )
        else:
            await db.execute("UPDATE bots SET status=?, pid=NULL WHERE id=?", (status, bot_id))
        await db.commit()


async def increment_restart_count(bot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE bots SET restart_count=restart_count+1, crash_count=crash_count+1 WHERE id=?", (bot_id,)
        )
        await db.commit()


async def delete_bot(bot_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bots  WHERE id=?", (bot_id,))
        await db.execute("DELETE FROM files WHERE bot_id=?", (bot_id,))
        await db.commit()


async def set_bot_auto_restart(bot_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE bots SET auto_restart=? WHERE id=?", (1 if enabled else 0, bot_id))
        await db.commit()


async def add_file(user_id, bot_id, filename, filepath, file_type, size):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO files (user_id, bot_id, filename, filepath, file_type, size_bytes) VALUES (?,?,?,?,?,?)",
            (user_id, bot_id, filename, filepath, file_type, size),
        )
        await db.commit()


async def get_emoji(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM emoji_settings WHERE key=?", (key,)) as c:
            return await c.fetchone()


async def get_all_emojis():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM emoji_settings ORDER BY key") as c:
            return await c.fetchall()


async def update_emoji(key: str, custom_emoji_id: str, fallback: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO emoji_settings (key, custom_emoji_id, fallback, updated_at) VALUES (?,?,?,?)",
            (key, custom_emoji_id, fallback, datetime.now().isoformat()),
        )
        await db.commit()


async def get_button(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM button_settings WHERE key=?", (key,)) as c:
            return await c.fetchone()


async def get_all_buttons():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM button_settings ORDER BY key") as c:
            return await c.fetchall()


async def update_button(key: str, label: str, color: str, emoji_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO button_settings (key, label, color, emoji_key, updated_at) VALUES (?,?,?,?,?)",
            (key, label, color, emoji_key, datetime.now().isoformat()),
        )
        await db.commit()


async def get_text(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_texts WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default


async def get_all_texts():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bot_texts ORDER BY key") as c:
            return await c.fetchall()


async def update_text(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE bot_texts SET value=?, updated_at=? WHERE key=?",
            (value, datetime.now().isoformat(), key),
        )
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES (?,?,?)",
            (key, value, datetime.now().isoformat()),
        )
        await db.commit()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE plan='premium'") as c:
            premium_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM bots") as c:
            total_bots = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM bots WHERE status='running'") as c:
            running_bots = (await c.fetchone())[0]
        today = datetime.now().strftime("%Y-%m-%d")
        async with db.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)) as c:
            daily_registrations = (await c.fetchone())[0]
    return {
        "total_users": total_users, "premium_users": premium_users,
        "total_bots": total_bots, "running_bots": running_bots,
        "daily_registrations": daily_registrations,
    }


async def add_transaction(user_id, type_, amount, description):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES (?,?,?,?)",
            (user_id, type_, amount, description),
        )
        await db.commit()


async def add_broadcast_stat(admin_id, target, total, sent, failed):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO broadcast_stats (admin_id, target, total, sent, failed) VALUES (?,?,?,?,?)",
            (admin_id, target, total, sent, failed),
        )
        await db.commit()


async def get_broadcast_stats(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM broadcast_stats ORDER BY created_at DESC LIMIT ?", (limit,)) as c:
            return await c.fetchall()


async def log_admin_action(admin_id, action, target_id=0, details=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO admin_log (admin_id, action, target_id, details) VALUES (?,?,?,?)",
            (admin_id, action, target_id, details),
        )
        await db.commit()

# ══════════════════════════════════════════════════════════════════
# UTILS — HELPERS
# ══════════════════════════════════════════════════════════════════

class _SafeDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"


def safe_format(template: str, **kwargs) -> str:
    try:
        return template.format_map(_SafeDict(**kwargs))
    except Exception:
        return template


async def resolve_emojis(text: str) -> str:
    """Replace [EMJ:key] with <tg-emoji> tags for premium emoji support."""
    pattern = re.compile(r"\[EMJ:(\w+)\]")
    result, last = "", 0
    for m in pattern.finditer(text):
        result += text[last:m.start()]
        key = m.group(1)
        row = await get_emoji(key)
        if row and row["custom_emoji_id"] and row["custom_emoji_id"] not in ("", "0"):
            fallback = html_mod.escape(row["fallback"] or "⭐")
            result += f'<tg-emoji emoji-id="{row["custom_emoji_id"]}">{fallback}</tg-emoji>'
        else:
            result += (row["fallback"] if row else "⭐")
        last = m.end()
    result += text[last:]
    return result


async def get_btn_emoji(key: str) -> str:
    row = await get_emoji(key)
    return row["fallback"] if row else "⭐"

# ══════════════════════════════════════════════════════════════════
# UTILS — PROCESS MANAGER
# ══════════════════════════════════════════════════════════════════

running_processes: dict[int, asyncio.subprocess.Process] = {}
log_buffers:       dict[int, list[str]] = {}
MAX_LOG_LINES = 500
_notify_cb = None


def set_notify_callback(cb):
    global _notify_cb
    _notify_cb = cb


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _build_cmd(bot_type: str, main_file: str, folder: str) -> list[str]:
    if bot_type == "nodejs":
        pkg_path = os.path.join(folder, "package.json")
        if os.path.exists(pkg_path):
            try:
                data = json.loads(open(pkg_path).read())
                if data.get("scripts", {}).get("start"):
                    return ["npm", "start"]
            except Exception:
                pass
        node = shutil.which("node") or "node"
        return [node, main_file]
    return [sys.executable, main_file]


async def _install_deps(folder: str, bot_type: str):
    if bot_type == "nodejs":
        pkg = os.path.join(folder, "package.json")
        if os.path.exists(pkg) and shutil.which("npm"):
            p = await asyncio.create_subprocess_exec(
                "npm", "install", "--prefer-offline", cwd=folder,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await p.communicate()
    else:
        req = os.path.join(folder, "requirements.txt")
        if os.path.exists(req):
            p = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", req, "--quiet", cwd=folder,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await p.communicate()


async def _monitor_output(bot_id: int, proc: asyncio.subprocess.Process):
    if bot_id not in log_buffers:
        log_buffers[bot_id] = []
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            log_buffers[bot_id].append(f"[{_ts()}] {decoded}")
            if len(log_buffers[bot_id]) > MAX_LOG_LINES:
                log_buffers[bot_id] = log_buffers[bot_id][-MAX_LOG_LINES:]
    except Exception:
        pass


async def _monitor_process(bot_id, proc, user_id, bot_name):
    await proc.wait()
    running_processes.pop(bot_id, None)
    if bot_id in log_buffers:
        log_buffers[bot_id].append(f"[{_ts()}] ❌ Process exited (code {proc.returncode})\n")
    await update_bot_status(bot_id, "stopped")


async def start_bot(bot_id: int) -> tuple[bool, str]:
    bot = await get_bot(bot_id)
    if not bot:
        return False, "Bot not found."
    proc = running_processes.get(bot_id)
    if proc and proc.returncode is None:
        return False, "Bot is already running."
    folder, main_file = bot["folder_path"], bot["main_file"]
    full_path = os.path.join(folder, main_file)
    bot_type = bot["bot_type"] if bot["bot_type"] else "python"
    if not os.path.exists(full_path):
        return False, f"Main file `{main_file}` not found."
    await _install_deps(folder, bot_type)
    log_buffers[bot_id] = [f"[{_ts()}] ▶️ Starting ({bot_type})...\n"]
    try:
        cmd = _build_cmd(bot_type, main_file, folder)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=folder,
        )
        running_processes[bot_id] = process
        await update_bot_status(bot_id, "running", process.pid)
        asyncio.create_task(_monitor_output(bot_id, process))
        asyncio.create_task(_monitor_process(bot_id, process, bot["user_id"], bot["bot_name"]))
        return True, f"Started! PID: {process.pid}"
    except Exception as e:
        log_buffers[bot_id].append(f"[{_ts()}] ❌ Failed: {e}\n")
        return False, f"Failed to start: {e}"


async def stop_bot(bot_id: int) -> tuple[bool, str]:
    proc = running_processes.get(bot_id)
    if not proc or proc.returncode is not None:
        running_processes.pop(bot_id, None)
        await update_bot_status(bot_id, "stopped")
        return False, "Bot was not running."
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        running_processes.pop(bot_id, None)
        await update_bot_status(bot_id, "stopped")
        if bot_id in log_buffers:
            log_buffers[bot_id].append(f"[{_ts()}] ⏹️ Stopped by user.\n")
        return True, "Bot stopped."
    except Exception as e:
        return False, f"Error: {e}"


async def restart_bot(bot_id: int) -> tuple[bool, str]:
    await stop_bot(bot_id)
    await asyncio.sleep(1)
    await increment_restart_count(bot_id)
    return await start_bot(bot_id)


async def get_bot_logs(bot_id: int, lines: int = 50) -> str:
    buf = log_buffers.get(bot_id, [])
    return "".join(buf[-lines:]) if buf else "No logs available yet."


async def get_bot_stats(bot_id: int) -> dict:
    proc = running_processes.get(bot_id)
    if not proc or proc.returncode is not None:
        return {"status": "stopped", "cpu": 0.0, "ram": 0.0, "uptime": "N/A"}
    try:
        ps  = psutil.Process(proc.pid)
        cpu = ps.cpu_percent(interval=0.1)
        mem = ps.memory_info().rss / 1024 / 1024
        uptime = str(datetime.now() - datetime.fromtimestamp(ps.create_time())).split(".")[0]
        return {"status": "running", "cpu": round(cpu, 1), "ram": round(mem, 1), "uptime": uptime}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"status": "stopped", "cpu": 0.0, "ram": 0.0, "uptime": "N/A"}


async def get_system_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=0.1)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    active = len([p for p in running_processes.values() if p.returncode is None])
    return {
        "cpu_percent":  round(cpu, 1),
        "ram_used_mb":  round(mem.used   / 1024 / 1024, 1),
        "ram_total_mb": round(mem.total  / 1024 / 1024, 1),
        "ram_percent":  round(mem.percent, 1),
        "disk_used_gb": round(disk.used  / 1024**3, 2),
        "disk_total_gb":round(disk.total / 1024**3, 2),
        "disk_percent": round(disk.percent, 1),
        "running_bots": active,
    }


def is_running(bot_id: int) -> bool:
    proc = running_processes.get(bot_id)
    return bool(proc and proc.returncode is None)


async def recover_on_startup():
    bots = await get_running_bots()
    recovered = 0
    for bot in bots:
        bid = bot["id"]
        await update_bot_status(bid, "stopped")
        ok, _ = await start_bot(bid)
        if ok:
            recovered += 1
        await asyncio.sleep(0.5)
    return recovered


async def watchdog_loop():
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL)
        try:
            bots = await get_running_bots()
            for bot in bots:
                bid = bot["id"]
                if not is_running(bid):
                    rc = bot["restart_count"] or 0
                    if rc < MAX_AUTO_RESTARTS:
                        await increment_restart_count(bid)
                        await start_bot(bid)
                        if _notify_cb:
                            try:
                                tmpl = await get_text(
                                    "bot_crashed_notify",
                                    "🔴 <b>Bot Crashed!</b>\n\n"
                                    "🤖 <code>{bot_name}</code> crashed.\n"
                                    "🔄 Auto-restarting (attempt {restart_count})",
                                )
                                msg = safe_format(tmpl, bot_name=bot["bot_name"], restart_count=rc + 1)
                                await _notify_cb(bot["user_id"], msg)
                            except Exception:
                                pass
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════
# UTILS — DECORATORS
# ══════════════════════════════════════════════════════════════════

def require_user(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return
        db_user = await get_user(user.id)
        if not db_user:
            await create_user(user.id, user.username or "", user.full_name or "")
            db_user = await get_user(user.id)
        if db_user and db_user["is_banned"]:
            await update.effective_message.reply_text("❌ You are banned from using this bot.")
            return
        if db_user and db_user["is_suspended"] and user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("⏸️ Your account is suspended. Contact support.")
            return
        maintenance = await get_setting("maintenance_mode", "0")
        if maintenance == "1" and user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("🔧 Bot is under maintenance. Please try again later.")
            return
        await touch_user(user.id)
        return await func(update, context, *args, **kwargs)
    return wrapper


def require_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("❌ Admin access required.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ══════════════════════════════════════════════════════════════════
# HANDLERS — START / MENU
# ══════════════════════════════════════════════════════════════════



def _btn(buttons: dict, key: str, default: str, cb: str) -> InlineKeyboardButton:
    b = buttons.get(key)
    label = b["label"] if b else default
    return InlineKeyboardButton(label, callback_data=cb)


async def _main_menu(is_admin: bool, buttons: dict) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn(buttons, "my_files",    "📁 My Files",    "my_files"),
            _btn(buttons, "upload_file", "📤 Upload File", "upload_file"),
        ],
        [
            _btn(buttons, "run_module",  "▶️ Run Bot",     "run_module"),
            _btn(buttons, "status",      "📊 Status",      "status_cmd"),
        ],
        [
            _btn(buttons, "my_logs",     "📋 My Logs",     "my_logs"),
            _btn(buttons, "upgrade",     "⭐ Buy Premium", "buy_premium"),
        ],
        [_btn(buttons, "support", "🆘 Support", "support_cmd")],
    ]
    if is_admin:
        rows.append([_btn(buttons, "admin_panel", "👑 Admin Panel 🔐", "admin_panel")])
    return InlineKeyboardMarkup(rows)


async def _welcome_text(user, db_user) -> str:
    sys_st = await get_system_stats()
    gst    = await get_stats()
    plan   = "⭐ Premium" if db_user and db_user["plan"] == "premium" else "Free"
    title_tmpl = await get_text("welcome_title", "🚀 <b>Welcome to {bot_name}!</b>")
    body_tmpl  = await get_text(
        "welcome_body",
        "Host your Python &amp; Node.js bots 24/7.\n\n"
        "✅ <b>Free:</b> {free_bots} bots · {free_ram}MB RAM\n"
        "⭐ <b>Premium:</b> {premium_bots} bots · {premium_ram}MB RAM\n\n"
        "👤 {user_name}  |  Plan: {plan}\n"
        "👥 Total users: {total_users}  |  🟢 Running: {running_bots}",
    )
    fmt = dict(
        bot_name=BOT_NAME,
        user_name=user.full_name or user.username or "User",
        plan=plan,
        free_bots=FREE_MAX_BOTS, free_ram=FREE_MAX_RAM_MB,
        premium_bots=PREMIUM_MAX_BOTS, premium_ram=PREMIUM_MAX_RAM_MB,
        total_users=gst["total_users"],
        running_bots=sys_st["running_bots"],
        support_username=await get_setting("support_username", "@support"),
        channel_link=await get_setting("channel_link", ""),
    )
    title = await resolve_emojis(safe_format(title_tmpl, **fmt))
    body  = await resolve_emojis(safe_format(body_tmpl,  **fmt))
    return f"{title}\n\n{body}"


@require_user
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = await get_user(user.id)
    msg     = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return
    btns     = {b["key"]: b for b in await get_all_buttons()}
    text     = await _welcome_text(user, db_user)
    kb       = await _main_menu(user.id in ADMIN_IDS, btns)
    photo_id = await get_setting("welcome_photo_id", "")
    send_kw  = dict(parse_mode="HTML", reply_markup=kb)
    try:
        if photo_id:
            await msg.reply_photo(photo=photo_id, caption=text, **send_kw)
        else:
            await msg.reply_text(text, **send_kw)
    except Exception:
        await msg.reply_text(text, **send_kw)


@require_user
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmpl = await get_text("help_text",
        "📖 <b>Help &amp; Commands</b>\n\n"
        "📁 /files — My hosted bots\n"
        "📤 /upload — Upload a bot (.py, .js, .zip)\n"
        "▶️ /run — Start / Stop / Restart\n"
        "📊 /status — Server stats\n"
        "📋 /logs — Live logs\n"
        "🔥 /upgrade — Upgrade to Premium\n"
        "🆘 /support — Contact support\n"
        "❌ /cancel — Cancel action",
    )
    text = await resolve_emojis(tmpl)
    await update.message.reply_text(text, parse_mode="HTML")


@require_user
async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st  = await get_system_stats()
    gst = await get_stats()
    user    = update.effective_user
    db_user = await get_user(user.id)
    bots    = await get_user_bots(user.id)
    running = sum(1 for b in bots if b["status"] == "running")
    plan    = "⭐ Premium" if db_user and db_user["plan"] == "premium" else "Free"

    def bar(v, m=100, n=10):
        f = int((v / m) * n) if m else 0
        return "█" * min(f, n) + "░" * (n - min(f, n))

    text = (
        f"📊 <b>Server Status</b>\n\n"
        f"⚙️ CPU:   {bar(st['cpu_percent'])} <code>{st['cpu_percent']}%</code>\n"
        f"💾 RAM:   {bar(st['ram_percent'])}  <code>{st['ram_used_mb']}/{st['ram_total_mb']} MB</code>\n"
        f"🗂️ Disk:  {bar(st['disk_percent'])} <code>{st['disk_used_gb']}/{st['disk_total_gb']} GB</code>\n"
        f"🤖 Running bots: <code>{st['running_bots']}</code>\n\n"
        f"<b>Your Account</b>\n"
        f"📋 Plan: <code>{plan}</code>\n"
        f"🤖 Your bots: <code>{len(bots)}</code>  🟢 Running: <code>{running}</code>\n"
        f"👥 Total users: <code>{gst['total_users']}</code>"
    )
    kb  = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]])
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


@require_user
async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sup  = await get_setting("support_username", "@support")
    chn  = await get_setting("channel_link", "")
    tmpl = await get_text("support_text",
        "🆘 <b>Support</b>\n\nNeed help? Contact:\n\n📩 {support_username}\n📢 {channel_link}")
    text = await resolve_emojis(safe_format(tmpl, support_username=sup, channel_link=chn, bot_name=BOT_NAME))
    kb   = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="main_menu")]])
    msg  = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


@require_user
async def premium_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title_t = await get_text("premium_title", "🔥 <b>Upgrade to Premium</b>")
    body_t  = await get_text("premium_body",
        "Unlock the full power of <b>{bot_name}</b>!\n\n"
        "🤖 Host up to <b>{premium_bots} bots</b>\n"
        "💾 <b>{premium_ram}MB</b> RAM each\n"
        "⚡ Priority resources\n📊 Advanced analytics\n🆘 Priority support")
    fmt   = dict(bot_name=BOT_NAME, premium_bots=PREMIUM_MAX_BOTS, premium_ram=PREMIUM_MAX_RAM_MB)
    title = await resolve_emojis(safe_format(title_t, **fmt))
    body  = await resolve_emojis(safe_format(body_t,  **fmt))
    text  = f"{title}\n\n{body}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ Monthly – {STARS_PRICE_MONTHLY} Stars", callback_data="buy_monthly")],
        [InlineKeyboardButton(f"⭐ Yearly – {STARS_PRICE_YEARLY} Stars",   callback_data="buy_yearly")],
        [InlineKeyboardButton("◀️ Back", callback_data="main_menu")],
    ])
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
    elif msg:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)

# ══════════════════════════════════════════════════════════════════
# HANDLERS — PAYMENTS
# ══════════════════════════════════════════════════════════════════

@require_user
async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "buy_monthly":
        amount, title, desc, payload, days = (
            STARS_PRICE_MONTHLY,
            f"Premium Monthly — {BOT_NAME}",
            f"Host up to {PREMIUM_MAX_BOTS} bots for 30 days with {PREMIUM_MAX_RAM_MB}MB RAM each.",
            "premium_monthly", 30,
        )
    else:
        amount, title, desc, payload, days = (
            STARS_PRICE_YEARLY,
            f"Premium Yearly — {BOT_NAME}",
            f"Host up to {PREMIUM_MAX_BOTS} bots for 365 days with {PREMIUM_MAX_RAM_MB}MB RAM each.",
            "premium_yearly", 365,
        )
    context.user_data["pending_plan_days"] = days
    try:
        await query.message.reply_invoice(
            title=title, description=desc, payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Premium Plan", amount=amount)],
        )
    except Exception as e:
        await query.message.reply_text(
            f"⚠️ Payment unavailable: {e}\n\nContact support to upgrade manually.", parse_mode="HTML"
        )


async def pre_checkout_handler(update: Update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment_handler(update: Update, context):
    user    = update.effective_user
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    stars   = payment.total_amount
    days    = 365 if "yearly" in payload else 30
    await update_user_plan(user.id, "premium", days)
    await add_transaction(user.id, "purchase", stars, f"Premium {days}d")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Start Hosting", callback_data="upload_file")],
        [InlineKeyboardButton("📊 Status",        callback_data="status_cmd")],
    ])
    await update.message.reply_text(
        f"🎉 <b>Payment Successful!</b>\n\n"
        f"⭐ You are now <b>Premium</b> for {days} days!\n"
        f"💎 {stars} Stars received\n\n"
        f"🚀 Host up to {PREMIUM_MAX_BOTS} bots with {PREMIUM_MAX_RAM_MB}MB RAM!",
        parse_mode="HTML", reply_markup=kb,
    )

# ══════════════════════════════════════════════════════════════════
# HANDLERS — FILES / BOT MANAGEMENT
# ══════════════════════════════════════════════════════════════════

WAITING_FILE = 1

def _max_bots(user) -> int:
    return PREMIUM_MAX_BOTS if user["plan"] == "premium" else FREE_MAX_BOTS

def _bar(value, max_val, n=8):
    f = int((value / max_val) * n) if max_val else 0
    return "█" * max(0, min(f, n)) + "░" * (n - max(0, min(f, n)))

def _detect_bot_type(folder, main_file):
    if os.path.exists(os.path.join(folder, "package.json")):
        return "nodejs"
    if main_file.endswith(".js"):
        return "nodejs"
    return "python"


@require_user
async def list_files_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bots = await get_user_bots(user.id)
    msg  = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return
    if not bots:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Upload Bot", callback_data="upload_file")]])
        await msg.reply_text("📁 <b>Your Hosted Bots</b>\n\nNo bots yet. Upload one to get started!",
                             parse_mode="HTML", reply_markup=kb)
        return
    text = "📁 <b>Your Hosted Bots</b>\n\n"
    kb   = []
    for bot in bots:
        icon = "🟢" if bot["status"] == "running" else "🔴"
        t    = "🐍" if (bot["bot_type"] or "python") == "python" else "🟨"
        text += f"{icon} {t} <code>{bot['bot_name']}</code>\n"
        kb.append([InlineKeyboardButton(f"🔧 {bot['bot_name']}", callback_data=f"bot_manage:{bot['id']}")])
    kb.append([InlineKeyboardButton("📤 Upload New Bot", callback_data="upload_file")])
    await msg.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


@require_user
async def upload_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = await get_user(user.id)
    bots    = await get_user_bots(user.id)
    max_b   = _max_bots(db_user)
    msg     = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return
    if len(bots) >= max_b and user.id not in ADMIN_IDS:
        tip = "" if db_user["plan"] == "premium" else f"\n\n⭐ Upgrade to Premium for {PREMIUM_MAX_BOTS} bot slots!"
        await msg.reply_text(f"❌ Bot limit reached (<b>{max_b}</b> bots).{tip}", parse_mode="HTML")
        return
    context.user_data["state"] = WAITING_FILE
    tmpl = await get_text("upload_prompt",
        "📤 <b>Upload Your Bot Files</b>\n\n"
        "Send me one of:\n• 🐍 Python file (<code>.py</code>)\n"
        "• 🟨 Node.js file (<code>.js</code>)\n• 📦 ZIP archive\n\n"
        "I'll auto-install <code>requirements.txt</code> or <code>package.json</code>!\n\nSend /cancel to abort.")
    await msg.reply_text(tmpl, parse_mode="HTML")


@require_user
async def receive_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    db_user = await get_user(user.id)
    doc     = update.message.document
    if not doc:
        await update.message.reply_text("❌ Please send a file (.py, .js, .zip)")
        return
    fname = doc.file_name or "uploaded_file"
    ext   = os.path.splitext(fname)[1].lower()
    if ext not in [".py", ".js", ".zip", ".txt", ".json", ".env"]:
        await update.message.reply_text("❌ Unsupported type. Send <code>.py</code>, <code>.js</code>, or <code>.zip</code>", parse_mode="HTML")
        return
    bots  = await get_user_bots(user.id)
    max_b = _max_bots(db_user)
    if len(bots) >= max_b and user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Bot limit reached! Upgrade to Premium for more slots.")
        return
    processing = await update.message.reply_text("⏳ Processing your file...")
    os.makedirs(USER_BOTS_DIR, exist_ok=True)
    folder_name = f"user_{user.id}_bot_{len(bots) + 1}"
    folder      = os.path.join(USER_BOTS_DIR, folder_name)
    os.makedirs(folder, exist_ok=True)
    tg_file   = await doc.get_file()
    temp_path = os.path.join(folder, fname)
    await tg_file.download_to_drive(temp_path)
    main_file = None
    if ext == ".zip":
        try:
            with zipfile.ZipFile(temp_path, "r") as zf:
                zf.extractall(folder)
            os.remove(temp_path)
            files_in = os.listdir(folder)
            if "package.json" in files_in:
                js_candidates = ["index.js", "app.js", "bot.js", "main.js", "server.js"]
                js_files = [f for f in files_in if f.endswith(".js")]
                for c in js_candidates:
                    if c in js_files:
                        main_file = c
                        break
                if not main_file and js_files:
                    main_file = js_files[0]
            if not main_file:
                py_files = [f for f in files_in if f.endswith(".py")]
                for c in ["main.py", "bot.py", "app.py", "run.py", "index.py"]:
                    if c in py_files:
                        main_file = c
                        break
                if not main_file and py_files:
                    main_file = py_files[0]
            if not main_file:
                js_files = [f for f in files_in if f.endswith(".js")]
                if js_files:
                    main_file = js_files[0]
        except zipfile.BadZipFile:
            await processing.edit_text("❌ Invalid ZIP file.")
            shutil.rmtree(folder, ignore_errors=True)
            return
    else:
        main_file = fname
    if not main_file:
        await processing.edit_text("❌ No Python or Node.js files found.")
        shutil.rmtree(folder, ignore_errors=True)
        return
    bot_type = _detect_bot_type(folder, main_file)
    bot_name = os.path.splitext(fname)[0].replace("_", " ").title()
    bot_id   = await create_bot(user.id, bot_name, main_file, folder, bot_type)
    await add_file(user.id, bot_id, fname, temp_path if ext != ".zip" else folder, ext, doc.file_size or 0)
    type_icon = "🟨" if bot_type == "nodejs" else "🐍"
    has_deps  = (
        os.path.exists(os.path.join(folder, "requirements.txt")) or
        os.path.exists(os.path.join(folder, "package.json"))
    )
    dep_note = "\n✅ Dependencies file found — auto-installing on run!" if has_deps else ""
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Run Bot", callback_data=f"bot_start:{bot_id}"),
            InlineKeyboardButton("📁 Files",   callback_data=f"bot_files:{bot_id}"),
        ],
        [InlineKeyboardButton("⚙️ Manage", callback_data=f"bot_manage:{bot_id}")],
    ])
    await processing.edit_text(
        f"✅ <b>Bot uploaded!</b>\n\n"
        f"📛 Name: <code>{bot_name}</code>\n"
        f"{type_icon} Type: <code>{'Node.js' if bot_type == 'nodejs' else 'Python'}</code>\n"
        f"📄 Main: <code>{main_file}</code>{dep_note}\n\nPress ▶️ Run Bot to start!",
        parse_mode="HTML", reply_markup=kb
    )


@require_user
async def bot_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        await query.message.reply_text("❌ Bot not found or access denied.")
        return
    stats    = await get_bot_stats(bot_id)
    status_i = "🟢" if bot["status"] == "running" else "🔴"
    bot_type = bot["bot_type"] or "python"
    type_i   = "🟨" if bot_type == "nodejs" else "🐍"
    cpu_bar  = _bar(stats["cpu"], 100)
    ram_bar  = _bar(stats["ram"], 512)
    text = (
        f"🤖 <b>{bot['bot_name']}</b>\n\n"
        f"{status_i} Status: <code>{bot['status'].upper()}</code>\n"
        f"{type_i} Type: <code>{'Node.js' if bot_type == 'nodejs' else 'Python'}</code>\n"
        f"📄 Main: <code>{bot['main_file']}</code>\n"
        f"🔁 Restarts: <code>{bot['restart_count']}</code>\n"
        f"💥 Crashes: <code>{bot['crash_count'] or 0}</code>\n"
        f"⏱️ Uptime: <code>{stats['uptime']}</code>\n"
        f"⚙️ CPU: {cpu_bar} <code>{stats['cpu']}%</code>\n"
        f"💾 RAM: {ram_bar} <code>{stats['ram']} MB</code>\n"
        f"🔄 Auto-restart: <code>{'ON' if bot['auto_restart'] else 'OFF'}</code>"
    )
    if bot["status"] == "running":
        action_row = [
            InlineKeyboardButton("⏹️ Stop",    callback_data=f"bot_stop:{bot_id}"),
            InlineKeyboardButton("🔄 Restart", callback_data=f"bot_restart:{bot_id}"),
        ]
    else:
        action_row = [InlineKeyboardButton("▶️ Start", callback_data=f"bot_start:{bot_id}")]
    ar_lbl = "🔄 Auto: OFF" if bot["auto_restart"] else "🔄 Auto: ON"
    kb = InlineKeyboardMarkup([
        action_row,
        [
            InlineKeyboardButton("📋 Logs",  callback_data=f"bot_logs:{bot_id}"),
            InlineKeyboardButton("📁 Files", callback_data=f"bot_files:{bot_id}"),
        ],
        [InlineKeyboardButton(ar_lbl, callback_data=f"bot_toggle_ar:{bot_id}")],
        [InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"bot_delete_confirm:{bot_id}")],
        [InlineKeyboardButton("◀️ Back",       callback_data="my_files")],
    ])
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@require_user
async def bot_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    ok, msg = await start_bot(bot_id)
    await query.answer(f"{'✅' if ok else '❌'} {msg}", show_alert=True)
    await bot_manage_callback(update, context)


@require_user
async def bot_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    ok, msg_text = await stop_bot(bot_id)
    await query.answer(f"{'✅' if ok else '❌'} {msg_text}", show_alert=True)
    await bot_manage_callback(update, context)


@require_user
async def bot_restart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    ok, msg_text = await restart_bot(bot_id)
    await query.answer(f"{'✅' if ok else '❌'} {msg_text}", show_alert=True)
    await bot_manage_callback(update, context)


@require_user
async def bot_toggle_ar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    new_val = not bool(bot["auto_restart"])
    await set_bot_auto_restart(bot_id, new_val)
    await query.answer(f"Auto-restart {'enabled' if new_val else 'disabled'}", show_alert=True)
    await bot_manage_callback(update, context)


@require_user
async def bot_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        await query.message.reply_text("❌ Access denied.")
        return
    logs = await get_bot_logs(bot_id, lines=40)
    logs_safe = html_mod.escape(logs) if logs else "No logs available."
    text = f"📋 <b>Logs: {bot['bot_name']}</b>\n\n<pre>{logs_safe}</pre>"
    if len(text) > 4000:
        text = text[:3990] + "\n…</pre>"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"bot_logs:{bot_id}")],
        [InlineKeyboardButton("◀️ Back",    callback_data=f"bot_manage:{bot_id}")],
    ])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


@require_user
async def bot_files_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        await query.message.reply_text("❌ Access denied.")
        return
    folder = bot["folder_path"]
    files  = []
    if os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            fp = os.path.join(folder, f)
            if os.path.isfile(fp):
                files.append((f, os.path.getsize(fp)))
    if not files:
        await query.message.edit_text(
            "📁 No files found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=f"bot_manage:{bot_id}")]])
        )
        return
    text = f"📁 <b>Files — {html_mod.escape(bot['bot_name'])}</b>\n\n"
    kb   = []
    for fname, size in files:
        sz   = f"{size}B" if size < 1024 else f"{size//1024}KB"
        text += f"📄 <code>{html_mod.escape(fname)}</code> ({sz})\n"
        if fname.endswith((".py", ".js", ".txt", ".json", ".env", ".cfg", ".ini", ".yaml")):
            kb.append([InlineKeyboardButton(f"✏️ Edit {fname}", callback_data=f"edit_file:{bot_id}:{fname}")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data=f"bot_manage:{bot_id}")])
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


@require_user
async def edit_file_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split(":", 2)
    bot_id = int(parts[1])
    fname  = parts[2]
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        await query.message.reply_text("❌ Access denied.")
        return
    filepath = os.path.join(bot["folder_path"], fname)
    if not os.path.exists(filepath):
        await query.message.reply_text("❌ File not found.")
        return
    try:
        async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
            content = await f.read()
    except Exception:
        await query.message.reply_text("❌ Cannot read file (binary?).")
        return
    preview = content[:3000] + ("\n…(truncated)" if len(content) > 3000 else "")
    context.user_data["editing_bot_id"]   = bot_id
    context.user_data["editing_filename"] = fname
    context.user_data["editing_filepath"] = filepath
    await query.message.reply_text(
        f"✏️ <b>Editing: <code>{html_mod.escape(fname)}</code></b>\n\n"
        f"Current content:\n<pre>{html_mod.escape(preview)}</pre>\n\nSend the new content, or /cancel to abort.",
        parse_mode="HTML"
    )


@require_user
async def receive_edit_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "editing_filepath" not in context.user_data:
        return
    filepath = context.user_data.pop("editing_filepath")
    fname    = context.user_data.pop("editing_filename")
    bot_id   = context.user_data.pop("editing_bot_id")
    new_content = update.message.text
    try:
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(new_content)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📁 Back to Files", callback_data=f"bot_files:{bot_id}")]])
        await update.message.reply_text(f"✅ <code>{fname}</code> saved!", parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to save: {e}")


@require_user
async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Yes, Delete", callback_data=f"bot_delete_do:{bot_id}"),
            InlineKeyboardButton("❌ Cancel",       callback_data=f"bot_manage:{bot_id}"),
        ]
    ])
    await query.message.edit_text(
        f"⚠️ <b>Delete <code>{html_mod.escape(bot['bot_name'])}</code>?</b>\n\n"
        "This will permanently delete all files and stop the bot.",
        parse_mode="HTML", reply_markup=kb
    )


@require_user
async def delete_do_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    bot_id = int(query.data.split(":")[1])
    user   = update.effective_user
    bot    = await get_bot(bot_id)
    if not bot or (bot["user_id"] != user.id and user.id not in ADMIN_IDS):
        return
    await stop_bot(bot_id)
    shutil.rmtree(bot["folder_path"], ignore_errors=True)
    await delete_bot(bot_id)
    await query.message.edit_text(
        f"🗑️ <b>{html_mod.escape(bot['bot_name'])}</b> deleted.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📁 My Files", callback_data="my_files")]])
    )

# ══════════════════════════════════════════════════════════════════
# HANDLERS — ADMIN PANEL
# ══════════════════════════════════════════════════════════════════

@require_admin
async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    st  = await get_stats()
    text = (
        f"👑 <b>Admin Panel</b>\n\n"
        f"👥 Total users: <code>{st['total_users']}</code>\n"
        f"⭐ Premium users: <code>{st['premium_users']}</code>\n"
        f"🤖 Total bots: <code>{st['total_bots']}</code>\n"
        f"🟢 Running: <code>{st['running_bots']}</code>\n"
        f"📅 Today's joins: <code>{st['daily_registrations']}</code>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Users",     callback_data="admin_users"),
            InlineKeyboardButton("⭐ Premium",   callback_data="admin_premium"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("📊 Stats",     callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton("📝 Texts",     callback_data="admin_texts"),
            InlineKeyboardButton("😀 Emojis",    callback_data="admin_emojis"),
        ],
        [
            InlineKeyboardButton("🎨 Buttons",   callback_data="admin_buttons"),
            InlineKeyboardButton("⚙️ Settings",  callback_data="admin_settings"),
        ],
        [
            InlineKeyboardButton("🔧 Maint. ON",  callback_data="admin_maint_on"),
            InlineKeyboardButton("🔧 Maint. OFF", callback_data="admin_maint_off"),
        ],
    ])
    if msg:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sys_st = await get_system_stats()
    gst    = await get_stats()

    def bar(v, m=100, n=10):
        f = int((v / m) * n) if m else 0
        return "█" * min(f, n) + "░" * (n - min(f, n))

    text = (
        f"📊 <b>Admin Stats</b>\n\n"
        f"<b>Users</b>\n"
        f"👥 Total: <code>{gst['total_users']}</code>\n"
        f"⭐ Premium: <code>{gst['premium_users']}</code>\n"
        f"📅 Today: <code>{gst['daily_registrations']}</code>\n\n"
        f"<b>Bots</b>\n"
        f"🤖 Total hosted: <code>{gst['total_bots']}</code>\n"
        f"🟢 Running: <code>{gst['running_bots']}</code>\n"
        f"🔴 Stopped: <code>{gst['total_bots'] - gst['running_bots']}</code>\n\n"
        f"<b>Server</b>\n"
        f"⚙️ CPU:  {bar(sys_st['cpu_percent'])} <code>{sys_st['cpu_percent']}%</code>\n"
        f"💾 RAM:  {bar(sys_st['ram_percent'])}  <code>{sys_st['ram_used_mb']}/{sys_st['ram_total_mb']} MB</code>\n"
        f"🗂️ Disk: {bar(sys_st['disk_percent'])} <code>{sys_st['disk_used_gb']}/{sys_st['disk_total_gb']} GB</code>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="admin_panel")]])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = await get_all_users()
    text  = f"👥 <b>Users</b> ({len(users)} total)\n\nSelect action:"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 List All",  callback_data="admin_users_list:0"),
            InlineKeyboardButton("🔍 Search",    callback_data="admin_users_search"),
        ],
        [
            InlineKeyboardButton("⭐ Premium",   callback_data="admin_users_premium"),
            InlineKeyboardButton("🔴 Banned",    callback_data="admin_users_banned"),
        ],
        [InlineKeyboardButton("◀️ Back", callback_data="admin_panel")],
    ])
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_users_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    page   = int(query.data.split(":")[1])
    users  = await get_all_users()
    PER    = 8
    start  = page * PER
    chunk  = list(users)[start:start + PER]
    text   = f"👥 <b>Users</b> (page {page + 1}/{max(1, -(-len(users) // PER))})\n\n"
    kb     = []
    for u in chunk:
        plan_i = "⭐" if u["plan"] == "premium" else "🆓"
        ban_i  = " 🚫" if u["is_banned"] else (" ⏸️" if u["is_suspended"] else "")
        name   = html_mod.escape(u["full_name"] or u["username"] or str(u["user_id"]))
        text  += f"{plan_i} <code>{u['user_id']}</code> — {name}{ban_i}\n"
        kb.append([InlineKeyboardButton(f"👤 {name[:20]}", callback_data=f"admin_user_view:{u['user_id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_users_list:{page-1}"))
    if start + PER < len(users):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_users_list:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_users")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_users_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "search_user"
    await query.message.reply_text("🔍 <b>Search User</b>\n\nSend a username, name, or user ID:", parse_mode="HTML")


async def admin_user_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    u       = await get_user(user_id)
    if not u:
        await query.message.reply_text("❌ User not found.")
        return
    bots    = await get_user_bots(user_id)
    running = sum(1 for b in bots if b["status"] == "running")
    plan_expires = ""
    if u["plan_expires"]:
        try:
            exp = datetime.fromisoformat(u["plan_expires"])
            days_left = (exp - datetime.now()).days
            plan_expires = f"\n⏰ Expires: <code>{exp.strftime('%Y-%m-%d')}</code> ({days_left}d)"
        except Exception:
            pass
    name = html_mod.escape(u["full_name"] or u["username"] or str(u["user_id"]))
    text = (
        f"👤 <b>User Profile</b>\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n"
        f"👤 Name: {name}\n"
        f"📛 Username: @{html_mod.escape(u['username'] or 'N/A')}\n"
        f"📋 Plan: <code>{u['plan'].upper()}</code>{plan_expires}\n"
        f"🤖 Bots: <code>{len(bots)}</code>  🟢 Running: <code>{running}</code>\n"
        f"🚫 Banned: <code>{'Yes' if u['is_banned'] else 'No'}</code>\n"
        f"⏸️ Suspended: <code>{'Yes' if u['is_suspended'] else 'No'}</code>\n"
        f"📅 Joined: <code>{u['joined_at'][:10] if u['joined_at'] else 'N/A'}</code>\n"
        f"🕐 Last active: <code>{u['last_activity'][:16] if u['last_activity'] else 'N/A'}</code>"
    )
    ban_btn = (
        InlineKeyboardButton("✅ Unban", callback_data=f"admin_unban:{user_id}")
        if u["is_banned"] else
        InlineKeyboardButton("🚫 Ban",   callback_data=f"admin_ban:{user_id}")
    )
    sus_btn = (
        InlineKeyboardButton("▶️ Unsuspend", callback_data=f"admin_unsuspend:{user_id}")
        if u["is_suspended"] else
        InlineKeyboardButton("⏸️ Suspend",   callback_data=f"admin_suspend:{user_id}")
    )
    kb = InlineKeyboardMarkup([
        [ban_btn, sus_btn],
        [
            InlineKeyboardButton("⭐ Give Premium",  callback_data=f"admin_give_premium:{user_id}"),
            InlineKeyboardButton("❌ Remove Premium", callback_data=f"admin_remove_premium:{user_id}"),
        ],
        [
            InlineKeyboardButton("🤖 View Bots",   callback_data=f"admin_user_bots:{user_id}"),
            InlineKeyboardButton("🗑️ Delete Data", callback_data=f"admin_delete_data:{user_id}"),
        ],
        [InlineKeyboardButton("◀️ Back", callback_data="admin_users_list:0")],
    ])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_user_bots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[1])
    bots    = await get_user_bots(user_id)
    text    = f"🤖 <b>Bots of user {user_id}</b>\n\n"
    kb      = []
    for bot in bots:
        icon = "🟢" if bot["status"] == "running" else "🔴"
        text += f"{icon} <code>{html_mod.escape(bot['bot_name'])}</code> — {bot['status']}\n"
        kb.append([InlineKeyboardButton(f"🔧 {bot['bot_name'][:25]}", callback_data=f"bot_manage:{bot['id']}")])
    if not bots:
        text += "No bots yet."
    kb.append([InlineKeyboardButton("◀️ Back", callback_data=f"admin_user_view:{user_id}")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = int(query.data.split(":")[1])
    action = "ban" if "admin_ban:" in query.data else "unban"
    await ban_user(uid, action == "ban")
    await log_admin_action(update.effective_user.id, action, uid)
    await query.answer(f"User {'banned' if action=='ban' else 'unbanned'}.", show_alert=True)
    query.data = f"admin_user_view:{uid}"
    await admin_user_view_callback(update, context)


async def admin_suspend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    uid    = int(query.data.split(":")[1])
    action = "suspend" if "admin_suspend:" in query.data else "unsuspend"
    await suspend_user(uid, action == "suspend")
    await log_admin_action(update.effective_user.id, action, uid)
    await query.answer(f"User {'suspended' if action=='suspend' else 'unsuspended'}.", show_alert=True)
    query.data = f"admin_user_view:{uid}"
    await admin_user_view_callback(update, context)


async def admin_delete_data_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = int(query.data.split(":")[1])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚠️ Confirm Delete", callback_data=f"admin_delete_data_do:{uid}"),
        InlineKeyboardButton("❌ Cancel",          callback_data=f"admin_user_view:{uid}"),
    ]])
    await query.message.reply_text(
        f"⚠️ Delete ALL bot data for user <code>{uid}</code>?\nThis removes all hosted bots and files.",
        parse_mode="HTML", reply_markup=kb
    )


async def admin_delete_data_do_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = int(query.data.split(":")[1])
    bots  = await get_user_bots(uid)
    for bot in bots:
        bid = bot["id"]
        proc = running_processes.get(bid)
        if proc and proc.returncode is None:
            proc.terminate()
        running_processes.pop(bid, None)
        log_buffers.pop(bid, None)
    await delete_user_data(uid)
    await log_admin_action(update.effective_user.id, "delete_data", uid)
    await query.answer("Data deleted.", show_alert=True)
    await query.message.reply_text(f"🗑️ All data deleted for user <code>{uid}</code>.", parse_mode="HTML")


async def admin_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    users = await get_users_by_plan("premium")
    text  = f"⭐ <b>Premium Users</b> ({len(users)} active)\n\n"
    kb    = []
    for u in users[:15]:
        name  = html_mod.escape(u["full_name"] or u["username"] or str(u["user_id"]))
        exp   = u["plan_expires"][:10] if u["plan_expires"] else "∞"
        text += f"• <code>{u['user_id']}</code> {name} — expires: {exp}\n"
        kb.append([InlineKeyboardButton(f"👤 {name[:22]}", callback_data=f"admin_user_view:{u['user_id']}")])
    kb.append([InlineKeyboardButton("➕ Give Premium by ID", callback_data="admin_give_premium_id")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_panel")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_give_premium_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "give_premium_id"
    await query.message.reply_text(
        "⭐ <b>Give Premium by User ID</b>\n\nSend the user ID:\n\nExample: <code>123456789</code>\n\n/cancel to abort.",
        parse_mode="HTML"
    )


async def admin_give_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    uid     = int(query.data.split(":")[1])
    context.user_data["admin_state"] = f"give_premium:{uid}"
    await query.message.reply_text(
        f"⭐ <b>Give Premium to <code>{uid}</code></b>\n\nSend number of days (e.g. <code>30</code>, <code>365</code>):",
        parse_mode="HTML"
    )


async def admin_remove_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid   = int(query.data.split(":")[1])
    await update_user_plan(uid, "free", 0)
    await log_admin_action(update.effective_user.id, "remove_premium", uid)
    await query.answer("Premium removed.", show_alert=True)
    query.data = f"admin_user_view:{uid}"
    await admin_user_view_callback(update, context)


async def admin_users_banned_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    users  = await get_all_users()
    banned = [u for u in users if u["is_banned"]]
    text   = f"🚫 <b>Banned Users</b> ({len(banned)})\n\n"
    kb     = []
    for u in banned[:15]:
        name = html_mod.escape(u["full_name"] or u["username"] or str(u["user_id"]))
        text += f"• <code>{u['user_id']}</code> {name}\n"
        kb.append([InlineKeyboardButton(f"👤 {name[:22]}", callback_data=f"admin_user_view:{u['user_id']}")])
    if not banned:
        text += "No banned users."
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_users")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stats = await get_broadcast_stats(5)
    text  = "📢 <b>Broadcast</b>\n\nSend message to all or selected users.\n\n"
    if stats:
        text += "<b>Recent broadcasts:</b>\n"
        for s in stats:
            text += f"• {s['target']} — {s['sent']}/{s['total']} sent, {s['failed']} failed [{s['created_at'][:10]}]\n"
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 All Users", callback_data="broadcast_all"),
            InlineKeyboardButton("⭐ Premium",   callback_data="broadcast_premium"),
        ],
        [InlineKeyboardButton("📊 Broadcast Stats", callback_data="broadcast_stats")],
        [InlineKeyboardButton("◀️ Back", callback_data="admin_panel")],
    ])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    target = "all" if query.data == "broadcast_all" else "premium"
    context.user_data["admin_state"] = f"broadcast:{target}"
    await query.message.reply_text(
        f"📢 <b>Broadcast to {target} users</b>\n\nSend the message (HTML supported, /cancel to abort):",
        parse_mode="HTML"
    )


async def broadcast_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stats = await get_broadcast_stats(10)
    text  = "📊 <b>Broadcast History</b>\n\n"
    if not stats:
        text += "No broadcasts yet."
    for s in stats:
        text += f"📅 {s['created_at'][:10]}  Target: <b>{s['target']}</b>\n   Sent: {s['sent']}/{s['total']} | Failed: {s['failed']}\n\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="admin_broadcast")]])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def _do_broadcast(app, target: str, message: str, admin_id: int):
    if target == "premium":
        users = await get_users_by_plan("premium")
    else:
        users = await get_all_users()
    users = [u for u in users if not u["is_banned"] and not u["is_suspended"]]
    total, sent, failed = len(users), 0, 0
    for u in users:
        try:
            await app.bot.send_message(u["user_id"], message, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await add_broadcast_stat(admin_id, target, total, sent, failed)
    return sent, failed


async def admin_texts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    texts = await get_all_texts()
    text  = "📝 <b>Edit Texts</b>\n\nSelect a text to edit:"
    kb    = []
    for t in texts:
        kb.append([InlineKeyboardButton(f"📄 {t['key']}", callback_data=f"admin_edit_text:{t['key']}")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_panel")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_edit_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key   = query.data.split(":", 1)[1]
    texts = {t["key"]: t for t in await get_all_texts()}
    t     = texts.get(key)
    if not t:
        await query.message.reply_text("❌ Text not found.")
        return
    current = html_mod.escape(t["value"] or "")
    desc    = html_mod.escape(t["description"] or "")
    context.user_data["admin_state"]    = f"edit_text:{key}"
    context.user_data["admin_edit_key"] = key
    await query.message.reply_text(
        f"📝 <b>Editing:</b> <code>{html_mod.escape(key)}</code>\n<i>{desc}</i>\n\n"
        f"<b>Current:</b>\n<code>{current}</code>\n\n"
        "💡 Use <code>[EMJ:key]</code> for premium emojis\n\nSend new text (/cancel to abort):",
        parse_mode="HTML"
    )


async def admin_emojis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    emojis = await get_all_emojis()
    text   = "😀 <b>Custom Emojis</b>\n\nSet Telegram Premium emoji IDs:\n\n"
    for e in emojis:
        has = "✅" if e["custom_emoji_id"] and e["custom_emoji_id"] != "0" else "⬜"
        text += f"{has} <code>{e['key']}</code> → {html_mod.escape(e['fallback'] or '')}\n"
    text += "\n💡 Use <code>[EMJ:key]</code> in texts to insert them."
    kb = []
    for e in emojis:
        kb.append([InlineKeyboardButton(f"✏️ {e['key']} {e['fallback'] or ''}", callback_data=f"admin_edit_emoji:{e['key']}")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_panel")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_edit_emoji_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key   = query.data.split(":")[1]
    context.user_data["admin_state"]      = f"edit_emoji:{key}"
    context.user_data["admin_edit_emoji"] = key
    await query.message.reply_text(
        f"😀 <b>Edit Emoji:</b> <code>{html_mod.escape(key)}</code>\n\n"
        "Send: <code>EMOJI_ID | fallback_char</code>\n\n"
        "Example: <code>5307659638810877853 | ⭐</code>\n\n"
        "💡 Get Premium emoji IDs via @getidsbot\n\n/cancel to abort.",
        parse_mode="HTML"
    )


async def admin_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    buttons = await get_all_buttons()
    text    = "🎨 <b>Edit Buttons</b>\n\nSelect a button to edit:"
    kb      = []
    for b in buttons:
        kb.append([InlineKeyboardButton(f"🔘 {b['key']} — {b['label']} [{b['color']}]", callback_data=f"admin_edit_button:{b['key']}")])
    kb.append([InlineKeyboardButton("◀️ Back", callback_data="admin_panel")])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


async def admin_edit_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    key     = query.data.split(":")[1]
    buttons = {b["key"]: b for b in await get_all_buttons()}
    b       = buttons.get(key)
    if not b:
        await query.message.reply_text("❌ Button not found.")
        return
    context.user_data["admin_state"]       = f"edit_button:{key}"
    context.user_data["admin_edit_button"] = key
    await query.message.reply_text(
        f"🔘 <b>Edit Button:</b> <code>{html_mod.escape(key)}</code>\n\n"
        f"Current: <code>{html_mod.escape(b['label'])}</code> | Color: <code>{b['color']}</code>\n\n"
        "Send: <code>Label | color</code>\n"
        "Colors: <code>primary</code> (🔵), <code>success</code> (🟢), <code>danger</code> (🔴)\n\n"
        "Example: <code>📁 My Files | primary</code>\n\n/cancel to abort.",
        parse_mode="HTML"
    )


async def admin_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    photo_id = await get_setting("welcome_photo_id", "")
    support  = await get_setting("support_username", "@support")
    channel  = await get_setting("channel_link", "")
    maint    = await get_setting("maintenance_mode", "0")
    text = (
        f"⚙️ <b>Settings</b>\n\n"
        f"📸 Welcome photo: <code>{'Set ✅' if photo_id else 'Not set'}</code>\n"
        f"🆘 Support: <code>{html_mod.escape(support)}</code>\n"
        f"📢 Channel: <code>{html_mod.escape(channel)}</code>\n"
        f"🔧 Maintenance: <code>{'ON' if maint=='1' else 'OFF'}</code>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📸 Set Photo",    callback_data="admin_set_photo"),
            InlineKeyboardButton("🆘 Support Link", callback_data="admin_set_support"),
        ],
        [InlineKeyboardButton("📢 Channel Link",    callback_data="admin_set_channel")],
        [InlineKeyboardButton("◀️ Back",            callback_data="admin_panel")],
    ])
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_set_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "set_photo"
    await query.message.reply_text("📸 Send the welcome photo (or send /cancel to remove):")


async def admin_set_support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "set_support"
    await query.message.reply_text("🆘 Send new support username (e.g. @YourUsername):")


async def admin_set_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "set_channel"
    await query.message.reply_text("📢 Send new channel link (e.g. https://t.me/yourchannel):")


async def admin_maint_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = "1" if query.data == "admin_maint_on" else "0"
    await set_setting("maintenance_mode", val)
    await log_admin_action(update.effective_user.id, f"maintenance_{val}")
    status = "ON 🔧" if val == "1" else "OFF ✅"
    await query.answer(f"Maintenance mode: {status}", show_alert=True)
    await admin_panel_handler(update, context)


@require_admin
async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("admin_state", "")
    text  = update.message.text.strip()
    if not state:
        return

    if state == "search_user":
        context.user_data.pop("admin_state", None)
        results = await search_users(text)
        if not results:
            await update.message.reply_text("❌ No users found.")
            return
        msg_text = f"🔍 <b>Search Results</b> for <code>{html_mod.escape(text)}</code>\n\n"
        kb = []
        for u in results:
            name   = html_mod.escape(u["full_name"] or u["username"] or str(u["user_id"]))
            plan_i = "⭐" if u["plan"] == "premium" else "🆓"
            msg_text += f"{plan_i} <code>{u['user_id']}</code> — {name}\n"
            kb.append([InlineKeyboardButton(f"👤 {name[:25]}", callback_data=f"admin_user_view:{u['user_id']}")])
        await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "give_premium_id":
        context.user_data.pop("admin_state", None)
        try:
            uid = int(text)
            u   = await get_user(uid)
            if not u:
                await update.message.reply_text(f"❌ User <code>{uid}</code> not found.", parse_mode="HTML")
                return
            context.user_data["admin_state"] = f"give_premium:{uid}"
            name = html_mod.escape(u["full_name"] or u["username"] or str(uid))
            await update.message.reply_text(
                f"⭐ <b>Give Premium to:</b>\n👤 {name} (<code>{uid}</code>)\n\n"
                "Send number of days (e.g. <code>30</code>, <code>365</code>):", parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ Please send a valid user ID.")
        return

    if state.startswith("give_premium:"):
        uid = int(state.split(":")[1])
        context.user_data.pop("admin_state", None)
        try:
            days = int(text)
            await update_user_plan(uid, "premium", days)
            await log_admin_action(update.effective_user.id, "give_premium", uid, f"{days} days")
            exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
            await update.message.reply_text(
                f"✅ Premium granted to <code>{uid}</code> for <b>{days} days</b>.\nExpires: {exp}",
                parse_mode="HTML"
            )
        except ValueError:
            await update.message.reply_text("❌ Please send a number (e.g. 30)")
        return

    if state.startswith("edit_text:"):
        key = state.split(":", 1)[1]
        context.user_data.pop("admin_state", None)
        await update_text(key, text)
        await update.message.reply_text(
            f"✅ Text <code>{html_mod.escape(key)}</code> updated!", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 Back to Texts", callback_data="admin_texts")]])
        )
        return

    if state.startswith("edit_emoji:"):
        key = state.split(":", 1)[1]
        context.user_data.pop("admin_state", None)
        parts    = [p.strip() for p in text.split("|", 1)]
        emoji_id = parts[0]
        fallback = parts[1] if len(parts) > 1 else "⭐"
        await update_emoji(key, emoji_id, fallback)
        await update.message.reply_text(
            f"✅ Emoji <code>{html_mod.escape(key)}</code> updated!\n"
            f"ID: <code>{html_mod.escape(emoji_id)}</code> | Fallback: {html_mod.escape(fallback)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("😀 Back to Emojis", callback_data="admin_emojis")]])
        )
        return

    if state.startswith("edit_button:"):
        key = state.split(":", 1)[1]
        context.user_data.pop("admin_state", None)
        parts = [p.strip() for p in text.split("|", 1)]
        label = parts[0]
        color = parts[1].lower() if len(parts) > 1 else "primary"
        if color not in ("primary", "success", "danger", "default"):
            color = "primary"
        b         = await get_button(key)
        emoji_key = b["emoji_key"] if b else ""
        await update_button(key, label, color, emoji_key)
        await update.message.reply_text(
            f"✅ Button <code>{html_mod.escape(key)}</code> updated!\nLabel: <code>{html_mod.escape(label)}</code> | Color: <code>{color}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎨 Back to Buttons", callback_data="admin_buttons")]])
        )
        return

    if state == "set_support":
        context.user_data.pop("admin_state", None)
        await set_setting("support_username", text)
        await update.message.reply_text(f"✅ Support username set: <code>{html_mod.escape(text)}</code>", parse_mode="HTML")
        return

    if state == "set_channel":
        context.user_data.pop("admin_state", None)
        await set_setting("channel_link", text)
        await update.message.reply_text(f"✅ Channel link set: <code>{html_mod.escape(text)}</code>", parse_mode="HTML")
        return

    if state.startswith("broadcast:"):
        target = state.split(":", 1)[1]
        context.user_data.pop("admin_state", None)
        status_msg = await update.message.reply_text(f"📢 Broadcasting to <b>{target}</b> users...", parse_mode="HTML")
        app = context.application
        sent, failed = await _do_broadcast(app, target, text, update.effective_user.id)
        await log_admin_action(update.effective_user.id, f"broadcast_{target}", 0, f"sent={sent} failed={failed}")
        await status_msg.edit_text(
            f"✅ <b>Broadcast complete!</b>\n\n📨 Sent: <code>{sent}</code>\n❌ Failed: <code>{failed}</code>",
            parse_mode="HTML"
        )
        return


@require_admin
async def admin_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("admin_state", "")
    if state != "set_photo":
        return
    context.user_data.pop("admin_state", None)
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("❌ Please send a photo.")
        return
    await set_setting("welcome_photo_id", photo.file_id)
    await update.message.reply_text("✅ Welcome photo updated!")

# ══════════════════════════════════════════════════════════════════
# WEB DASHBOARD
# ══════════════════════════════════════════════════════════════════

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>BOT HOSTING — Dashboard</title>
<style>
:root{--bg:#0d0d0f;--card:#161618;--card2:#1e1e21;--accent:#7c6cf8;--accent2:#5eead4;--danger:#f87171;--warn:#fbbf24;--ok:#34d399;--text:#e4e4e7;--muted:#71717a;--border:#27272a;--font:'Segoe UI',system-ui,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}
header{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);padding:20px 28px;display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--border)}
header h1{font-size:1.3rem;font-weight:700}.pulse{width:9px;height:9px;border-radius:50%;background:var(--ok);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}50%{box-shadow:0 0 0 6px rgba(52,211,153,0)}}
main{max-width:1200px;margin:0 auto;padding:24px 20px}
.grid4{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.stat-card .val{font-size:2rem;font-weight:700}.stat-card .lbl{font-size:.75rem;color:var(--muted);margin-top:6px;text-transform:uppercase}
.grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.card h2{font-size:.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);margin-bottom:16px}
.res-row{display:flex;align-items:center;gap:12px;margin-bottom:14px}.res-row .name{width:48px;font-size:.8rem;color:var(--muted)}
.bar{flex:1;height:8px;background:var(--card2);border-radius:4px;overflow:hidden}.bar-fill{height:100%;border-radius:4px;transition:width .6s}
.bar-fill.cpu{background:linear-gradient(90deg,var(--accent),var(--accent2))}.bar-fill.ram{background:linear-gradient(90deg,var(--warn),var(--danger))}
.bar-fill.disk{background:linear-gradient(90deg,var(--accent2),var(--ok))}.res-row .pct{width:36px;text-align:right;font-size:.8rem;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:.82rem}
thead th{text-align:left;padding:8px 10px;color:var(--muted);font-weight:600;text-transform:uppercase;border-bottom:1px solid var(--border)}
tbody tr{border-bottom:1px solid #1f1f22}tbody td{padding:10px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:20px;font-size:.7rem;font-weight:600}
.chip.on{background:rgba(52,211,153,.15);color:var(--ok)}.chip.py{background:rgba(124,108,248,.15);color:var(--accent)}.chip.js{background:rgba(251,191,36,.12);color:var(--warn)}
.mono{font-family:'Courier New',monospace;font-size:.75rem;color:var(--accent2)}
footer{text-align:center;padding:24px;color:var(--muted);font-size:.75rem}.empty{text-align:center;color:var(--muted);padding:32px}
</style>
</head>
<body>
<header><div class="pulse"></div><h1>🤖 BOT HOSTING Dashboard</h1>
<span style="margin-left:auto;font-size:.8rem;color:#6b7280" id="ts">Loading…</span></header>
<main>
<div class="grid4">
<div class="stat-card"><div style="font-size:1.6rem">👥</div><div class="val" id="s-users">—</div><div class="lbl">Total Users</div></div>
<div class="stat-card"><div style="font-size:1.6rem">🤖</div><div class="val" id="s-running">—</div><div class="lbl">Bots Running</div></div>
<div class="stat-card"><div style="font-size:1.6rem">⭐</div><div class="val" id="s-premium">—</div><div class="lbl">Premium Users</div></div>
<div class="stat-card"><div style="font-size:1.6rem">📦</div><div class="val" id="s-total">—</div><div class="lbl">Total Bots</div></div>
</div>
<div class="grid2">
<div class="card"><h2>⚡ System Resources</h2>
<div class="res-row"><span class="name">CPU</span><div class="bar"><div class="bar-fill cpu" id="bar-cpu" style="width:0%"></div></div><span class="pct" id="pct-cpu">—</span></div>
<div class="res-row"><span class="name">RAM</span><div class="bar"><div class="bar-fill ram" id="bar-ram" style="width:0%"></div></div><span class="pct" id="pct-ram">—</span></div>
<div class="res-row"><span class="name">Disk</span><div class="bar"><div class="bar-fill disk" id="bar-disk" style="width:0%"></div></div><span class="pct" id="pct-disk">—</span></div>
<div style="margin-top:16px;font-size:.75rem;color:var(--muted)" id="sys-info">—</div></div>
<div class="card"><h2>📊 Quick Stats</h2>
<table><tbody>
<tr><td style="color:var(--muted)">Today Joins</td><td id="q-today" class="mono">—</td></tr>
<tr><td style="color:var(--muted)">Banned</td><td id="q-banned" class="mono">—</td></tr>
<tr><td style="color:var(--muted)">Python Bots</td><td id="q-py" class="mono">—</td></tr>
<tr><td style="color:var(--muted)">Node.js Bots</td><td id="q-js" class="mono">—</td></tr>
<tr><td style="color:var(--muted)">Auto-Restart ON</td><td id="q-ar" class="mono">—</td></tr>
</tbody></table></div></div>
<div class="card" style="margin-bottom:24px"><h2>🟢 Running Bots</h2><div id="bots-wrap"><div class="empty">Loading…</div></div></div>
</main>
<footer>BOT HOSTING © 2025 — Auto-refreshes every 10s</footer>
<script>
async function fetchStats(){
  try{
    const d=await(await fetch('/dash/api/stats')).json();
    document.getElementById('s-users').textContent=d.total_users??'—';
    document.getElementById('s-running').textContent=d.running_bots??'—';
    document.getElementById('s-premium').textContent=d.premium_users??'—';
    document.getElementById('s-total').textContent=d.total_bots??'—';
    document.getElementById('q-today').textContent=d.today_joins??'—';
    document.getElementById('q-banned').textContent=d.banned_users??'—';
    document.getElementById('q-py').textContent=d.python_bots??'—';
    document.getElementById('q-js').textContent=d.node_bots??'—';
    document.getElementById('q-ar').textContent=d.auto_restart_bots??'—';
    const s=d.system||{};
    document.getElementById('bar-cpu').style.width=(s.cpu_pct||0)+'%';
    document.getElementById('bar-ram').style.width=(s.ram_pct||0)+'%';
    document.getElementById('bar-disk').style.width=(s.disk_pct||0)+'%';
    document.getElementById('pct-cpu').textContent=(s.cpu_pct||0)+'%';
    document.getElementById('pct-ram').textContent=(s.ram_pct||0)+'%';
    document.getElementById('pct-disk').textContent=(s.disk_pct||0)+'%';
    document.getElementById('sys-info').textContent=`${s.platform??''} · Python ${s.python??''} · ${s.ram_used??''} / ${s.ram_total??''} RAM`;
  }catch(e){}
}
async function fetchBots(){
  try{
    const bots=await(await fetch('/dash/api/bots')).json();
    const w=document.getElementById('bots-wrap');
    if(!bots.length){w.innerHTML='<div class="empty">No bots running</div>';return;}
    w.innerHTML='<table><thead><tr><th>User ID</th><th>Bot Name</th><th>Status</th><th>Type</th><th>Crashes</th><th>Started</th></tr></thead><tbody>'+
      bots.map(b=>`<tr><td>${b.user_id}</td><td class="mono">${b.bot_name}</td><td><span class="chip on">● Online</span></td>
      <td><span class="chip ${b.bot_type==='nodejs'?'js':'py'}">${b.bot_type==='nodejs'?'⬡ Node.js':'🐍 Python'}</span></td>
      <td>${b.crash_count??0}</td><td style="color:var(--muted)">${b.started_at?b.started_at.slice(0,16):'—'}</td></tr>`).join('')+'</tbody></table>';
  }catch(e){}
}
function tick(){document.getElementById('ts').textContent=new Date().toLocaleTimeString();}
async function refresh(){await Promise.all([fetchStats(),fetchBots()]);}
refresh();tick();setInterval(refresh,10000);setInterval(tick,1000);
</script>
</body>
</html>"""


async def _web_handle_index(_req):
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def _web_handle_stats(_req):
    data = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for col, q in [
                ("total_users",       "SELECT COUNT(*) c FROM users"),
                ("premium_users",     "SELECT COUNT(*) c FROM users WHERE plan='premium'"),
                ("banned_users",      "SELECT COUNT(*) c FROM users WHERE is_banned=1"),
                ("suspended_users",   "SELECT COUNT(*) c FROM users WHERE is_suspended=1"),
                ("total_bots",        "SELECT COUNT(*) c FROM bots"),
                ("python_bots",       "SELECT COUNT(*) c FROM bots WHERE bot_type='python' OR bot_type IS NULL"),
                ("node_bots",         "SELECT COUNT(*) c FROM bots WHERE bot_type='nodejs'"),
                ("auto_restart_bots", "SELECT COUNT(*) c FROM bots WHERE auto_restart=1"),
            ]:
                async with db.execute(q) as cur:
                    data[col] = (await cur.fetchone())["c"]
            today = datetime.now().strftime("%Y-%m-%d")
            async with db.execute("SELECT COUNT(*) c FROM users WHERE joined_at LIKE ?", (f"{today}%",)) as cur:
                data["today_joins"] = (await cur.fetchone())["c"]
    except Exception:
        pass
    data["running_bots"] = len(running_processes)
    sys_data: dict = {"platform": platform.system(), "python": platform.python_version()}
    try:
        sys_data["cpu_pct"]   = int(psutil.cpu_percent(interval=0.2))
        vm = psutil.virtual_memory()
        sys_data["ram_pct"]   = int(vm.percent)
        sys_data["ram_used"]  = f"{vm.used // (1024**2)} MB"
        sys_data["ram_total"] = f"{vm.total // (1024**2)} MB"
        dk = psutil.disk_usage("/")
        sys_data["disk_pct"]  = int(dk.percent)
    except Exception:
        pass
    data["system"] = sys_data
    return web.Response(text=json.dumps(data), content_type="application/json")


async def _web_handle_bots(_req):
    rows = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            bot_id_list = list(running_processes.keys())
            if not bot_id_list:
                return web.Response(text="[]", content_type="application/json")
            placeholders = ",".join("?" * len(bot_id_list))
            async with db.execute(
                f"SELECT user_id, bot_name, bot_type, crash_count, started_at FROM bots WHERE id IN ({placeholders})",
                bot_id_list,
            ) as cur:
                async for row in cur:
                    rows.append(dict(row))
    except Exception:
        pass
    return web.Response(text=json.dumps(rows), content_type="application/json")


async def start_web_server(port: int = 8082):
    app = web.Application()
    app.router.add_get("/dash/",          _web_handle_index)
    app.router.add_get("/dash",           _web_handle_index)
    app.router.add_get("/dash/api/stats", _web_handle_stats)
    app.router.add_get("/dash/api/bots",  _web_handle_bots)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner

# ══════════════════════════════════════════════════════════════════
# MAIN — GLOBAL HANDLERS & APP SETUP
# ══════════════════════════════════════════════════════════════════

_app_ref = None


async def _notify_user(user_id: int, text: str):
    try:
        if _app_ref:
            await _app_ref.bot.send_message(user_id, text, parse_mode="HTML")
    except Exception:
        pass


async def _premium_expiry_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            expired = await get_expired_premium_users()
            for u in expired:
                await update_user_plan(u["user_id"], "free", 0)
                tmpl = await get_text(
                    "premium_expired_notify",
                    "⚠️ <b>Premium Expired</b>\n\nYour Premium plan has expired. You've been moved to Free plan.\n\nUse /upgrade to renew.",
                )
                await _notify_user(u["user_id"], tmpl)
                logger.info(f"Premium expired for user {u['user_id']}")
        except Exception as e:
            logger.error(f"Premium expiry checker error: {e}")


async def post_init(application: Application):
    global _app_ref
    _app_ref = application
    await init_db()
    logger.info("Database initialized.")
    set_notify_callback(_notify_user)
    recovered = await recover_on_startup()
    logger.info(f"Recovered {recovered} hosted bot(s) from previous session.")
    commands = [
        BotCommand("start",   "Main menu"),
        BotCommand("help",    "Help & features"),
        BotCommand("upload",  "Upload a bot (.py, .js, .zip)"),
        BotCommand("files",   "My hosted bots"),
        BotCommand("run",     "Run / stop / restart a bot"),
        BotCommand("status",  "Check system status"),
        BotCommand("logs",    "View bot logs"),
        BotCommand("upgrade", "Upgrade to Premium"),
        BotCommand("support", "Contact support"),
        BotCommand("admin",   "Admin panel (admins only)"),
        BotCommand("cancel",  "Cancel current action"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Commands set.")
    try:
        # Railway sets PORT automatically; fallback to DASH_PORT or 8080
        web_port = int(os.environ.get("PORT") or os.environ.get("DASH_PORT") or 8080)
        asyncio.create_task(start_web_server(web_port))
        logger.info(f"Web dashboard started on port {web_port} → /dash/")
    except Exception as e:
        logger.warning(f"Web dashboard not started: {e}")
    asyncio.create_task(_premium_expiry_loop())
    asyncio.create_task(watchdog_loop())
    logger.info("Watchdog + expiry schedulers started.")


async def cancel_handler(update: Update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ Action cancelled.\n\nUse /start to return to the main menu.")


async def handle_message(update: Update, context):
    if update.message and update.message.photo:
        await admin_photo_handler(update, context)
        return
    if update.message and update.message.text:
        state = context.user_data.get("admin_state", "")
        if state:
            await admin_message_handler(update, context)
            return
        if context.user_data.get("editing_filepath"):
            await receive_edit_content(update, context)
            return
        await start_handler(update, context)


async def handle_document(update: Update, context):
    await receive_file_handler(update, context)


async def handle_callback(update: Update, context):
    query = update.callback_query
    data  = query.data

    if data in ("main_menu", "start"):
        await query.answer()
        await start_handler(update, context)
    elif data in ("status_cmd", "support_cmd", "buy_premium"):
        await query.answer()
        if data == "status_cmd":
            await status_handler(update, context)
        elif data == "support_cmd":
            await support_handler(update, context)
        elif data == "buy_premium":
            await premium_handler(update, context)
    elif data == "my_files":
        await query.answer()
        await list_files_handler(update, context)
    elif data == "upload_file":
        await query.answer()
        await upload_prompt_handler(update, context)
    elif data in ("edit_files", "delete_folder"):
        await query.answer()
        await list_files_handler(update, context)
    elif data.startswith("bot_manage:"):
        await bot_manage_callback(update, context)
    elif data.startswith("bot_files:"):
        await bot_files_callback(update, context)
    elif data.startswith("edit_file:"):
        await edit_file_callback(update, context)
    elif data.startswith("bot_delete_confirm:"):
        await delete_confirm_callback(update, context)
    elif data.startswith("bot_delete_do:"):
        await delete_do_callback(update, context)
    elif data.startswith("bot_logs:"):
        await bot_logs_callback(update, context)
    elif data.startswith("bot_toggle_ar:"):
        await bot_toggle_ar_callback(update, context)
    elif data.startswith("bot_start:"):
        await bot_start_callback(update, context)
    elif data.startswith("bot_stop:"):
        await bot_stop_callback(update, context)
    elif data.startswith("bot_restart:"):
        await bot_restart_callback(update, context)
    elif data in ("run_module", "my_logs"):
        await query.answer()
        await list_files_handler(update, context)
    elif data in ("buy_monthly", "buy_yearly"):
        await buy_plan_callback(update, context)
    elif data == "admin_panel":
        await admin_panel_handler(update, context)
    elif data == "admin_stats":
        await admin_stats_callback(update, context)
    elif data == "admin_users":
        await admin_users_callback(update, context)
    elif data.startswith("admin_users_list:"):
        await admin_users_list_callback(update, context)
    elif data == "admin_users_search":
        await admin_users_search_callback(update, context)
    elif data == "admin_users_premium":
        await admin_premium_callback(update, context)
    elif data == "admin_users_banned":
        await admin_users_banned_callback(update, context)
    elif data.startswith("admin_user_view:"):
        await admin_user_view_callback(update, context)
    elif data.startswith("admin_user_bots:"):
        await admin_user_bots_callback(update, context)
    elif data.startswith("admin_ban:") or data.startswith("admin_unban:"):
        await admin_ban_callback(update, context)
    elif data.startswith("admin_suspend:") or data.startswith("admin_unsuspend:"):
        await admin_suspend_callback(update, context)
    elif data.startswith("admin_delete_data:"):
        await admin_delete_data_callback(update, context)
    elif data.startswith("admin_delete_data_do:"):
        await admin_delete_data_do_callback(update, context)
    elif data == "admin_premium":
        await admin_premium_callback(update, context)
    elif data == "admin_give_premium_id":
        await admin_give_premium_id_callback(update, context)
    elif data.startswith("admin_give_premium:"):
        await admin_give_premium_callback(update, context)
    elif data.startswith("admin_remove_premium:"):
        await admin_remove_premium_callback(update, context)
    elif data == "admin_broadcast":
        await admin_broadcast_callback(update, context)
    elif data in ("broadcast_all", "broadcast_premium"):
        await broadcast_start_callback(update, context)
    elif data == "broadcast_stats":
        await broadcast_stats_callback(update, context)
    elif data == "admin_texts":
        await admin_texts_callback(update, context)
    elif data.startswith("admin_edit_text:"):
        await admin_edit_text_callback(update, context)
    elif data == "admin_emojis":
        await admin_emojis_callback(update, context)
    elif data.startswith("admin_edit_emoji:"):
        await admin_edit_emoji_callback(update, context)
    elif data == "admin_buttons":
        await admin_buttons_callback(update, context)
    elif data.startswith("admin_edit_button:"):
        await admin_edit_button_callback(update, context)
    elif data == "admin_settings":
        await admin_settings_callback(update, context)
    elif data == "admin_set_photo":
        await admin_set_photo_callback(update, context)
    elif data == "admin_set_support":
        await admin_set_support_callback(update, context)
    elif data == "admin_set_channel":
        await admin_set_channel_callback(update, context)
    elif data in ("admin_maint_on", "admin_maint_off"):
        await admin_maint_callback(update, context)
    else:
        await query.answer(f"Unknown: {data}", show_alert=False)


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Set it in .env or environment variables.")
        sys.exit(1)

    os.makedirs(USER_BOTS_DIR, exist_ok=True)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",   start_handler))
    app.add_handler(CommandHandler("help",    help_handler))
    app.add_handler(CommandHandler("upload",  upload_prompt_handler))
    app.add_handler(CommandHandler("files",   list_files_handler))
    app.add_handler(CommandHandler("run",     list_files_handler))
    app.add_handler(CommandHandler("status",  status_handler))
    app.add_handler(CommandHandler("logs",    list_files_handler))
    app.add_handler(CommandHandler("upgrade", premium_handler))
    app.add_handler(CommandHandler("support", support_handler))
    app.add_handler(CommandHandler("admin",   admin_panel_handler))
    app.add_handler(CommandHandler("cancel",  cancel_handler))

    try:
        app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
        app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    except Exception:
        pass

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info(f"🚀 Starting — Admins: {ADMIN_IDS}")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

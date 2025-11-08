#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import threading
from pathlib import Path
from telebot import TeleBot, types
from dotenv import load_dotenv
import datetime
import pytz   # 🟢 mana shu joyda qo‘sh

# Timezone: always use Tashkent time
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

def now_tashkent():
    """Return timezone-aware current datetime in Tashkent."""
    return datetime.datetime.now(TASHKENT_TZ)

def today_tashkent_date():
    """Return current date in Tashkent (datetime.date)."""
    return now_tashkent().date()

# ========================
# .env -> TOKEN, ADMIN_ID
# ========================
load_dotenv()
TOKEN = os.getenv("TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
if not TOKEN or ADMIN_ID == 0:
    print("❌ .env faylida TOKEN va ADMIN_ID to'g'ri kiritilganiga ishonch hosil qiling.")
    exit(1)

bot = TeleBot(TOKEN, threaded=True)

# Register bot commands so that when someone types "/" in a Telegram chat
# the commands like /bugun and /ertaga appear in the command suggestion list.
def register_bot_commands():
    cmds = [
        types.BotCommand("start", "Boshlash — botni boshlash"),
        types.BotCommand("bugun", "Bugungi jadval"),
        types.BotCommand("ertaga", "Ertangi jadval"),
        types.BotCommand("help", "Yordam")
    ]
    try:
        # global default
        bot.set_my_commands(cmds)
        # explicitly set for private chats and group chats as well
        try:
            bot.set_my_commands(cmds, scope=types.BotCommandScopeAllPrivateChats())
        except Exception:
            pass
        try:
            bot.set_my_commands(cmds, scope=types.BotCommandScopeAllGroupChats())
        except Exception:
            pass
        print("✅ Bot komandalar ro'yxati ro'yxatga olindi (/ bugun, /ertaga va boshqalar).")
    except Exception as e:
        print("⚠️ Bot komandalarini ro'yxatga olishda xato:", e)

# ========================
# File paths & defaults
# ========================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"           # individual users list
GROUPS_FILE = DATA_DIR / "groups.json"         # groups where bot is added
SCHEDULES_FILE = DATA_DIR / "schedules.json"  # tepa/pastgi schedules
SETTINGS_FILE = DATA_DIR / "settings.json"    # settings, admins, etc.
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

def load_json(path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("JSON load error:", e)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ========================
# Load or init data stores
# ========================
users = load_json(USERS_FILE, [])
groups = load_json(GROUPS_FILE, [])  # list of group chat ids (ints)
schedules = load_json(SCHEDULES_FILE, {
    "tepa": {
        "Monday": "08:00 - Matematika\n09:00 - Fizika\n10:30 - Ingliz tili",
        "Tuesday": "08:00 - Kimyo\n09:00 - Biologiya\n10:30 - Tarix",
        "Wednesday": "08:00 - Tarix\n09:00 - Adabiyot\n10:30 - Informatika",
        "Thursday": "08:00 - Fizika\n09:00 - Matematika\n10:30 - Ingliz tili",
        "Friday": "08:00 - Algebra\n09:00 - Geometriya\n10:30 - Musiqa",
        "Saturday": "09:00 - Jismoniy tarbiya\n10:00 - Sinf soati"
    },
    "pastgi": {
        "Monday": "08:00 - Kimyo\n09:00 - Ingliz tili\n10:30 - Matematika",
        "Tuesday": "08:00 - Biologiya\n09:00 - Algebra\n10:30 - Tarix",
        "Wednesday": "08:00 - Fizika\n09:00 - Matematika\n10:30 - Adabiyot",
        "Thursday": "08:00 - Tarix\n09:00 - Kimyo\n10:30 - Informatika",
        "Friday": "08:00 - Adabiyot\n09:00 - Informatika\n10:30 - Musiqa",
        "Saturday": "09:00 - Sport\n10:00 - Sinf soati"
    }
})
settings = load_json(SETTINGS_FILE, {
    "current_week": "tepa",             # tepa / pastgi
    "auto_switch_on_monday": True,      # auto switch week on Monday
    "reminder_minutes_before": 15,      # reminder offset
    "admins": [ADMIN_ID],               # list of bot-global admins (can manage global things)
    "send_6am": True,
    "send_18pm": True
})

# persist initial files if missing
save_json(USERS_FILE, users)
save_json(GROUPS_FILE, groups)
save_json(SCHEDULES_FILE, schedules)
save_json(SETTINGS_FILE, settings)

# ========================
# Utilities: day mapping, pretty text
# ========================
EN_TO_UZ_BTN = {
    "Monday": "📘 Dushanba",
    "Tuesday": "📗 Seshanba",
    "Wednesday": "📙 Chorshanba",
    "Thursday": "📒 Payshanba",
    "Friday": "📔 Juma",
    "Saturday": "📕 Shanba",
    "Sunday": "🌞 Yakshanba"
}
UZ_BTN_TO_EN = {v: k for k, v in EN_TO_UZ_BTN.items()}

def is_user_admin_in_chat(chat_id, user_id):
    """Return True if user is chat admin (works for groups)"""
    try:
        admins = bot.get_chat_administrators(chat_id)
        return any(a.user.id == user_id for a in admins)
    except Exception:
        return False

def pretty_schedule_text(day_en, week_type):
    """Make markdown formatted schedule text"""
    if day_en == "Sunday":
        return "🌞 *Yakshanba* — Bugun dars yo'q!!!"
    jadval = schedules.get(week_type, {}).get(day_en)
    if not jadval:
        return f"❌ *{EN_TO_UZ_BTN.get(day_en, day_en)}* uchun jadval topilmadi."
    header = f"📅 *{EN_TO_UZ_BTN.get(day_en, day_en)}* — *{'Tepa' if week_type=='tepa' else 'Pastgi'} hafta*\n\n"
    lines = []
    for line in jadval.splitlines():
        m = re.match(r"\s*(\d{1,2}:\d{2})\s*-\s*(.+)", line)
        if m:
            t, subject = m.groups()
            lines.append(f"⏰ `{t}` — *{subject}*")
        else:
            lines.append(f"• {line}")
    return header + "\n".join(lines)

def parse_times_from_text(jadval_text):
    times = re.findall(r"(\d{1,2}:\d{2})", jadval_text)
    return sorted(list(dict.fromkeys(times)))

# ========================
# Save helper wrappers
# ========================
def save_all():
    save_json(USERS_FILE, users)
    save_json(GROUPS_FILE, groups)
    save_json(SCHEDULES_FILE, schedules)
    save_json(SETTINGS_FILE, settings)

# ========================
# Scheduling & reminders
# ========================
def send_message_safe(chat_id, text, parse_mode="Markdown", reply_markup=None):
    try:
        bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as e:
        print(f"Send error to {chat_id}: {e}")

def send_daily_morning():
    """Send today's schedule to all users and groups at 06:00 Tashkent time"""
    week = settings.get("current_week", "tepa")
    today_en = today_tashkent_date().strftime("%A")
    if today_en == "Sunday":
        text = "🌞 *Yakshanba* — Bugun dars yo'q! 😎\nDam oling!"
    else:
        text = pretty_schedule_text(today_en, week)
    # Send to individual users
    sent_u = 0
    for uid in list(users):
        try:
            send_message_safe(uid, text, reply_markup=main_reply_keyboard(uid))
            sent_u += 1
        except Exception:
            pass
    # Send to groups (use inline "Bugun / Ertaga" buttons)
    inline = types.InlineKeyboardMarkup()
    inline.add(
        types.InlineKeyboardButton("📅 Bugun", callback_data=f"grp_bugun:{today_en}"),
        types.InlineKeyboardButton("📅 Ertaga", callback_data=f"grp_ertaga:{today_en}")
    )
    sent_g = 0
    for gid in list(groups):
        try:
            send_message_safe(gid, text, reply_markup=inline)
            sent_g += 1
        except Exception:
            pass
    # Notify admin
    try:
        bot.send_message(ADMIN_ID, f"📤 06:00: Ertalabki jadval yuborildi. Foydalanuvchilar: {len(users)}, Guruhlar: {len(groups)}. Yuborildi: users={sent_u}, groups={sent_g}")
    except Exception:
        pass

def send_daily_evening():
    """Send tomorrow's schedule at 18:00 Tashkent time to users and groups"""
    week = settings.get("current_week", "tepa")
    today_date = today_tashkent_date()
    tomorrow_date = today_date + datetime.timedelta(days=1)
    tomorrow_en = tomorrow_date.strftime("%A")
    week_type = settings.get("current_week", "tepa")
    if settings.get("auto_switch_on_monday", True) and tomorrow_date.weekday() == 0:
        week_type = "pastgi" if week_type == "tepa" else "tepa"
    if tomorrow_en == "Sunday":
        text = "🌞 *Yakshanba* — Ertaga dars yo'q! 😎\nDam oling!"
    else:
        text = pretty_schedule_text(tomorrow_en, week_type)
    inline = types.InlineKeyboardMarkup()
    inline.add(
        types.InlineKeyboardButton("📅 Bugun", callback_data=f"grp_bugun:{tomorrow_en}"),
        types.InlineKeyboardButton("📅 Ertaga", callback_data=f"grp_ertaga:{tomorrow_en}")
    )
    sent_u = 0
    for uid in list(users):
        try:
            send_message_safe(uid, text, reply_markup=main_reply_keyboard(uid))
            sent_u += 1
        except Exception:
            pass
    sent_g = 0
    for gid in list(groups):
        try:
            send_message_safe(gid, text, reply_markup=inline)
            sent_g += 1
        except Exception:
            pass
    try:
        bot.send_message(ADMIN_ID, f"📤 18:00: Ertangi jadval yuborildi. users={sent_u}, groups={sent_g}")
    except Exception:
        pass

def seconds_until_target(hour, minute=0):
    """Return seconds until next target time at Tashkent timezone."""
    now = now_tashkent()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target = target + datetime.timedelta(days=1)
    return (target - now).total_seconds()

def daily_scheduler_loop():
    """Thread: waits until next 06:00 and 18:00 (Tashkent) and sends messages"""
    while True:
        sec6 = seconds_until_target(6, 0)
        sec18 = seconds_until_target(18, 0)
        # choose next event
        if sec6 <= sec18:
            time.sleep(sec6)
            if settings.get("send_6am", True):
                # If it's Monday morning and auto switch enabled: switch week before sending
                today = today_tashkent_date()
                if settings.get("auto_switch_on_monday", True) and today.weekday() == 0:
                    settings["current_week"] = "pastgi" if settings.get("current_week","tepa") == "tepa" else "tepa"
                    save_json(SETTINGS_FILE, settings)
                send_daily_morning()
                schedule_reminders_for_today()
        else:
            time.sleep(sec18)
            if settings.get("send_18pm", True):
                send_daily_evening()

# Reminder scheduling for individual users
def schedule_reminders_for_today():
    """Schedule reminders (threading.Timer) for times in today's schedule for individuals only (Tashkent time)."""
    today_en = today_tashkent_date().strftime("%A")
    if today_en == "Sunday":
        return
    week = settings.get("current_week", "tepa")
    jadval_text = schedules.get(week, {}).get(today_en, "")
    times = parse_times_from_text(jadval_text)
    minutes_before = int(settings.get("reminder_minutes_before", 15))
    now = now_tashkent()
    for t in times:
        try:
            hh, mm = map(int, t.split(":"))
            # Build a timezone-aware lesson datetime in Tashkent
            lesson_naive = datetime.datetime(now.year, now.month, now.day, hh, mm)
            lesson_dt = TASHKENT_TZ.localize(lesson_naive)
            remind_dt = lesson_dt - datetime.timedelta(minutes=minutes_before)
            delay = (remind_dt - now).total_seconds()
            if delay <= 0:
                continue
            threading.Timer(delay, reminder_send_for_time, args=(t,)).start()
        except Exception as e:
            print("Reminder schedule error:", e)

def reminder_send_for_time(time_str):
    """Send reminder to all individual users (not groups) at the scheduled Tashkent time."""
    week = settings.get("current_week", "tepa")
    today_en = today_tashkent_date().strftime("%A")
    jadval_text = schedules.get(week, {}).get(today_en, "")
    subject = None
    for line in jadval_text.splitlines():
        if time_str in line:
            parts = line.split("-", 1)
            if len(parts) >= 2:
                subject = parts[1].strip()
            break
    if subject:
        msg = f"🔔 *Eslatma!* `{time_str}` da *{subject}* boshlanadi. Tayyorlaning!"
    else:
        msg = f"🔔 *Eslatma!* `{time_str}` da dars boshlanadi. Tayyorlaning!"
    for uid in list(users):
        try:
            send_message_safe(uid, msg, reply_markup=main_reply_keyboard(uid))
        except Exception:
            pass

# ========================
# Keyboards & inline nav
# ========================
def main_reply_keyboard(user_id, chat_id=None):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    buttons = [types.KeyboardButton(v) for v in EN_TO_UZ_BTN.values()]
    kb.add(*buttons)
    kb.add(types.KeyboardButton("📅 Bugun"), types.KeyboardButton("📅 Ertaga"))
    # Add admin panel if user is bot-global admin or chat admin
    if user_id in settings.get("admins", []) or (chat_id and is_user_admin_in_chat(chat_id, user_id)):
        kb.add(types.KeyboardButton("🧠 Admin panel"))
    return kb

def admin_reply_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📋 Jadvalni ko‘rish", "✏️ Jadvalni tahrirlash")
    kb.add("➕ Jadval qo‘shish", "🗑 Jadval o‘chirish")
    kb.add("🔁 Haftani almashtirish", "📆 Hozirgi hafta turi")
    kb.add("📊 Statistika", "📤 Barcha foydalanuvchilarga xabar")
    kb.add("💾 Backup yaratish", "👥 Admin qo'sh / o'chirish")
    kb.add("⬅️ Orqaga")
    return kb

def inline_day_nav(day_en, week_type):
    """Inline keyboard with left/right and today/weekly (with clear icons)"""
    kb = types.InlineKeyboardMarkup()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    idx = days.index(day_en)
    prev_day = days[(idx - 1) % len(days)]
    next_day = days[(idx + 1) % len(days)]
    left_text = "⬅️ " + EN_TO_UZ_BTN.get(prev_day, prev_day)
    cur_text = EN_TO_UZ_BTN.get(day_en, day_en)
    right_text = EN_TO_UZ_BTN.get(next_day, next_day) + " ➡️"
    kb.row(
        types.InlineKeyboardButton(left_text, callback_data=f"nav:{prev_day}:{week_type}"),
        types.InlineKeyboardButton(cur_text, callback_data="nav:noop"),
        types.InlineKeyboardButton(right_text, callback_data=f"nav:{next_day}:{week_type}")
    )
    kb.add(types.InlineKeyboardButton("📅 Haftalik", callback_data=f"nav:weekly:{week_type}"))
    return kb

# ========================
# Handlers: start, private/group join, messages
# ========================
@bot.message_handler(commands=["start"])
def handle_start(m):
    chat_id = m.chat.id
    uid = m.from_user.id
    # Add to users if private chat
    if m.chat.type == "private":
        if chat_id not in users:
            users.append(chat_id)
            save_json(USERS_FILE, users)
        # send today's schedule automatically on /start
        today_en = today_tashkent_date().strftime("%A")
        week = settings.get("current_week", "tepa")
        text = pretty_schedule_text(today_en, week)
        send_message_safe(chat_id, "👋 *Assalomu alaykum!* Men — Raspisanie boti 🤖\nQuyidagi tugmalardan foydalaning:", reply_markup=main_reply_keyboard(uid, chat_id))
        send_message_safe(chat_id, text, reply_markup=main_reply_keyboard(uid, chat_id))
        return
    # If group, welcome and add to groups and send today's schedule to the group
    if m.chat.type in ("group", "supergroup"):
        if chat_id not in groups:
            groups.append(chat_id)
            save_json(GROUPS_FILE, groups)
        bot.send_message(chat_id, "👋 Men guruhda ishlashga tayyorman! Adminlar /start orqali admin panelini ochishlari mumkin.")
        # send today's schedule to group automatically
        today_en = today_tashkent_date().strftime("%A")
        week = settings.get("current_week", "tepa")
        text = pretty_schedule_text(today_en, week)
        inline = types.InlineKeyboardMarkup()
        inline.add(
            types.InlineKeyboardButton("📅 Bugun", callback_data=f"grp_bugun:{today_en}"),
            types.InlineKeyboardButton("📅 Ertaga", callback_data=f"grp_ertaga:{today_en}")
        )
        send_message_safe(chat_id, text, reply_markup=inline)
        return

@bot.message_handler(content_types=["new_chat_members"])
def on_new_members(m):
    # if bot added to group, store group id
    for u in m.new_chat_members:
        try:
            if u.id == bot.get_me().id:
                gid = m.chat.id
                if gid not in groups:
                    groups.append(gid)
                    save_json(GROUPS_FILE, groups)
                bot.send_message(gid, "👋 Men guruhga qo‘shildim — Raspisanie funktsiyalari hozir faqat adminlar tomonidan boshqarilishi mumkin.")
        except Exception:
            pass

@bot.message_handler(commands=["help"])
def cmd_help(m):
    chat_id = m.chat.id
    text = ("📚 *Raspisanie bot yordam*:\n\n"
            "🔹 /start — boshlash\n"
            "🔹 /bugun yoki '📅 Bugun' — bugungi jadval\n"
            "🔹 /ertaga yoki '📅 Ertaga' — ertangi jadval\n"
            "🔹 Tugmalardan kunlarni tanlang (Dushanba..Shanba)\n"
            "🔹 Guruhda adminlar '🧠 Admin panel' orqali jadvalni boshqaradi\n"
            "🔹 Inline tugmalar orqali oldingi/keyingi kunni ko‘rish mumkin\n"
            "🔹 Har kuni 06:00 va 18:00 da avtomatik xabar yuboriladi")
    send_message_safe(chat_id, text)

# Quick handlers for "Bugun" and "Ertaga" buttons (both private and group)
@bot.message_handler(commands=["bugun"])
def cmd_bugun(m):
    # same as pressing "📅 Bugun"
    handle_bugun(m)

@bot.message_handler(commands=["ertaga"])
def cmd_ertaga(m):
    handle_ertaga(m)

@bot.message_handler(func=lambda m: m.text == "📅 Bugun")
def handle_bugun(m):
    chat_id = m.chat.id
    uid = m.from_user.id
    today_en = today_tashkent_date().strftime("%A")
    week = settings.get("current_week", "tepa")
    text = pretty_schedule_text(today_en, week)
    # if in group, show inline nav
    if m.chat.type in ("group", "supergroup"):
        kb = inline_day_nav(today_en, week)
        send_message_safe(chat_id, text, reply_markup=kb)
    else:
        send_message_safe(chat_id, text, reply_markup=main_reply_keyboard(uid, chat_id))

@bot.message_handler(func=lambda m: m.text == "📅 Ertaga")
def handle_ertaga(m):
    chat_id = m.chat.id
    uid = m.from_user.id
    today_date = today_tashkent_date()
    tomorrow_date = (today_date + datetime.timedelta(days=1))
    tomorrow = tomorrow_date.strftime("%A")
    # compute week type possibly switching if Monday auto switch true
    week = settings.get("current_week", "tepa")
    if settings.get("auto_switch_on_monday", True) and tomorrow_date.weekday() == 0:
        week = "pastgi" if week == "tepa" else "tepa"
    text = pretty_schedule_text(tomorrow, week)
    if m.chat.type in ("group", "supergroup"):
        kb = inline_day_nav(tomorrow, week)
        send_message_safe(chat_id, text, reply_markup=kb)
    else:
        send_message_safe(chat_id, text, reply_markup=main_reply_keyboard(uid, chat_id))

# Handler for day buttons (private and group)
@bot.message_handler(func=lambda m: m.text in EN_TO_UZ_BTN.values())
def handle_day_buttons(m):
    chat_id = m.chat.id
    uid = m.from_user.id
    day_en = UZ_BTN_TO_EN.get(m.text)
    if not day_en:
        return
    week = settings.get("current_week", "tepa")
    text = pretty_schedule_text(day_en, week)
    if m.chat.type in ("group", "supergroup"):
        kb = inline_day_nav(day_en, week)
        send_message_safe(chat_id, text, reply_markup=kb)
    else:
        send_message_safe(chat_id, text, reply_markup=main_reply_keyboard(uid, chat_id))

# ========================
# Callbacks: inline navigation and group bugun/ertaga
# ========================
@bot.callback_query_handler(func=lambda cq: True)
def callback_handler(cq):
    data = cq.data
    cid = cq.message.chat.id
    uid = cq.from_user.id

    # grp_bugun:Monday  or grp_ertaga:Monday
    if data.startswith("grp_bugun:") or data.startswith("grp_ertaga:"):
        typ, day = data.split(":", 1)
        if typ == "grp_bugun":
            week = settings.get("current_week", "tepa")
            text = pretty_schedule_text(day, week)
            kb = inline_day_nav(day, week)
            try:
                bot.edit_message_text(text=text, chat_id=cid, message_id=cq.message.message_id, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                send_message_safe(cid, text, reply_markup=kb)
        else:  # grp_ertaga
            today_date = today_tashkent_date()
            tomorrow_date = (today_date + datetime.timedelta(days=1))
            tomorrow_en = tomorrow_date.strftime("%A")
            week = settings.get("current_week", "tepa")
            if settings.get("auto_switch_on_monday", True) and tomorrow_date.weekday() == 0:
                week = "pastgi" if week == "tepa" else "tepa"
            text = pretty_schedule_text(tomorrow_en, week)
            kb = inline_day_nav(tomorrow_en, week)
            try:
                bot.edit_message_text(text=text, chat_id=cid, message_id=cq.message.message_id, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                send_message_safe(cid, text, reply_markup=kb)
        bot.answer_callback_query(cq.id)
        return

    # nav:Monday:tepa  or nav:weekly:tepa or nav:noop
    if data.startswith("nav:"):
        parts = data.split(":")
        if len(parts) >= 2:
            action = parts[1]
            if action == "weekly":
                week = parts[2] if len(parts) > 2 else settings.get("current_week", "tepa")
                header = f"📅 *{week.capitalize()} hafta* — Haftalik jadval:\n\n"
                body_parts = []
                for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
                    j = schedules.get(week, {}).get(d, "—")
                    day_label = EN_TO_UZ_BTN.get(d, d)
                    body = f"🗓 *{day_label}*\n{j}\n"
                    body_parts.append(body)
                full = header + "\n".join(body_parts)
                try:
                    bot.edit_message_text(text=full, chat_id=cid, message_id=cq.message.message_id, parse_mode="Markdown", reply_markup=None)
                except Exception:
                    send_message_safe(cid, full)
                bot.answer_callback_query(cq.id)
                return
            if action == "noop":
                bot.answer_callback_query(cq.id, "📌 Bu hozirgi kun.")
                return
            # else action is a day name
            day = action
            week_type = parts[2] if len(parts) > 2 else settings.get("current_week", "tepa")
            text = pretty_schedule_text(day, week_type)
            kb = inline_day_nav(day, week_type)
            try:
                bot.edit_message_text(text=text, chat_id=cid, message_id=cq.message.message_id, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                send_message_safe(cid, text, reply_markup=kb)
            bot.answer_callback_query(cq.id)
            return

# ========================
# Admin utilities and checks
# ========================
def user_is_allowed_as_admin(chat_id, user_id):
    # allowed if user is global admin in settings OR chat admin in that chat
    try:
        if user_id in settings.get("admins", []):
            return True
        if chat_id in groups:
            return is_user_admin_in_chat(chat_id, user_id)
    except Exception:
        pass
    return False

@bot.message_handler(func=lambda m: m.text == "🧠 Admin panel")
def open_admin_panel(m):
    chat_id = m.chat.id
    uid = m.from_user.id
    if not user_is_allowed_as_admin(chat_id, uid):
        bot.send_message(chat_id, "⛔ Bu bo‘lim faqat adminlar uchun.")
        return
    kb = admin_reply_keyboard()
    if m.chat.type in ("group", "supergroup"):
        bot.send_message(chat_id, "🧠 *Admin panel (guruh)*\nQuyidagi tugmalardan tanlang:", parse_mode="Markdown", reply_markup=kb)
    else:
        bot.send_message(chat_id, "🧠 *Admin panel (shaxsiy)*\nQuyidagi tugmalardan tanlang:", parse_mode="Markdown", reply_markup=kb)

# Admin handlers (gated)
@bot.message_handler(func=lambda m: m.text == "📋 Jadvalni ko‘rish")
def admin_view(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    week = settings.get("current_week", "tepa")
    text = f"📅 *{week.capitalize()} hafta jadvali:*\n\n"
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
        j = schedules.get(week, {}).get(day, "—")
        text += f"🗓 *{EN_TO_UZ_BTN[day]}*\n{j}\n\n"
    send_message_safe(m.chat.id, text, reply_markup=main_reply_keyboard(m.from_user.id, m.chat.id))

@bot.message_handler(func=lambda m: m.text == "✏️ Jadvalni tahrirlash")
def admin_edit_start(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Tepa hafta", "Pastgi hafta")
    kb.add("⬅️ Orqaga")
    bot.send_message(m.chat.id, "📝 Qaysi haftani tahrirlamoqchisiz?", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in ["Tepa hafta", "Pastgi hafta"])
def admin_edit_choose_week(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    week = "tepa" if "Tepa" in m.text else "pastgi"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    for d in ["📘 Dushanba", "📗 Seshanba", "📙 Chorshanba", "📒 Payshanba", "📔 Juma", "📕 Shanba"]:
        kb.add(d)
    kb.add("⬅️ Orqaga")
    bot.send_message(m.chat.id, f"✍️ {m.text} — Qaysi kunni tahrirlaysiz?", reply_markup=kb)
    bot.register_next_step_handler(m, admin_edit_day_step, week)

def admin_edit_day_step(m, week):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    if m.text == "⬅️ Orqaga":
        bot.send_message(m.chat.id, "🔙 Ortga", reply_markup=admin_reply_keyboard())
        return
    if m.text not in UZ_BTN_TO_EN:
        bot.send_message(m.chat.id, "❌ Noto'g'ri tugma, bekor qilindi.", reply_markup=admin_reply_keyboard())
        return
    day = UZ_BTN_TO_EN[m.text]
    bot.send_message(m.chat.id, f"✍️ {m.text} uchun yangi jadvalni matn ko'rinishida yuboring.\nHar qator `HH:MM - Fan nomi` formatida bo'lsin.")
    bot.register_next_step_handler(m, admin_save_day, week, day)

def admin_save_day(m, week, day):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    text = m.text.strip()
    schedules.setdefault(week, {})[day] = text
    save_json(SCHEDULES_FILE, schedules)
    bot.send_message(m.chat.id, f"✅ Jadval yangilandi: *{EN_TO_UZ_BTN[day]}* ({'Tepa' if week=='tepa' else 'Pastgi'} hafta)",
                     parse_mode="Markdown", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "➕ Jadval qo‘shish")
def admin_add_schedule(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Tepa hafta", "Pastgi hafta", "⬅️ Orqaga")
    bot.send_message(m.chat.id, "➕ Qaysi haftaga yangi jadval qo'shmoqchisiz?", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in ["➕ Jadval qo‘shish", "Tepa hafta", "Pastgi hafta"])
def admin_add_choose_week(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    if m.text in ["Tepa hafta", "Pastgi hafta"]:
        week = "tepa" if "Tepa" in m.text else "pastgi"
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        for d in ["📘 Dushanba", "📗 Seshanba", "📙 Chorshanba", "📒 Payshanba", "📔 Juma", "📕 Shanba"]:
            kb.add(d)
        kb.add("⬅️ Orqaga")
        bot.send_message(m.chat.id, "➕ Qaysi kun uchun qo'shmoqchisiz?", reply_markup=kb)
        bot.register_next_step_handler(m, admin_add_day_step, week)

def admin_add_day_step(m, week):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    if m.text not in UZ_BTN_TO_EN:
        bot.send_message(m.chat.id, "❌ Bekor qilindi.", reply_markup=admin_reply_keyboard())
        return
    day = UZ_BTN_TO_EN[m.text]
    bot.send_message(m.chat.id, "➕ Yangi jadval matnini kiriting:")
    bot.register_next_step_handler(m, admin_add_save, week, day)

def admin_add_save(m, week, day):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    schedules.setdefault(week, {})[day] = m.text.strip()
    save_json(SCHEDULES_FILE, schedules)
    bot.send_message(m.chat.id, f"✅ Qo‘shildi: {EN_TO_UZ_BTN[day]}", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🗑 Jadval o‘chirish")
def admin_delete_start(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Tepa hafta", "Pastgi hafta", "⬅️ Orqaga")
    bot.send_message(m.chat.id, "🗑 Qaysi haftadan o'chirmoqchisiz?", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in ["Tepa hafta", "Pastgi hafta"] and m.reply_to_message is None)
def admin_delete_choose_week(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    week = "tepa" if "Tepa" in m.text else "pastgi"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for d in ["📘 Dushanba", "📗 Seshanba", "📙 Chorshanba", "📒 Payshanba", "📔 Juma", "📕 Shanba"]:
        kb.add(d)
    kb.add("⬅️ Orqaga")
    bot.send_message(m.chat.id, "🗑 Qaysi kunni o'chirmoqchisiz?", reply_markup=kb)
    bot.register_next_step_handler(m, admin_delete_day_step, week)

def admin_delete_day_step(m, week):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    if m.text not in UZ_BTN_TO_EN:
        bot.send_message(m.chat.id, "❌ Bekor qilindi.", reply_markup=admin_reply_keyboard())
        return
    day = UZ_BTN_TO_EN[m.text]
    if day in schedules.get(week, {}):
        del schedules[week][day]
        save_json(SCHEDULES_FILE, schedules)
        bot.send_message(m.chat.id, f"🗑 {EN_TO_UZ_BTN[day]} o'chirildi.", reply_markup=admin_reply_keyboard())
    else:
        bot.send_message(m.chat.id, "❌ Bu kun uchun jadval topilmadi.", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "🔁 Haftani almashtirish")
def admin_switch_week(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    settings["current_week"] = "pastgi" if settings.get("current_week", "tepa") == "tepa" else "tepa"
    save_json(SETTINGS_FILE, settings)
    bot.send_message(m.chat.id, f"🔄 Hafta turi o'zgardi. Hozir: *{settings['current_week'].capitalize()} hafta*", parse_mode="Markdown", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "📆 Hozirgi hafta turi")
def admin_current_week(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    bot.send_message(m.chat.id, f"📅 Hozir: *{settings.get('current_week','tepa').capitalize()} hafta*", parse_mode="Markdown", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def admin_stats(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    total_users = len(users)
    total_groups = len(groups)
    last_10 = users[-10:] if users else []
    text = f"📊 *Statistika:*\n\n👥 Foydalanuvchilar: *{total_users}*\n👥 Guruhlar: *{total_groups}*\n\n🆔 Oxirgi 10 foydalanuvchi: `{last_10}`"
    bot.send_message(m.chat.id, text, parse_mode="Markdown", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "📤 Barcha foydalanuvchilarga xabar")
def admin_broadcast_start(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    bot.send_message(m.chat.id, "📨 Yubormoqchi bo‘lgan xabaringizni kiriting:")
    bot.register_next_step_handler(m, admin_broadcast_send)

def admin_broadcast_send(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    text = m.text
    count = 0
    for uid in list(users):
        try:
            send_message_safe(uid, f"📢 *ADMIN:* \n\n{text}", reply_markup=main_reply_keyboard(uid))
            count += 1
        except Exception:
            pass
    bot.send_message(m.chat.id, f"✅ Xabar {count} foydalanuvchiga yuborildi.", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "💾 Backup yaratish")
def admin_backup(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    ts = now_tashkent().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"schedules_backup_{ts}.json"
    save_json(backup_file, schedules)
    try:
        with open(backup_file, "rb") as f:
            bot.send_document(m.chat.id, f, caption=f"💾 Backup: {backup_file.name}", reply_markup=admin_reply_keyboard())
    except Exception as e:
        bot.send_message(m.chat.id, f"❌ Backup yuborishda xato: {e}", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "👥 Admin qo'sh / o'chirish")
def admin_manage_admins(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    bot.send_message(m.chat.id, "🧑‍💼 Iltimos, qo'shmoq/ochirmoqchi bo'lgan admin ID sini yuboring (raqam):")
    bot.register_next_step_handler(m, admin_manage_admins_step)

def admin_manage_admins_step(m):
    if not user_is_allowed_as_admin(m.chat.id, m.from_user.id):
        return
    try:
        aid = int(m.text.strip())
    except Exception:
        bot.send_message(m.chat.id, "❌ Noto'g'ri format. Iltimos faqat raqam yuboring.", reply_markup=admin_reply_keyboard())
        return
    admins = settings.get("admins", [])
    if aid in admins:
        admins.remove(aid)
        settings["admins"] = admins
        save_json(SETTINGS_FILE, settings)
        bot.send_message(m.chat.id, f"🗑 Admin (ID: {aid}) o'chirildi.", reply_markup=admin_reply_keyboard())
    else:
        admins.append(aid)
        settings["admins"] = admins
        save_json(SETTINGS_FILE, settings)
        bot.send_message(m.chat.id, f"➕ Yangi admin (ID: {aid}) qo'shildi.", reply_markup=admin_reply_keyboard())

@bot.message_handler(func=lambda m: m.text == "⬅️ Orqaga")
def back_to_main(m):
    send_message_safe(m.chat.id, "🏠 Asosiy menyu:", reply_markup=main_reply_keyboard(m.from_user.id, m.chat.id))

# ========================
# When bot removed from group: cleanup
# ========================
@bot.message_handler(content_types=["left_chat_member"])
def on_left(m):
    # if bot removed, remove group from groups list
    try:
        u = m.left_chat_member
        if u and u.id == bot.get_me().id:
            gid = m.chat.id
            if gid in groups:
                groups.remove(gid)
                save_json(GROUPS_FILE, groups)
    except Exception:
        pass

# ========================
# Start background loops and polling
# ========================
def start_background():
    th = threading.Thread(target=daily_scheduler_loop, daemon=True)
    th.start()
    # schedule reminders for current day on startup
    schedule_reminders_for_today()

if __name__ == "__main__":
    print("🤖 Raspisanie bot ishga tushdi...")
    # register slash commands so "/" in group/private shows /bugun and /ertaga options
    register_bot_commands()
    start_background()
    # Use infinity_polling for continuous operation
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")

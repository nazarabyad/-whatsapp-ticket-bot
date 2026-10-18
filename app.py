import os
import re
import time
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ---- Render environment variables ----
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ZoolTicket123")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1407724379087822")
WHATSAPP_TOKEN = (
    os.environ.get("WHATSAPP_TOKEN")
    or os.environ.get("WHATSAPP_ACCESS_TOKEN")
    or os.environ.get("META_ACCESS_TOKEN")
)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

COMPANY_NAME = "معالجات التقانة والمعلومات والدعم الفني"

# ---- Edit this list: problem types (max 10, each title max 24 characters) ----
PROBLEM_TYPES = [
    "انقطاع الإنترنت",
    "بطء الشبكة",
    "مشكلة في الجهاز",
    "مشكلة في الكهرباء",
    "مشكلة في البرنامج",
    "أخرى",
]

SESSION_TTL = 30 * 60  # seconds
PHONE_RE = re.compile(r"WA:(\d{6,20})")
IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

sessions = {}       # customer number -> state (in memory)
seen_ids = set()    # processed WhatsApp message ids


# ---------------- WhatsApp helpers ----------------
def wa_post(payload):
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload,
            timeout=10,
        )
        print("WhatsApp send status:", r.status_code, r.text)
        return r.status_code == 200
    except Exception as e:
        print(f"WhatsApp send error: {e}")
        return False


def send_whatsapp(to_number, body):
    return wa_post({
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body},
    })


def send_type_list(to_number):
    rows = [{"id": f"type_{i}", "title": t[:24]} for i, t in enumerate(PROBLEM_TYPES)]
    return wa_post({
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": COMPANY_NAME[:60]},
            "body": {"text": "مرحباً بك في خدمة الدعم الفني.\nاختر نوع المشكلة لفتح تذكرة:"},
            "action": {
                "button": "اختر النوع",
                "sections": [{"title": "أنواع المشاكل", "rows": rows}],
            },
        },
    })


def send_photo_buttons(to_number):
    return wa_post({
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "هل تريد إرفاق صورة للمشكلة؟"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "upload", "title": "📷 رفع صورة"}},
                    {"type": "reply", "reply": {"id": "skip", "title": "تخطي"}},
                ]
            },
        },
    })


def download_whatsapp_media(media_id):
    try:
        h = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(
            f"https://graph.facebook.com/v21.0/{media_id}", headers=h, timeout=10
        ).json()
        url = meta.get("url")
        if not url:
            return None
        return requests.get(url, headers=h, timeout=20).content
    except Exception as e:
        print(f"Media download error: {e}")
        return None


# ---------------- Telegram helpers ----------------
def send_telegram(chat_id, text):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        print("Telegram send status:", r.status_code)
    except Exception as e:
        print(f"Telegram send error: {e}")


def send_telegram_photo(chat_id, photo_bytes, caption):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"photo": ("problem.jpg", photo_bytes)},
            timeout=30,
        )
        print("Telegram photo status:", r.status_code)
        return r.status

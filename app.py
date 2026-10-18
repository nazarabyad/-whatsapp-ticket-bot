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

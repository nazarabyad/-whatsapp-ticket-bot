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

PROBLEM_TYPES = [
    "انقطاع الإنترنت",
    "بطء الشبكة",
    "مشكلة في الجهاز",
    "مشكلة في الكهرباء",
    "مشكلة في البرنامج",
    "أخرى",
]

SESSION_TTL = 30 * 60
PHONE_RE = re.compile(r"WA:(\d{6,20})")
IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

sessions = {}
seen_ids = set()
processed_tickets = {}

def wa_post(payload):
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload,
            timeout=10,
        )
        return r.status_code == 200
    except:
        return False

def send_whatsapp(to_number, body):
    return wa_post({"messaging_product": "whatsapp","to": to_number,"type": "text","text": {"body": body}})

def send_type_list(to_number):
    rows = [{"id": f"type_{i}", "title": t[:24]} for i, t in enumerate(PROBLEM_TYPES)]
    return wa_post({"messaging_product": "whatsapp","to": to_number,"type": "interactive","interactive": {"type": "list","header": {"type": "text", "text": COMPANY_NAME[:60]},"body": {"text": "مرحباً بك في خدمة الدعم الفني.\nاختر نوع المشكلة لفتح تذكرة:"},"action": {"button": "اختر النوع","sections": [{"title": "أنواع المشاكل", "rows": rows}]}}})

def send_photo_buttons(to_number):
    return wa_post({"messaging_product": "whatsapp","to": to_number,"type": "interactive","interactive": {"type": "button","body": {"text": "هل تريد إرفاق صورة للمشكلة؟"},"action": {"buttons": [{"type": "reply", "reply": {"id": "upload", "title": "📷 رفع صورة"}},{"type": "reply", "reply": {"id": "skip", "title": "تخطي"}}]}}})

def download_whatsapp_media(media_id):
    try:
        h = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=h, timeout=10).json()
        url = meta.get("url")
        if not url: return None
        return requests.get(url, headers=h, timeout=20).content
    except:
        return None

def send_telegram(chat_id, text):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except: pass

def send_telegram_photo(chat_id, photo_bytes, caption):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", data={"chat_id": chat_id, "caption": caption[:1000]}, files={"photo": ("problem.jpg", photo_bytes)}, timeout=30)
        return r.status_code == 200
    except:
        return False

def edit_telegram_message(chat_id, message_id, original_text, technician_name, reply_text, is_caption=False):
    try:
        khartoum_time = time.strftime("%d/%m %I:%M %p", time.localtime())
        clean_old = original_text
        if "تمت المعالجة - مغلق" in clean_old:
            parts = clean_old.split("----------------------------")
            if len(parts) > 1:
                clean_old = parts[-1].strip()
        new_text = f"""✅ تمت المعالجة - مغلق
👨‍🔧 بواسطة: {technician_name}
🕒 الوقت: {khartoum_time}
💬 الرد: {reply_text}
----------------------------
{clean_old.replace('تذكرة جديدة', 'تذكرة مكتملة ✅')}
"""
        method = "editMessageCaption" if is_caption else "editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id}
        if is_caption:
            payload["caption"] = new_text[:1000]
        else:
            payload["text"] = new_text[:4000]
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=payload, timeout=10)
        print(f"EDIT {message_id}: {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"Edit failed: {e}")
        return False

def finish_ticket(number, name, photo_bytes=None):
    s = sessions.pop(number, {})
    ticket = int(time.time()) % 1000000
    text = f"{COMPANY_NAME}\nتذكرة جديدة #{ticket}\nالعميل: {name or 'غير معروف'}\nالنوع: {s.get('type', '-')}\nIP المركز: {s.get('ip', '-')}\nالموقع: {s.get('location', '-')}\nWA:{number}\n\n(اعمل Reply على هذه الرسالة للرد على العميل)"
    sent = False
    if photo_bytes:
        sent = send_telegram_photo(TELEGRAM_CHAT_ID, photo_bytes, text)
    if not sent:
        send_telegram(TELEGRAM_CHAT_ID, text)
    send_whatsapp(number, f"شكراً لتواصلك مع {COMPANY_NAME}.\nتم فتح تذكرتك رقم #{ticket}، وسيتواصل معك فريق الدعم الفني قريباً.")

def handle_customer_message(msg, name):
    number = msg.get("from")
    msg_type = msg.get("type")
    now = time.time()
    s = sessions.get(number)
    if s and now - s["ts"] > SESSION_TTL:
        s = None
        sessions.pop(number, None)
    text = ""
    if msg_type == "text":
        text = msg.get("text", {}).get("body", "").strip()
    reply_id = None
    if msg_type == "interactive":
        inter = msg.get("interactive", {})
        if inter.get("type") == "list_reply":
            reply_id = inter["list_reply"].get("id")
        elif inter.get("type") == "button_reply":
            reply_id = inter["button_reply"].get("id")
    if text in ("إلغاء", "الغاء", "cancel", "Cancel"):
        sessions.pop(number, None)
        send_type_list(number)
        return
    if not s:
        sessions[number] = {"step": "type", "ts": now}
        send_type_list(number)
        return
    s["ts"] = now
    step = s["step"]
    if step == "type":
        if reply_id and reply_id.startswith("type_"):
            idx = int(reply_id.split("_")[1])
            s["type"] = PROBLEM_TYPES[idx]
            s["step"] = "ip"
            send_whatsapp(number, "اكتب رقم IP المركز (مثال: 192.168.1.10):")
        else:
            send_type_list(number)
    elif step == "ip":
        if msg_type == "text" and IP_RE.match(text):
            s["ip"] = text
            s["step"] = "location"
            send_whatsapp(number, "اكتب اسم المركز ومكانه:")
        else:
            send_whatsapp(number, "رقم IP غير صحيح.")
    elif step == "location":
        if msg_type == "text" and text:
            s["location"] = text
            s["step"] = "photo"
            send_photo_buttons(number)
        else:
            send_whatsapp(number, "اكتب اسم المركز.")
    elif step == "photo":
        if msg_type == "image":
            media_id = msg.get("image", {}).get("id")
            photo = download_whatsapp_media(media_id) if media_id else None
            finish_ticket(number, name, photo)
        elif reply_id == "skip":
            finish_ticket(number, name, None)
        elif reply_id == "upload":
            send_whatsapp(number, "أرسل الصورة الآن.")
        else:
            send_photo_buttons(number)

@app.route("/")
def home():
    return "Bot Live V2 - تمت المعالجة في نفس البلاغ", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def handle_whatsapp():
    try:
        data = request.get_json()
        if data and "entry" in data:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    contacts = value.get("contacts", [])
                    name = contacts[0].get("profile", {}).get("name", "") if contacts else ""
                    for msg in value.get("messages", []):
                        mid = msg.get("id")
                        if mid in seen_ids: continue
                        seen_ids.add(mid)
                        if len(seen_ids) > 2000: seen_ids.clear()
                        if msg.get("from") and WHATSAPP_TOKEN:
                            handle_customer_message(msg, name)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error"}), 200

@app.route("/setup-telegram")
def setup_telegram():
    if not TELEGRAM_BOT_TOKEN: return "TOKEN not set", 400
    try:
        base = request.url_root.replace("http://", "https://")
        me = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10).json()
        hook = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", params={"url": base + "telegram"}, timeout=10).json()
        return jsonify({"bot": me.get("result", {}).get("username"), "webhook_ok": hook.get("ok"), "url": base + "telegram"}), 200
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/telegram", methods=["POST"])
def handle_telegram():
    try:
        update = request.get_json() or {}
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text", "") or "").strip()
        from_user = message.get("from") or {}
        technician_name = f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip() or from_user.get("username","فني")

        if not chat_id:
            return jsonify({"ok": True}), 200
        if text.startswith("/start"):
            send_telegram(chat_id, f"Your chat id is: {chat_id}\nمرحبا {technician_name}")
            return jsonify({"ok": True}), 200

        replied = message.get("reply_to_message")
        if replied and text:
            original_msg_id = replied.get("message_id")
            src = replied.get("text") or replied.get("caption") or ""
            m = PHONE_RE.search(src)
            is_caption = bool(replied.get("caption"))

            if original_msg_id in processed_tickets:
                prev = processed_tickets[original_msg_id]
                send_telegram(chat_id, f"⚠️ ممنوع! البلاغ ده تمت معالجتو قبل كده\n✅ بواسطة: {prev['by']}\n🕒 الوقت: {prev['time']}\nالرد السابق: {prev['reply']}")
                return jsonify({"ok": True}), 200

            if m:
                khartoum_time = time.strftime("%I:%M %p - %d/%m", time.localtime())
                processed_tickets[original_msg_id] = {"by": technician_name, "time": khartoum_time, "reply": text}
                edit_telegram_message(chat_id, original_msg_id, src, technician_name, text, is_caption=is_caption)
                ok = send_whatsapp(m.group(1), f"{text}\n\n- {technician_name} - {COMPANY_NAME}")
                if ok:
                    send_telegram(chat_id, f"✅ تم - البلاغ اتقفل واتكتب فيهو تمت المعالجة بواسطة {technician_name}")
                else:
                    send_telegram(chat_id, "فشل الإرسال للعميل")
            else:
                send_telegram(chat_id, "اعمل Reply على رسالة التذكرة الأصلية")

        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return jsonify({"ok": True}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

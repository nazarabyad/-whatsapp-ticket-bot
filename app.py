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

# ---- جديد: منع التكرار - نخزن البلاغات المكتملة ----
processed_tickets = {}  # message_id -> {by, time, reply}

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
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
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
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram photo error: {e}")
        return False

def edit_telegram_message(chat_id, message_id, new_text, is_caption=False):
    """جديد: يعدل نفس رسالة البلاغ الأساسية"""
    try:
        method = "editMessageCaption" if is_caption else "editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id}
        if is_caption:
            payload["caption"] = new_text[:1000]
        else:
            payload["text"] = new_text[:4000]
        
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
            json=payload,
            timeout=10,
        )
        print(f"Edit message {message_id}: {r.status_code} {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"Edit error: {e}")
        return False

# ---------------- Ticket flow ----------------
def finish_ticket(number, name, photo_bytes=None):
    s = sessions.pop(number, {})
    ticket = int(time.time()) % 1000000
    text = (
        f"{COMPANY_NAME}\n"
        f"تذكرة جديدة #{ticket}\n"
        f"العميل: {name or 'غير معروف'}\n"
        f"النوع: {s.get('type', '-')}\n"
        f"IP المركز: {s.get('ip', '-')}\n"
        f"الموقع: {s.get('location', '-')}\n"
        f"WA:{number}\n\n"
        f"(اعمل Reply على هذه الرسالة للرد على العميل)"
    )
    sent = False
    if photo_bytes:
        sent = send_telegram_photo(TELEGRAM_CHAT_ID, photo_bytes, text)
    if not sent:
        send_telegram(TELEGRAM_CHAT_ID, text)
    send_whatsapp(
        number,
        f"شكراً لتواصلك مع {COMPANY_NAME}.\nتم فتح تذكرتك رقم #{ticket}، وسيتواصل معك فريق الدعم الفني قريباً.",
    )

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
            send_whatsapp(number, "اكتب اسم المركز ومكانه (المدينة / الحي / العنوان):")
        else:
            send_whatsapp(number, "رقم IP غير صحيح. اكتبه بالشكل: 192.168.1.10")
    elif step == "location":
        if msg_type == "text" and text:
            s["location"] = text
            s["step"] = "photo"
            send_photo_buttons(number)
        else:
            send_whatsapp(number, "اكتب اسم المركز أو مكانه كتابةً.")
    elif step == "photo":
        if msg_type == "image":
            media_id = msg.get("image", {}).get("id")
            photo = download_whatsapp_media(media_id) if media_id else None
            finish_ticket(number, name, photo)
        elif reply_id == "skip":
            finish_ticket(number, name, None)
        elif reply_id == "upload":
            send_whatsapp(number, "أرسل الصورة الآن: اضغط على المشبك 📎 ثم اختر الصورة من المعرض أو الكاميرا.")
        else:
            send_photo_buttons(number)

# ---------------- Routes ----------------
@app.route("/")
def home():
    return "WhatsApp Ticket Bot is Live! Webhook: /webhook", 200

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
                        if mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        if len(seen_ids) > 2000:
                            seen_ids.clear()
                        if msg.get("from") and WHATSAPP_TOKEN:
                            handle_customer_message(msg, name)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error"}), 200

@app.route("/subscribe-waba")
def subscribe_waba():
    waba_id = "1166674012694127"
    r = requests.post(
        f"https://graph.facebook.com/v21.0/{waba_id}/subscribed_apps",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=10,
    )
    return r.text, r.status_code

@app.route("/setup-telegram")
def setup_telegram():
    if not TELEGRAM_BOT_TOKEN:
        return "TELEGRAM_BOT_TOKEN is not set", 400
    try:
        base = request.url_root.replace("http://", "https://")
        me = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10).json()
        hook = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            params={"url": base + "telegram"}, timeout=10
        ).json()
        return jsonify({"bot": me.get("result", {}).get("username"), "webhook_ok": hook.get("ok"), "url": base + "telegram"}), 200
    except Exception as e:
        return f"Error: {e}", 500

# ---- هذا المسار عدلناه: يمنع التكرار + يكتب تمت المعالجة في نفس البلاغ ----
@app.route("/telegram", methods=["POST"])
def handle_telegram():
    try:
        update = request.get_json() or {}
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "") or ""
        from_user = message.get("from") or {}
        technician_name = from_user.get("first_name", "") + " " + from_user.get("last_name", "")
        technician_name = technician_name.strip() or from_user.get("username", "فني")

        if not chat_id:
            return jsonify({"ok": True}), 200

        if text.startswith("/start"):
            send_telegram(chat_id, f"Your chat id is: {chat_id}\nمرحبا {technician_name} - سيصلك البلاغ هنا")
            return jsonify({"ok": True}), 200

        # لو شغال في قروب، اسمح لكل القروب
        # لو عندك TELEGRAM_CHAT_ID محدد، تأكد انو نفسو
        if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
            # لو انت عامل قروب - خليك تقبل أي قروب فيهو البوت
            # لو داير تسمح لقروب واحد بس خلي الشرط ده
            # للسماح لكل القروبات: علق السطر الجاي
            pass  # تم تعليق الفلترة عشان كل الفنيين في القروب يشوفو

        replied = message.get("reply_to_message")
        if replied and text:
            original_msg_id = replied.get("message_id")
            src = replied.get("text") or replied.get("caption") or ""
            m = PHONE_RE.search(src)

            # ---- جديد: هل البلاغ ده اتعالج قبل كده؟ ----
            if original_msg_id in processed_tickets:
                prev = processed_tickets[original_msg_id]
                send_telegram(chat_id, 
                    f"⚠️ ممنوع! البلاغ ده تمت معالجتو قبل كده\n✅ بواسطة: {prev['by']}\n🕒 الوقت: {prev['time']}\nالرد السابق: {prev['reply']}")
                return jsonify({"ok": True}), 200

            if m:
                # ---- جديد: احجز البلاغ طوالي عشان مافي فني تاني يعالجو ----
                khartoum_time = time.strftime("%I:%M %p - %d/%m", time.localtime())
                processed_tickets[original_msg_id] = {
                    "by": technician_name,
                    "time": khartoum_time,
                    "reply": text
                }

                # ---- جديد: عدل نفس رسالة البلاغ الأساسية واكتب فيها تمت المعالجة ----
                old_text = src
                new_header = f"✅ تمت المعالجة - مغلق\n👨‍🔧 بواسطة: {technician_name}\n🕒 الوقت: {khartoum_time}\n💬 الرد: {text}\n----------------------------\n\n"
                new_text = new_header + old_text.replace("تذكرة جديدة", "تذكرة مكتملة ✅")

                is_caption = bool(replied.get("caption"))
                edit_telegram_message(chat_id, original_msg_id, new_text, is_caption=is_caption)

                # ارسل للعميل
                ok = send_whatsapp(m.group(1), f"{text}\n\n- {technician_name} - {COMPANY_NAME}")
                
                # رد في القروب
                if ok:
                    send_telegram(chat_id, f"✅ تم - البلاغ اتقفل واتكتب فيهو تمت المعالجة بواسطة {technician_name}")
                else:
                    send_telegram(chat_id, "فشل الإرسال للعميل، راجع Logs.")
            else:
                send_telegram(chat_id, "اعمل Reply على رسالة التذكرة الأصلية للرد على العميل.")

        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Telegram handler error: {e}")
        return jsonify({"ok": True}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

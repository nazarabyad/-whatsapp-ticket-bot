import os
import re
import time
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ---- إعدادات Render ----
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
IP_PREFIX = os.environ.get("IP_PREFIX", "192.186.")

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
IP_FULL_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")

sessions = {}
seen_ids = set()
processed_tickets = {}  # لمنع تكرار المعالجة

# ---------------- WhatsApp helpers ----------------
def wa_post(payload):
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json=payload,
            timeout=15,
        )
        print(f"WhatsApp {r.status_code}: {r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        print(f"WhatsApp error: {e}")
        return False

def send_whatsapp(to_number, body):
    return wa_post({
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body},
    })

def send_main_message(to_number):
    # الرسالة الوحيدة المطلوبة
    return send_whatsapp(to_number,
        "اكتب مشكلتك ورقم IP المركز ومنطقتك ويمكنك إرفاق صورة مع الرسالة 📷\n\n"
        "مثال: النت قاطع - 2.2 - ابوحمد"
    )

def download_whatsapp_media(media_id):
    try:
        h = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        meta = requests.get(f"https://graph.facebook.com/v21.0/{media_id}", headers=h, timeout=10).json()
        url = meta.get("url")
        if not url: return None
        return requests.get(url, headers=h, timeout=20).content
    except Exception as e:
        print(f"Media error: {e}")
        return None

# ---------------- Telegram helpers ----------------
def send_telegram(chat_id, text):
    if not TELEGRAM_BOT_TOKEN: return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        print(f"Telegram {r.status_code}")
    except Exception as e:
        print(f"Telegram error: {e}")

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
        print(f"EDIT {message_id}: {r.text[:300]}")
        return r.status_code == 200
    except Exception as e:
        print(f"Edit failed: {e}")
        return False

# ---------------- تحليل الرسالة الواحدة ----------------
def parse_message(text):
    original = text.strip()
    ip = "-"
    m_full = IP_FULL_RE.search(original)
    if m_full:
        ip = m_full.group(0)
    else:
        shorts = re.findall(r"\b\d{1,3}(?:\.\d{1,3})+\b", original)
        if shorts:
            cand = shorts[0]
            if cand.startswith("216."):
                ip = "192.168." + cand
            elif "." in cand:
                # 2.2 -> 192.186.2.2
                ip = f"192.186.{cand}" if cand.count(".") == 1 else cand

    problem_type = "أخرى"
    if "انقطاع" in original or "قاطع" in original or "فاصل" in original:
        problem_type = "انقطاع الإنترنت"
    elif "بطء" in original or "بطي" in original:
        problem_type = "بطء الشبكة"
    elif "كهرب" in original:
        problem_type = "مشكلة في الكهرباء"
    elif "جهاز" in original:
        problem_type = "مشكلة في الجهاز"
    elif "برنامج" in original or "سيستم" in original:
        problem_type = "مشكلة في البرنامج"

    parts = re.split(r"\s*[-–—]\s*|\n", original)
    parts = [p.strip() for p in parts if p.strip()]
    location = "-"
    description = original

    if len(parts) >= 2:
        # نبحث عن الموقع
        for p in parts:
            if ip != "-" and ip in p: continue
            if p == problem_type: continue
            if re.search(r"[ا-ي]", p) and len(p) < 40:
                if location == "-":
                    location = p
        if len(parts) >= 3:
            location = parts[1] if parts[1] != ip else parts[2] if len(parts) > 2 else "-"
            description = " - ".join(parts[2:]) if len(parts) > 2 else original

    return {"type": problem_type, "ip": ip, "location": location, "description": description, "raw": original}

def finish_ticket(number, name, parsed, photo_bytes=None):
    ticket = int(time.time()) % 1000000
    print(f"New ticket #{ticket} from {number}")
    tg_text = (
        f"{COMPANY_NAME}\n"
        f"تذكرة جديدة #{ticket}\n"
        f"العميل: {name or 'غير معروف'}\n"
        f"النوع: {parsed['type']}\n"
        f"IP المركز: {parsed['ip']}\n"
        f"الموقع: {parsed['location']}\n"
        f"الوصف: {parsed['description']}\n"
        f"WA:{number}\n\n"
        f"(اعمل Reply على هذه الرسالة للرد على العميل)"
    )
    sent = False
    if photo_bytes:
        sent = send_telegram_photo(TELEGRAM_CHAT_ID, photo_bytes, tg_text)
    if not sent:
        send_telegram(TELEGRAM_CHAT_ID, tg_text)
    send_whatsapp(number, f"تم استلام بلاغك ✅ رقم #{ticket}\nالنوع: {parsed['type']}\nIP: {parsed['ip']}\nسيتواصل معك الدعم الفني قريبا.")

def handle_customer_message(msg, name):
    number = msg.get("from")
    msg_type = msg.get("type")
    now = time.time()

    s = sessions.get(number)
    if s and now - s["ts"] > SESSION_TTL:
        sessions.pop(number, None)
        s = None

    text = ""
    photo_bytes = None

    if msg_type == "text":
        text = msg.get("text", {}).get("body", "").strip()
    elif msg_type == "image":
        media_id = msg.get("image", {}).get("id")
        photo_bytes = download_whatsapp_media(media_id) if media_id else None
        text = msg.get("image", {}).get("caption", "") or ""

    print(f"From {number} ({msg_type}): {text[:100]}")

    # تحية أو رسالة قصيرة -> نرسل الرسالة الوحيدة
    greetings = ["سلام", "مرحبا", "اهلا", "السلام عليكم", "hi", "hello", "هلا"]
    if (len(text.strip()) < 4 or any(g in text.lower() for g in greetings)) and not photo_bytes:
        sessions[number] = {"ts": now, "step": "wait"}
        send_main_message(number)
        return

    # لو رسل صورة بدون نص وكنا منتظرين
    if not text and photo_bytes:
        if s and s.get("photo") is None:
            s["photo"] = photo_bytes
            s["ts"] = now
            send_whatsapp(number, "الصورة وصلت ✅ أرسل الآن مشكلتك ورقم IP ومنطقتك في رسالة واحدة")
            return
        else:
            sessions[number] = {"ts": now, "step": "wait", "photo": photo_bytes}
            send_main_message(number)
            return

    if not text:
        send_main_message(number)
        return

    # رسالة فيها تفاصيل -> نحللها طوالي وننشئ تذكرة
    parsed = parse_message(text)
    print(f"Parsed: {parsed}")
    
    # لو معاها صورة محفوظة من قبل
    saved_photo = s.get("photo") if s else None
    final_photo = photo_bytes or saved_photo

    finish_ticket(number, name, parsed, final_photo)
    sessions.pop(number, None)

# ---------------- Routes ----------------
@app.route("/")
def home():
    return f"Bot V5 Full - رسالة واحدة + تمت المعالجة | TELEGRAM set: {bool(TELEGRAM_CHAT_ID)} | WA set: {bool(PHONE_NUMBER_ID)}", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK VERIFIED")
        return challenge, 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def handle_whatsapp():
    try:
        data = request.get_json()
        print(f"Webhook: {str(data)[:800]}")
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
                        handle_customer_message(msg, name)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 200

@app.route("/setup-telegram")
def setup_telegram():
    if not TELEGRAM_BOT_TOKEN: return "TOKEN not set", 400
    try:
        base = request.url_root.replace("http://", "https://")
        me = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=10).json()
        hook = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", params={"url": base + "telegram"}, timeout=10).json()
        return jsonify({"bot": me.get("result", {}).get("username"), "webhook_ok": hook.get("ok"), "url": base + "telegram", "chat_id_env": TELEGRAM_CHAT_ID}), 200
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/telegram", methods=["POST"])
def handle_telegram():
    try:
        update = request.get_json() or {}
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        from_user = message.get("from") or {}
        technician_name = f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip() or from_user.get("username","فني")

        if not chat_id: return jsonify({"ok": True}), 200
        if text.startswith("/start"):
            send_telegram(chat_id, f"Your chat id is: {chat_id}\nمرحبا {technician_name}\n\nانسخ هذا ال ID وضعه في Render في TELEGRAM_CHAT_ID")
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
                ok = wa_send(m.group(1), f"{text}\n\n- {technician_name} - {COMPANY_NAME}") if 'wa_send' in globals() else send_whatsapp(m.group(1), f"{text}\n\n- {technician_name}")
                send_telegram(chat_id, f"✅ تم - البلاغ اتقفل واتكتب فيهو تمت المعالجة بواسطة {technician_name}" if ok else "⚠️ تم الحجز لكن فشل الإرسال للعميل")
            else:
                send_telegram(chat_id, "اعمل Reply على رسالة التذكرة الأصلية للرد على العميل")
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"Telegram handler error: {e}")
        return jsonify({"ok": True}), 200

def wa_send(to, body):
    return send_whatsapp(to, body)

@app.route("/test-send/<number>")
def test_send(number):
    ok = send_main_message(number)
    return f"Send to {number}: {ok}", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

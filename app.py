import os, re, time, requests
from flask import Flask, request, jsonify

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ZoolTicket123")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("WHATSAPP_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

PHONE_RE = re.compile(r"WA:(\d{6,20})")
seen_ids = set()
processed_tickets = {}

def wa_send(to, body):
    try:
        r = requests.post(f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":body}}, timeout=15)
        print(f"WA {r.status_code}: {r.text[:200]}")
        return r.status_code==200
    except Exception as e:
        print(f"WA ERR {e}")
        return False

def tg_send(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id":chat_id,"text":text}, timeout=15)
    except Exception as e:
        print(f"TG ERR {e}")

def tg_send_photo(chat_id, photo_bytes, caption):
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
            data={"chat_id":chat_id,"caption":caption[:1024]},
            files={"photo":("img.jpg",photo_bytes)}, timeout=30)
        return r.status_code==200
    except Exception as e:
        print(f"TG photo ERR {e}")
        return False

def download_media(media_id):
    try:
        h={"Authorization":f"Bearer {WHATSAPP_TOKEN}"}
        meta=requests.get(f"https://graph.facebook.com/v21.0/{media_id}",headers=h,timeout=10).json()
        url=meta.get("url")
        if not url: return None
        return requests.get(url,headers=h,timeout=20).content
    except Exception as e:
        print(f"Media ERR {e}")
        return None

def edit_telegram(chat_id, msg_id, original_text, tech_name, reply_text, is_caption=False):
    try:
        kh=time.strftime("%d/%m %I:%M %p", time.localtime())
        new_text=f"✅ تمت المعالجة - {tech_name} - {kh}\n💬 {reply_text}\n----------------------------\n{original_text}"
        method="editMessageCaption" if is_caption else "editMessageText"
        payload={"chat_id":chat_id,"message_id":msg_id}
        if is_caption: payload["caption"]=new_text[:1024]
        else: payload["text"]=new_text[:4000]
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",json=payload,timeout=10)
    except Exception as e:
        print(f"Edit ERR {e}")

@app.route("/")
def home():
    return "Bot V6 - Text Only Mode | WA OK" if PHONE_NUMBER_ID else "No PHONE ID",200

@app.route("/webhook", methods=["GET"])
def verify():
    mode=request.args.get("hub.mode")
    token=request.args.get("hub.verify_token")
    challenge=request.args.get("hub.challenge")
    if mode=="subscribe" and token==VERIFY_TOKEN:
        print("WEBHOOK VERIFIED")
        return challenge,200
    return "fail",403

@app.route("/webhook", methods=["POST"])
def webhook():
    data=request.get_json() or {}
    print(f"Webhook hit: {str(data)[:500]}")
    try:
        for entry in data.get("entry",[]):
            for change in entry.get("changes",[]):
                value=change.get("value",{})
                for msg in value.get("messages",[]):
                    mid=msg.get("id")
                    if mid in seen_ids: continue
                    seen_ids.add(mid)
                    if len(seen_ids)>2000: seen_ids.clear()
                    
                    frm=msg.get("from")
                    if not frm: continue
                    mtype=msg.get("type")
                    text=""; photo=None
                    
                    if mtype=="text":
                        text=msg.get("text",{}).get("body","").strip()
                    elif mtype=="image":
                        media_id=msg.get("image",{}).get("id")
                        if media_id: photo=download_media(media_id)
                        text=msg.get("image",{}).get("caption","") or ""

                    print(f"FROM {frm}: {text[:100]}")

                    if not text and not photo: continue
                    
                    # رسالة ترحيب
                    if text.lower() in ["سلام","مرحبا","اهلا","السلام عليكم","hi","hello"] and len(text)<15 and not photo:
                        wa_send(frm, "اكتب مشكلتك ورقم IP المركز ومنطقتك ويمكنك إرفاق صورة مع الرسالة 📷\")
                        continue

                    # الرسالة في تليجرام = نص العميل فقط
                    raw = text if text else "صورة مرفقة"
                    tg_text = f"{raw}\n\nWA:{frm}"

                    if photo:
                        ok=tg_send_photo(TELEGRAM_CHAT_ID, photo, tg_text)
                        if not ok: tg_send(TELEGRAM_CHAT_ID, tg_text)
                    else:
                        tg_send(TELEGRAM_CHAT_ID, tg_text)

                    wa_send(frm, "تم الاستلام ✅")
    except Exception as e:
        print(f"Webhook ERR {e}")
    return jsonify({"status":"ok"}),200

@app.route("/telegram", methods=["POST"])
def telegram():
    try:
        update=request.get_json() or {}
        message=update.get("message") or {}
        chat=message.get("chat") or {}
        chat_id=str(chat.get("id",""))
        text=(message.get("text") or "").strip()
        from_user=message.get("from") or {}
        tech=f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip() or from_user.get("username","فني")

        if not chat_id: return jsonify({"ok":True}),200
        
        if text.startswith("/start"):
            tg_send(chat_id, f"Chat ID: {chat_id}\nمرحبا {tech}")
            return jsonify({"ok":True}),200

        replied=message.get("reply_to_message")
        if replied and text:
            orig_id=replied.get("message_id")
            src=replied.get("text") or replied.get("caption") or ""
            m=PHONE_RE.search(src)
            is_cap=bool(replied.get("caption"))

            if orig_id in processed_tickets:
                tg_send(chat_id, f"⚠️ اتعالج قبل كده بواسطة {processed_tickets[orig_id]['by']}")
                return jsonify({"ok":True}),200

            if m:
                processed_tickets[orig_id]={"by":tech, "time":time.strftime("%I:%M %p")}
                edit_telegram(chat_id, orig_id, src, tech, text, is_caption=is_cap)
                wa_send(m.group(1), text)
                tg_send(chat_id, f"✅ تم وقفل البلاغ")
            else:
                tg_send(chat_id, "اعمل Reply على رسالة التذكرة الأصلية")
    except Exception as e:
        print(f"TG handler ERR {e}")
    return jsonify({"ok":True}),200

@app.route("/setup-telegram")
def setup_telegram():
    if not TELEGRAM_BOT_TOKEN: return "No TOKEN",400
    try:
        base=request.url_root.replace("http://","https://")
        url=base+"telegram"
        r=requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook", params={"url":url}, timeout=10).json()
        return jsonify({"webhook":url, "ok":r.get("ok"), "result":r}),200
    except Exception as e:
        return f"Error {e}",500

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)

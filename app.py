import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# المتغيرات من Render Environment
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ZoolTicket123")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1409435178926240")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("WHATSAPP_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
TICKET_API_URL = os.environ.get("TICKET_API_URL", "https://ticket.zoolsay.com/api/whatsapp")

@app.route("/")
def home():
    return "WhatsApp Ticket Bot is Live! Webhook: /webhook", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    print(f"Verify attempt: mode={mode}, token={token}, challenge={challenge}")
    print(f"Expected token: {VERIFY_TOKEN}")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK VERIFIED SUCCESSFULLY!")
        return challenge, 200
    else:
        print(f"Verification FAILED - received token: {token}")
        return "Verification failed", 403

def send_reply(to_number, body):
    """إرسال رد نصي عبر واتساب Cloud API"""
    try:
        r = requests.post(
            f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "text",
                "text": {"body": body},
            },
            timeout=10,
        )
        print("Reply status:", r.status_code, r.text)
    except Exception as e:
        print(f"Reply error: {e}")

@app.route("/webhook", methods=["POST"])
def handle_message():
    try:
        data = request.get_json()
        print(f"Incoming webhook: {data}")

        if data and "entry" in data:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    for msg in messages:
                        # Forward to ticket system
                        try:
                            if TICKET_API_URL:
                                requests.post(TICKET_API_URL, json=data, timeout=5)
                        except Exception as e:
                            print(f"Forward error: {e}")

                        # Auto reply
                        from_number = msg.get("from")
                        msg_type = msg.get("type")
                        if msg_type == "text" and WHATSAPP_TOKEN and from_number:
                            text = msg.get("text", {}).get("body", "")
                            print(f"Message from {from_number}: {text}")
                            send_reply(
                                from_number,
                                "أهلاً بك! استلمنا رسالتك وسيتم ف

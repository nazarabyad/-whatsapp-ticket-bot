import os
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "ZoolTicket123")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1409435178926240")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN") or os.environ.get("WHATSAPP_ACCESS_TOKEN") or os.environ.get("META_ACCESS_TOKEN")
TICKET_API_URL = os.environ.get("TICKET_API_URL", "")

REPLY_TEXT = "Hello! We received your message."

@app.route("/")
def home():
    return "WhatsApp Ticket Bot is Live! Webhook: /webhook", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK VERIFIED SUCCESSFULLY!")
        return challenge, 200
    print(f"Verification FAILED - received token: {token}")
    return "Verification failed", 403

def send_reply(to_number, body):
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
                    for msg in value.get("messages", []):
                        if TICKET_API_URL:
                            try:
                                requests.post(TICKET_API_URL, json=data, timeout=5)
                            except Exception as e:
                                print(f"Forward error: {e}")

                        from_number = msg.get("from")
                        if msg.get("type") == "text" and WHATSAPP_TOKEN and from_number:
                            print(f"Message from {from_number}")
                            send_reply(from_number, REPLY_TEXT)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error handling webhook: {e}")
        return jsonify({"status": "error"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


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

@app.route("/webhook", methods=["POST"])
def handle_message():
    try:
        data = request.get_json()
        print(f"Incoming webhook: {data}")
        
        # Forward to ticket system if configured
        if data and "entry" in data:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    for msg in messages:
                        # Forward to your ticket system
                        try:
                            if TICKET_API_URL:
                                requests.post(TICKET_API_URL, json=data, timeout=5)
                        except Exception as e:
                            print(f"Forward error: {e}")
                        
                        # Optional: auto reply
                        from_number = msg.get("from")
                        msg_type = msg.get("type")
                        if msg_type == "text" and WHATSAPP_TOKEN and from_number:
                            text = msg.get("text", {}).get("body", "")
                            print(f"Message from {from_number}: {text}")
                            # You can add auto-reply here
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error handling webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

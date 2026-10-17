from flask import Flask, request
import random, datetime

app = Flask(__name__)

tickets = {}
ticket_counter = 1000

@app.route('/')
def home():
    return f"Ticket Bot Running ✅ - {len(tickets)} تذكرة"

@app.route('/webhook', methods=['GET','POST'])
def webhook():
    global ticket_counter
    if request.method == 'GET':
        token = request.args.get('hub.verify_token')
        if token == 'nizar123':
            return request.args.get('hub.challenge')
        return "Failed", 403
    
    if request.method == 'POST':
        data = request.get_json()
        print(data)
        try:
            # استخراج رسالة واتساب
            entry = data['entry'][0]['changes'][0]['value']
            if 'messages' in entry:
                msg = entry['messages'][0]
                from_num = msg['from']
                text = msg['text']['body']
                
                ticket_counter += 1
                ticket_id = f"TCK-{ticket_counter}"
                tickets[ticket_id] = {
                    "رقم": from_num,
                    "مشكلة": text,
                    "وقت": str(datetime.datetime.now()),
                    "حالة": "مفتوحة"
                }
                print(f"تذكرة جديدة {ticket_id}: {text}")
        except Exception as e:
            print(f"Error: {e}")
        return "OK", 200

@app.route('/tickets')
def list_tickets():
    html = "<h1>نظام تذاكر المراكز</h1>"
    for tid, t in tickets.items():
        html += f"<p><b>{tid}</b> - {t['مشكلة']} - {t['حالة']} - {t['رقم']}</p>"
    return html

if __name__ == '__main__':
    app.run()

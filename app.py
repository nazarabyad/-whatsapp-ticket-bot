from flask import Flask, request
app = Flask(__name__)

@app.route('/')
def home():
    return "Ticket Bot Running ✅"

@app.route('/webhook', methods=['GET','POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == 'nizar123':
            return request.args.get('hub.challenge')
        return "Failed", 403
    print(request.get_json())
    return "OK", 200

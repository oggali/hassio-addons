from flask import Flask, jsonify
from queue import Queue
from waitress import serve

refresh_queue = Queue()
app = Flask(__name__)

@app.route("/trigger-refresh", methods=["POST"])
def trigger_refresh():
    print("🔁 API refresh request received", flush=True)
    refresh_queue.put("refresh")
    return jsonify({"status": "scheduled"}), 200

def start_server():
    serve(app, host="0.0.0.0", port=8126)

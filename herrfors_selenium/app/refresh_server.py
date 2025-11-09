from flask import Flask, jsonify
from queue import Queue

refresh_queue = Queue()
app = Flask(__name__)

@app.route("/trigger-refresh", methods=["POST"])
def trigger_refresh():
    refresh_queue.put("refresh")
    return jsonify({"status": "scheduled"}), 200

def start_server():
    app.run(host="0.0.0.0", port=8126)

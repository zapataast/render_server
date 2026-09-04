import os
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/")
def home():
    return jsonify({
        "success": True,
        "message": "Flask server is running on Render 🚀"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    }), 200


@app.route("/api/test", methods=["GET", "POST"])
def api_test():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        return jsonify({
            "success": True,
            "method": "POST",
            "received": data
        })

    return jsonify({
        "success": True,
        "method": "GET",
        "message": "API is working"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

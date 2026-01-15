from flask import Flask, jsonify

from api_wrapper import api_bp

app = Flask(__name__)
app.register_blueprint(api_bp)


@app.route("/")
def index():
    return jsonify({
        "service": "ADKAnon",
        "endpoints": {
            "health": "/health",
            "batch": "POST /api/anon",
        },
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

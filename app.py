from flask import Flask, jsonify

from api_wrapper import api_bp

app = Flask(__name__)
app.register_blueprint(api_bp)

try:
    import cv2  # noqa: F401
    print(f"[BOOT] cv2 module path: {cv2.__file__}", flush=True)
except Exception as exc:
    print(f"[BOOT] Unable to import cv2: {exc}", flush=True)


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    import traceback

    print("[ERROR] Unhandled exception:", flush=True)
    traceback.print_exc()
    return jsonify({
        "success": False,
        "error": str(err),
        "type": err.__class__.__name__,
    }), 500


@app.route("/")
def index():
    return jsonify({
        "service": "ADKAnon",
        "endpoints": {
            "health": "/health",
            "batch": "POST /api/anon",
            "status": "GET /api/status/<job_id>",
        },
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

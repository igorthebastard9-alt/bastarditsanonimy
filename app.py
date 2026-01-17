import os

os.environ.setdefault("HOME", "/app")
os.environ.setdefault("KERAS_HOME", "/app/.keras")
os.environ.setdefault("XDG_CACHE_HOME", "/app/.cache")
os.makedirs(os.path.join(os.environ["KERAS_HOME"], "models"), exist_ok=True)
os.makedirs(os.environ["XDG_CACHE_HOME"], exist_ok=True)

from flask import Flask, jsonify

from api_wrapper import api_bp, MODEL_SIZE_BYTES, PRIMARY_MODEL_PATH, ensure_model_weights

app = Flask(__name__)
app.register_blueprint(api_bp)

try:
    import cv2  # noqa: F401
    print(f"[BOOT] cv2 module path: {cv2.__file__}", flush=True)
except Exception as exc:
    print(f"[BOOT] Unable to import cv2: {exc}", flush=True)

print(f"[BOOT] KERAS_HOME={os.environ['KERAS_HOME']}", flush=True)
print(f"[BOOT] XDG_CACHE_HOME={os.environ['XDG_CACHE_HOME']}", flush=True)

ensure_model_weights()
if os.path.exists(PRIMARY_MODEL_PATH):
    print(f"[BOOT] extractor exists: true size: {os.path.getsize(PRIMARY_MODEL_PATH)}", flush=True)
    if os.path.getsize(PRIMARY_MODEL_PATH) != MODEL_SIZE_BYTES:
        print(f"[BOOT] WARNING: extractor size mismatch (expected {MODEL_SIZE_BYTES})", flush=True)
else:
    print(f"[BOOT] extractor exists: false size: 0", flush=True)


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

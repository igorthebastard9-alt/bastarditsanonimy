import base64
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

api_bp = Blueprint("api", __name__)


REQUIRED_FILE_COUNT = 4


def _get_api_key() -> str:
    return os.environ.get("ADKANON_API_KEY", "")


def _verify_api_key() -> bool:
    expected = _get_api_key()
    provided = request.headers.get("x-api-key", "")
    return bool(expected) and provided == expected


def _script_path() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "adkanon.py")


@api_bp.route("/health", methods=["GET"])
def health() -> "flask.Response":
    return jsonify({"ok": True, "service": "adkanon"})


@api_bp.route("/api/anon", methods=["POST"])
def run_batch():
    try:
        if not _verify_api_key():
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        if "files" not in request.files:
            return jsonify({"success": False, "error": "No files provided", "details": "Upload exactly 4 images using the 'files' field."}), 400

        uploads: List = [f for f in request.files.getlist("files") if f and f.filename]
        if len(uploads) != REQUIRED_FILE_COUNT:
            return jsonify({
                "success": False,
                "error": "Invalid file count",
                "details": f"Provide exactly {REQUIRED_FILE_COUNT} files.",
            }), 400

        job_dir = tempfile.mkdtemp(prefix="adkanon_job_")
        job_input = os.path.join(job_dir, "input")
        job_output = os.path.join(job_dir, "output")
        os.makedirs(job_input, exist_ok=True)
        os.makedirs(job_output, exist_ok=True)

        try:
            for upload in uploads:
                filename = secure_filename(upload.filename) or "image.jpg"
                upload.save(os.path.join(job_input, filename))

            script_path = _script_path()
            if not os.path.exists(script_path):
                return jsonify({"success": False, "error": "Processing script missing"}), 500

            command = [sys.executable, script_path]
            result = subprocess.run(
                command,
                cwd=job_dir,
                check=False,
                capture_output=True,
                text=True,
            )

            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")

            if result.returncode != 0:
                combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
                return jsonify({
                    "success": False,
                    "error": "Anonymization failed",
                    "details": combined_output[-2000:],
                }), 500

            produced = []
            for root, _, files in os.walk(job_output):
                for file_name in files:
                    produced.append(os.path.join(root, file_name))

            if len(produced) != REQUIRED_FILE_COUNT:
                return jsonify({
                    "success": False,
                    "error": "Unexpected output",
                    "details": f"Expected {REQUIRED_FILE_COUNT} files, found {len(produced)}",
                }), 500

            payload = []
            for file_path in sorted(produced):
                with open(file_path, "rb") as fh:
                    encoded = base64.b64encode(fh.read()).decode("ascii")
                mime_type, _ = mimetypes.guess_type(file_path)
                payload.append({
                    "filename": os.path.basename(file_path),
                    "content_type": mime_type or "application/octet-stream",
                    "data": encoded,
                })

            return jsonify({"success": True, "files": payload})
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": "Unhandled server error", "details": str(exc)}), 500

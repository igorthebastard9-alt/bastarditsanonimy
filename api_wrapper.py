import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import List

from flask import Blueprint, jsonify, request, send_file
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
    if not _verify_api_key():
        return jsonify({"error": "Unauthorized"}), 401

    if "files" not in request.files:
        return jsonify({"error": "No files provided", "details": "Upload exactly 4 images using the 'files' field."}), 400

    uploads: List = [f for f in request.files.getlist("files") if f and f.filename]
    if len(uploads) != REQUIRED_FILE_COUNT:
        return jsonify({
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
            return jsonify({"error": "Processing script missing"}), 500

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
                "error": "Anonymization failed",
                "details": combined_output[-2000:],
            }), 500

        produced = []
        for root, _, files in os.walk(job_output):
            for file_name in files:
                produced.append(os.path.join(root, file_name))

        if len(produced) != REQUIRED_FILE_COUNT:
            return jsonify({
                "error": "Unexpected output",
                "details": f"Expected {REQUIRED_FILE_COUNT} files, found {len(produced)}",
            }), 500

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file_path in produced:
                arcname = os.path.basename(file_path)
                bundle.write(file_path, arcname)
        memory_file.seek(0)

        return send_file(
            memory_file,
            as_attachment=True,
            download_name="anon.zip",
            mimetype="application/zip",
        )
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

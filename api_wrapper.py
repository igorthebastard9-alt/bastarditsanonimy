import base64
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

api_bp = Blueprint("api", __name__)


REQUIRED_FILE_COUNT = 4

_jobs: Dict[str, Dict[str, object]] = {}
_jobs_lock = threading.Lock()


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _create_job(job_dir: str) -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": _now(),
            "updated_at": _now(),
            "logs": [],
            "error": None,
            "output_files": None,
            "job_dir": job_dir,
        }
    return job_id


def _append_log(job_id: str, message: str) -> None:
    entry = f"[{_now()}] {message}"
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.setdefault("logs", []).append(entry)
            job["updated_at"] = _now()
    print(f"[JOB {job_id}] {message}", flush=True)


def _update_job(job_id: str, *, status: Optional[str] = None, error: Optional[str] = None, output_files: Optional[List[dict]] = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        if status is not None:
            job["status"] = status
        if error is not None:
            job["error"] = error
        if output_files is not None:
            job["output_files"] = output_files
        job["updated_at"] = _now()


def _get_job(job_id: str) -> Optional[Dict[str, object]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return dict(job)


def _execute_job(job_id: str, job_dir: str, job_input: str, job_output: str) -> None:
    _update_job(job_id, status="running")
    _append_log(job_id, "Starting Fawkes subprocess")
    script_path = _script_path()
    if not os.path.exists(script_path):
        _append_log(job_id, "adkanon.py script missing")
        _update_job(job_id, status="failed", error="Processing script missing")
        return

    command = [sys.executable, script_path]
    try:
        result = subprocess.run(
            command,
            cwd=job_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                _append_log(job_id, f"STDOUT: {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                _append_log(job_id, f"STDERR: {line}")

        if result.returncode != 0:
            combined_output = (result.stdout or "") + "\n" + (result.stderr or "")
            error_message = combined_output[-2000:].strip() or "Fawkes process failed"
            _append_log(job_id, f"Process exited with code {result.returncode}")
            _update_job(job_id, status="failed", error=error_message)
            return

        produced = []
        for root, _, files in os.walk(job_output):
            for file_name in files:
                produced.append(os.path.join(root, file_name))
        if len(produced) != REQUIRED_FILE_COUNT:
            message = f"Expected {REQUIRED_FILE_COUNT} files, found {len(produced)}"
            _append_log(job_id, message)
            _update_job(job_id, status="failed", error=message)
            return

        payload = []
        for file_path in sorted(produced):
            try:
                with open(file_path, "rb") as fh:
                    encoded = base64.b64encode(fh.read()).decode("ascii")
                mime_type, _ = mimetypes.guess_type(file_path)
                payload.append({
                    "filename": os.path.basename(file_path),
                    "content_type": mime_type or "application/octet-stream",
                    "data": encoded,
                })
                _append_log(job_id, f"Prepared output file {os.path.basename(file_path)}")
            except Exception as exc:  # noqa: BLE001
                _append_log(job_id, f"Failed to read output {file_path}: {exc}")
                _update_job(job_id, status="failed", error=str(exc))
                return

        _update_job(job_id, status="succeeded", output_files=payload)
        _append_log(job_id, "Job completed successfully")
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _append_log(job_id, f"Unhandled exception: {exc}")
        _update_job(job_id, status="failed", error=str(exc))
    finally:
        try:
            shutil.rmtree(job_dir, ignore_errors=True)
            _append_log(job_id, "Cleaned up job workspace")
        except Exception as cleanup_exc:  # noqa: BLE001
            _append_log(job_id, f"Failed to cleanup job dir: {cleanup_exc}")


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


@api_bp.route("/api/status/<job_id>", methods=["GET"])
def job_status(job_id: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify({"success": False, "error": "Job not found"}), 404
    response: Dict[str, object] = {
        "success": job.get("status") == "succeeded",
        "job_id": job_id,
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "logs": job.get("logs", []),
    }
    if job.get("status") == "succeeded":
        response["files"] = job.get("output_files")
    if job.get("error"):
        response["error"] = job.get("error")
    return jsonify(response)


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

        for upload in uploads:
            filename = secure_filename(upload.filename) or "image.jpg"
            destination = os.path.join(job_input, filename)
            upload.save(destination)

        job_id = _create_job(job_dir)
        _append_log(job_id, "Job enqueued; files saved")

        thread = threading.Thread(target=_execute_job, args=(job_id, job_dir, job_input, job_output), daemon=True)
        thread.start()

        return jsonify({"success": True, "job_id": job_id, "status": "queued"})
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": "Unhandled server error", "details": str(exc)}), 500

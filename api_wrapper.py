import base64
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timedelta
from importlib import resources as importlib_resources
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

api_bp = Blueprint("api", __name__)


LOG_CHAR_LIMIT = 10_000
JOB_TTL_SECONDS = 30 * 60
CLEANUP_INTERVAL_SECONDS = 60

# This service now treats each request as a single-image job. Earlier versions tried to
# anonymize four images in one batch and infer progress by parsing TensorFlow/Keras stdout.
# That approach proved unreliable because library logs are noisy and can change across
# releases. Parsing stdout to drive state transitions also risked deadlocks and races.
# The refactored design launches exactly one subprocess per image and derives job status
# only from the process lifecycle and the presence of the expected output file; stdout is
# kept purely for debugging, never for correctness.

_jobs: Dict[str, Dict[str, object]] = {}
_jobs_lock = threading.Lock()
_cleanup_started = False

MODEL_URL = "https://mirror.cs.uchicago.edu/fawkes/files/extractor_2.h5"
MODEL_SIZE_BYTES = 161_829_576
PRIMARY_MODEL_PATH = "/app/.keras/models/extractor_2.h5"


def _file_ok(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) == MODEL_SIZE_BYTES


def ensure_model_weights() -> None:
    os.environ.setdefault("KERAS_HOME", "/app/.keras")
    os.environ.setdefault("XDG_CACHE_HOME", "/app/.cache")
    os.makedirs("/app/.keras/models", exist_ok=True)
    os.makedirs("/app/.cache", exist_ok=True)

    target_path = PRIMARY_MODEL_PATH
    if _file_ok(target_path):
        return

    print(f"[BOOT] extractor cache missing or invalid at {target_path}; downloading...", flush=True)
    fd, temp_path = tempfile.mkstemp(prefix="extractor_2_", suffix=".h5", dir=os.path.dirname(target_path))
    os.close(fd)
    try:
        with urllib.request.urlopen(MODEL_URL) as response, open(temp_path, "wb") as outfile:
            shutil.copyfileobj(response, outfile)
        if not _file_ok(temp_path):
            raise ValueError("downloaded file size mismatch")
        os.replace(temp_path, target_path)
        print(f"[BOOT] extractor downloaded to {target_path}", flush=True)
    except Exception as exc:  # noqa: BLE001
        if os.path.exists(temp_path):
            os.remove(temp_path)
        print(f"[BOOT] ERROR downloading extractor weights: {exc}", flush=True)
        raise

    # Best-effort copy into fawkes package directory
    try:
        package_dir = importlib_resources.files("fawkes") / "model"
        os.makedirs(package_dir, exist_ok=True)
        package_target = package_dir / "extractor_2.h5"
        if not package_target.exists() or package_target.stat().st_size != MODEL_SIZE_BYTES:
            shutil.copy2(target_path, package_target)
            print(f"[BOOT] extractor copied into {package_target}", flush=True)
        else:
            print(f"[BOOT] extractor already present in {package_target}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[BOOT] Warning: unable to copy weights into package directory: {exc}", flush=True)



def _now() -> datetime:
    return datetime.utcnow()


def _format_time(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds") + "Z"


def _create_job(job_dir: str) -> str:
    job_id = uuid.uuid4().hex
    now = _now()
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "last_heartbeat": now,
            "completed_at": None,
            "logs": [],
            "log_chars": 0,
            "error": None,
            "output": None,
            "job_dir": job_dir,
        }
    _ensure_cleanup_thread()
    return job_id


def _ensure_cleanup_thread() -> None:
    global _cleanup_started
    with _jobs_lock:
        if _cleanup_started:
            return
        _cleanup_started = True
        thread = threading.Thread(target=_cleanup_loop, name="adkanon-cleaner", daemon=True)
        thread.start()


def _cleanup_loop() -> None:
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        now = _now()
        expired: List[str] = []
        with _jobs_lock:
            for job_id, job in list(_jobs.items()):
                status = job.get("status")
                completed_at: Optional[datetime] = job.get("completed_at")
                if status in {"succeeded", "failed"} and completed_at:
                    if now - completed_at > timedelta(seconds=JOB_TTL_SECONDS):
                        expired.append(job_id)
            for job_id in expired:
                job = _jobs.pop(job_id, None)
                if job:
                    job_dir = job.get("job_dir")
                    if job_dir and os.path.exists(job_dir):
                        try:
                            shutil.rmtree(job_dir, ignore_errors=True)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[CLEANUP] Failed to remove dir {job_dir}: {exc}", flush=True)
        if expired:
            print(f"[CLEANUP] Removed jobs: {', '.join(expired)}", flush=True)


def _append_log(job_id: str, message: str) -> None:
    timestamp = _format_time(_now())
    entry = f"[{timestamp}] {message}"
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            logs = job.setdefault("logs", [])
            logs.append(entry)
            job["log_chars"] = job.get("log_chars", 0) + len(entry)
            while logs and job["log_chars"] > LOG_CHAR_LIMIT:
                removed = logs.pop(0)
                job["log_chars"] -= len(removed)
            now = _now()
            job["updated_at"] = now
            job["last_heartbeat"] = now
    print(f"[JOB {job_id}] {message}", flush=True)


def _update_job(job_id: str, *, status: Optional[str] = None, error: Optional[str] = None, output: Optional[dict] = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        now = _now()
        if status is not None:
            job["status"] = status
        if error is not None:
            job["error"] = error
        if output is not None:
            job["output"] = output
        job["updated_at"] = now
        job["last_heartbeat"] = now
        if job.get("status") in {"succeeded", "failed"}:
            job["completed_at"] = now


def _get_job(job_id: str) -> Optional[Dict[str, object]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return dict(job)


def _serialize_job(job: Dict[str, object]) -> Dict[str, object]:
    created_at = job.get("created_at", _now())
    updated_at = job.get("updated_at", _now())
    response: Dict[str, object] = {
        "success": job.get("status") == "succeeded",
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "created_at": _format_time(created_at if isinstance(created_at, datetime) else _now()),
        "updated_at": _format_time(updated_at if isinstance(updated_at, datetime) else _now()),
        "logs": job.get("logs", []),
    }
    completed_at = job.get("completed_at")
    if completed_at:
        response["completed_at"] = _format_time(completed_at if isinstance(completed_at, datetime) else _now())
    if job.get("error"):
        response["error"] = job.get("error")
    if job.get("status") == "succeeded" and job.get("output"):
        response["file"] = job.get("output")
    return response


def _touch_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            now = _now()
            job["updated_at"] = now
            job["last_heartbeat"] = now


def _stream_reader(job_id: str, pipe, prefix: str) -> None:
    try:
        with pipe:
            for line in pipe:
                _append_log(job_id, f"{prefix}: {line.rstrip()}")
    except Exception as exc:  # noqa: BLE001
        _append_log(job_id, f"{prefix} reader error: {exc}")


def _execute_job(job_id: str, job_dir: str, job_input: str, job_output: str) -> None:
    """Run Fawkes on a single image in the background.

    We deliberately avoid any stdout-based progress heuristics; job status depends solely on
    the subprocess exit code and whether exactly one output file was produced."""
    _update_job(job_id, status="running")
    _append_log(job_id, "Job started")
    _append_log(job_id, "Starting Fawkes subprocess")
    script_path = _script_path()
    if not os.path.exists(script_path):
        _append_log(job_id, "adkanon.py script missing")
        _update_job(job_id, status="failed", error="Processing script missing")
        return

    command = [sys.executable, script_path]
    try:
        process = subprocess.Popen(
            command,
            cwd=job_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout_thread = threading.Thread(target=_stream_reader, args=(job_id, process.stdout, "STDOUT"), daemon=True)
        stderr_thread = threading.Thread(target=_stream_reader, args=(job_id, process.stderr, "STDERR"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        while True:
            retcode = process.poll()
            _touch_job(job_id)
            if retcode is not None:
                break
            time.sleep(0.5)

        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        if process.returncode != 0:
            message = f"Process exited with code {process.returncode}"
            _append_log(job_id, message)
            _update_job(job_id, status="failed", error=message)
            return

        produced = []
        for root, _, files in os.walk(job_output):
            for file_name in files:
                if file_name.lower().endswith((".jpg", ".jpeg", ".png")):
                    produced.append(os.path.join(root, file_name))

        if not produced:
            message = "No output file produced"
            _append_log(job_id, f"Job failed: {message}")
            _update_job(job_id, status="failed", error=message)
            return
        if len(produced) > 1:
            message = f"Expected 1 output file, found {len(produced)}"
            _append_log(job_id, f"Job failed: {message}")
            _update_job(job_id, status="failed", error=message)
            return

        output_path = produced[0]
        try:
            with open(output_path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("ascii")
            mime_type, _ = mimetypes.guess_type(output_path)
            payload = {
                "filename": os.path.basename(output_path),
                "content_type": mime_type or "application/octet-stream",
                "data": encoded,
            }
            _append_log(job_id, f"Prepared output file {os.path.basename(output_path)}")
        except Exception as exc:  # noqa: BLE001
            _append_log(job_id, f"Job failed: unable to read output {output_path}: {exc}")
            _update_job(job_id, status="failed", error=str(exc))
            return

        _append_log(job_id, "Job finished successfully")
        _update_job(job_id, status="succeeded", output=payload)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        _append_log(job_id, f"Job failed: {exc}")
        _update_job(job_id, status="failed", error=str(exc))
    finally:
        _append_log(job_id, "Job finished; scheduled for cleanup")


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
    return jsonify(_serialize_job(job))


@api_bp.route("/api/anon", methods=["POST"])
def run_batch():
    """Accept exactly one image, enqueue anonymization, and return a job id."""
    try:
        if not _verify_api_key():
            return jsonify({"success": False, "error": "Unauthorized"}), 401

        if "files" not in request.files:
            return jsonify({"success": False, "error": "No file provided", "details": "Upload exactly one image using the 'files' field."}), 400

        uploads: List = [f for f in request.files.getlist("files") if f and f.filename]
        if len(uploads) != 1:
            return jsonify({
                "success": False,
                "error": "Invalid file count",
                "details": "Provide exactly one image per request.",
            }), 400

        job_dir = tempfile.mkdtemp(prefix="adkanon_job_")
        job_input = os.path.join(job_dir, "input")
        job_output = os.path.join(job_dir, "output")
        os.makedirs(job_input, exist_ok=True)
        os.makedirs(job_output, exist_ok=True)

        upload = uploads[0]
        filename = secure_filename(upload.filename) or "image.jpg"
        destination = os.path.join(job_input, filename)
        upload.save(destination)

        script_path = _script_path()
        if not os.path.exists(script_path):
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"success": False, "error": "Processing script missing"}), 500

        job_id = _create_job(job_dir)
        _append_log(job_id, "Job enqueued; files saved")

        thread = threading.Thread(target=_execute_job, args=(job_id, job_dir, job_input, job_output), daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "job_id": job_id,
            "status": "queued",
        })
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": "Unhandled server error", "details": str(exc)}), 500

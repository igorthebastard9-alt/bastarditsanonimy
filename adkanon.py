import glob
import os
import shutil
import traceback
from datetime import datetime
from typing import List

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")

from fawkes.protection import Fawkes  # noqa: E402


LOG_PREFIX = "[LOG {timestamp}] {message}"
ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png")
DEFAULT_MODE = os.environ.get("ADKANON_MODE", "low")
DEFAULT_BATCH_SIZE = int(os.environ.get("ADKANON_BATCH_SIZE", "1"))
DEFAULT_FORMAT = os.environ.get("ADKANON_OUTPUT_FORMAT", "png").lower()
FEATURE_EXTRACTOR = os.environ.get("ADKANON_EXTRACTOR", "extractor_2")


def log(message: str) -> None:
    print(
        LOG_PREFIX.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            message=message,
        ),
        flush=True,
    )


def _normalized_format(fmt: str) -> str:
    fmt = fmt.lower().strip()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in {"png", "jpeg"}:
        log(f"Unsupported format '{fmt}', defaulting to png")
        fmt = "png"
    return fmt


OUTPUT_FORMAT = _normalized_format(DEFAULT_FORMAT)


def _gather_image_paths(directory: str) -> List[str]:
    matched: List[str] = []
    for entry in sorted(glob.glob(os.path.join(directory, "*"))):
        if entry.lower().endswith(ALLOWED_EXTENSIONS) and os.path.isfile(entry):
            matched.append(entry)
    return matched


def process_batch(input_dir: str, output_dir: str) -> bool:
    os.makedirs(output_dir, exist_ok=True)
    image_paths = _gather_image_paths(input_dir)
    if not image_paths:
        log("No compatible images found; skipping Fawkes run")
        return False

    try:
        log(
            "Launching Fawkes cloaking (mode={mode}, batch_size={batch}, format={fmt}, extractor={extractor})".format(
                mode=DEFAULT_MODE,
                batch=DEFAULT_BATCH_SIZE,
                fmt=OUTPUT_FORMAT,
                extractor=FEATURE_EXTRACTOR,
            )
        )
        protector = Fawkes(
            feature_extractor=FEATURE_EXTRACTOR,
            gpu=None,
            batch_size=DEFAULT_BATCH_SIZE,
            mode=DEFAULT_MODE,
        )
        status = protector.run_protection(
            image_paths,
            batch_size=DEFAULT_BATCH_SIZE,
            format=OUTPUT_FORMAT,
            separate_target=False,
            debug=False,
            no_align=False,
            save_last_on_failed=True,
        )
    except Exception as exc:
        log(f"Fawkes execution failed: {exc}")
        log(traceback.format_exc())
        return False

    if status != 1:
        status_map = {
            2: "No face detected in supplied images",
            3: "No images available for processing",
        }
        log(status_map.get(status, f"Fawkes returned non-success status code {status}"))
        return False

    success = True
    for src_path in image_paths:
        cloaked_path = f"{os.path.splitext(src_path)[0]}_cloaked.{OUTPUT_FORMAT}"
        if not os.path.exists(cloaked_path):
            log(f"Expected cloaked file missing: {cloaked_path}")
            success = False
            continue
        destination = os.path.join(output_dir, os.path.basename(cloaked_path))
        shutil.move(cloaked_path, destination)
        log(f"Generated cloaked image: {destination}")

    return success


if __name__ == "__main__":
    base_dir = os.getcwd()
    input_dir = os.path.join(base_dir, "input")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    log("ADKAnon Fawkes batch start")
    if not process_batch(input_dir, output_dir):
        log("Fawkes cloaking completed with errors")
        exit(1)

    log("Fawkes cloaking complete")

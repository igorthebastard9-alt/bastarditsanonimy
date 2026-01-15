import os
import random
import shutil
import traceback
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
from PIL import Image


LOG_PREFIX = "[LOG {timestamp}] {message}"


def log(message: str) -> None:
    print(LOG_PREFIX.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message=message), flush=True)


def strip_metadata(source_path: str, temp_path: str) -> bool:
    """Re-save the image without EXIF metadata."""
    try:
        with Image.open(source_path) as img:
            img.convert("RGB").save(temp_path, format="JPEG", quality=95)
        log(f"Metadata stripped for {os.path.basename(source_path)}")
        return True
    except Exception as exc:
        log(f"Failed to strip metadata for {source_path}: {exc}")
        log(traceback.format_exc())
        return False


def _pixelate(image: np.ndarray, factor: int = 12) -> np.ndarray:
    h, w = image.shape[:2]
    factor = max(2, min(factor, min(h, w) // 4 or 2))
    temp = cv2.resize(image, (w // factor, h // factor), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(temp, (w, h), interpolation=cv2.INTER_NEAREST)
    return pixelated


def _apply_random_masks(image: np.ndarray, overlays: int = 5) -> np.ndarray:
    mask = image.copy()
    h, w = mask.shape[:2]
    for _ in range(overlays):
        top_left = (random.randint(0, w - 1), random.randint(0, h - 1))
        size_w = random.randint(w // 10, w // 3)
        size_h = random.randint(h // 10, h // 3)
        bottom_right = (
            min(w - 1, top_left[0] + size_w),
            min(h - 1, top_left[1] + size_h),
        )
        color = [random.randint(0, 255) for _ in range(3)]
        alpha = random.uniform(0.35, 0.7)
        sub = mask[top_left[1] : bottom_right[1], top_left[0] : bottom_right[0]]
        if sub.size == 0:
            continue
        overlay = np.zeros_like(sub, dtype=np.uint8)
        overlay[:] = color
        cv2.addWeighted(overlay, alpha, sub, 1 - alpha, 0, dst=sub)
    return mask


def _add_noise(image: np.ndarray, sigma: float = 18.0) -> np.ndarray:
    noise = np.random.normal(0, sigma, image.shape).astype(np.float32)
    noisy = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return noisy


def _apply_mixed_anonymization(image: np.ndarray) -> np.ndarray:
    log("Applying anonymization pipeline")
    pixel_factor = random.randint(8, 18)
    log(f"Pixelation factor selected: {pixel_factor}")
    anonymized = _pixelate(image, factor=pixel_factor)

    anonymized = _add_noise(anonymized, sigma=random.uniform(10, 22))
    log("Noise overlay applied")

    anonymized = _apply_random_masks(anonymized, overlays=random.randint(3, 6))
    log("Random obfuscation masks applied")

    blur_kernel = random.choice([(11, 11), (15, 15)])
    anonymized = cv2.GaussianBlur(anonymized, blur_kernel, sigmaX=0)
    log(f"Gaussian blur applied with kernel {blur_kernel}")

    return anonymized


def anonymize_image(source_path: str, destination_path: str) -> bool:
    log(f"Processing {source_path}")
    temp_path = destination_path + ".tmp"
    if not strip_metadata(source_path, temp_path):
        return False

    image = cv2.imread(temp_path)
    if image is None:
        log(f"Failed to read image {temp_path}")
        return False

    anonymized = _apply_mixed_anonymization(image)

    try:
        cv2.imwrite(destination_path, anonymized, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        log(f"Anonymized image saved to {destination_path}")
        return True
    except Exception as exc:
        log(f"Failed to write anonymized image {destination_path}: {exc}")
        log(traceback.format_exc())
        return False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            log(f"Temporary file cleaned: {temp_path}")


def process_batch(input_dir: str, output_dir: str) -> bool:
    success = True
    os.makedirs(output_dir, exist_ok=True)
    entries = [f for f in sorted(os.listdir(input_dir)) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    if not entries:
        log("No compatible images found for anonymization")
        return False

    for filename in entries:
        source_path = os.path.join(input_dir, filename)
        basename = os.path.splitext(filename)[0]
        destination_path = os.path.join(
            output_dir,
            f"anon_{basename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}.jpg",
        )
        if not anonymize_image(source_path, destination_path):
            success = False
    return success


if __name__ == "__main__":
    base_dir = os.getcwd()
    input_dir = os.path.join(base_dir, "input")
    output_dir = os.path.join(base_dir, "output")

    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    log("ADKAnon batch anonymizer started")
    batch_success = process_batch(input_dir, output_dir)
    if not batch_success:
        log("Anonymization completed with errors")
        exit(1)

    log("Anonymization complete")

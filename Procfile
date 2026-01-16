web: bash -lc "pip uninstall -y opencv-python || true; gunicorn app:app --bind 0.0.0.0:$PORT --timeout 180 --graceful-timeout 30 --access-logfile - --error-logfile -"

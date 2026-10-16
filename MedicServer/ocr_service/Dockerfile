FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/legacy \
    FLAGS_use_mkldnn=0

RUN apt-get update && apt-get install -y --no-install-recommends \
      libglib2.0-0 libgl1 libgomp1 libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ocr_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY ocr_service/patch_paddleocr.py /tmp/patch_paddleocr.py
RUN python /tmp/patch_paddleocr.py && rm /tmp/patch_paddleocr.py
COPY ocr_service/app /app/app
COPY ocr_service/legacy /app/legacy

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads /data/results /home/appuser/.paddleocr \
    && chown -R appuser:appuser /app /data /home/appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


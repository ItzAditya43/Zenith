FROM python:3.11-slim

WORKDIR /app

# System deps: libmagic1 is used by app/services/attachments.py for MIME
# sniffing. ffmpeg was previously installed for video frame extraction but
# that feature is not implemented, so it has been removed to slim the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8420

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
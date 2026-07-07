FROM python:3.11-slim

WORKDIR /app

# System deps for python-magic and ffmpeg (used by attachment + video services)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8420

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
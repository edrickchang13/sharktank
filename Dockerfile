FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Vision Agents feat/tencent-rtc, install plugins editable. Tencent plugin
# (liteav) is skipped; agent.py falls back to getstream.Edge() automatically.
RUN git clone --depth 1 --branch feat/tencent-rtc \
    https://github.com/GetStream/vision-agents.git /tmp/va

RUN pip install --no-cache-dir \
    -e /tmp/va/agents-core \
    -e /tmp/va/plugins/gemini \
    -e /tmp/va/plugins/getstream \
    -e /tmp/va/plugins/smart_turn \
    -e /tmp/va/plugins/tencent

RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    websockets \
    python-dotenv \
    cos-python-sdk-v5 \
    google-genai \
    opencv-python-headless

COPY . /app

EXPOSE 8000
CMD ["python", "main.py"]

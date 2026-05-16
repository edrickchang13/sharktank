# Builds the FastAPI HTTP+WS server image (main.py).
# The LiveKit Agent worker is a SEPARATE process (python agent.py start).
# Run two containers in production, or override CMD to launch the worker.
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

# Python deps, LiveKit Agents + LemonSlice + Google Gemini + COS + FastAPI.
# Version pins from /tmp/lemonslice-ref/.../agent/pyproject.toml.
RUN pip install --no-cache-dir \
    "livekit-agents[google,silero,turn-detector]>=1.3.12" \
    "livekit-plugins-lemonslice>=1.3.12" \
    livekit-api \
    livekit \
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

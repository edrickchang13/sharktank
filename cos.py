"""COS client for Shark Tank session logging."""
import json
import os
import threading
from typing import Optional

from dotenv import load_dotenv
from qcloud_cos import CosConfig, CosS3Client

load_dotenv()

_REQUIRED_VARS = ["TENCENT_SECRET_ID", "TENCENT_SECRET_KEY", "COS_BUCKET"]
_client: Optional[CosS3Client] = None
_bucket: Optional[str] = None
_lock = threading.Lock()


def _get_client() -> tuple[CosS3Client, str]:
    global _client, _bucket
    with _lock:
        if _client is not None and _bucket is not None:
            return _client, _bucket

        missing = [v for v in _REQUIRED_VARS if not os.getenv(v)]
        if missing:
            raise RuntimeError(f"Missing required env vars: {missing}")

        config = CosConfig(
            Region=os.getenv("COS_REGION", "ap-guangzhou"),
            SecretId=os.getenv("TENCENT_SECRET_ID"),
            SecretKey=os.getenv("TENCENT_SECRET_KEY"),
        )
        try:
            _client = CosS3Client(config)
        except Exception:
            raise RuntimeError("COS client init failed; check credentials") from None
        _bucket = os.getenv("COS_BUCKET")
        return _client, _bucket


def upload_session(session_id: str, data: dict) -> str:
    """Upload full session log as JSON. Returns presigned URL (1hr)."""
    client, bucket = _get_client()
    key = f"sessions/{session_id}/session.json"
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return client.get_presigned_download_url(Bucket=bucket, Key=key, Expired=3600)


def upload_audio(session_id: str, turn_idx: int, judge_key: str, audio_bytes: bytes) -> str:
    """Upload one judge audio response. Returns presigned URL."""
    if not audio_bytes:
        raise ValueError("audio_bytes is empty; refusing to upload zero-byte object")
    client, bucket = _get_client()
    key = f"sessions/{session_id}/turn_{turn_idx:03d}_{judge_key}.mp3"
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=audio_bytes,
        ContentType="audio/mpeg",
    )
    return client.get_presigned_download_url(Bucket=bucket, Key=key, Expired=3600)


def list_session_keys(session_id: str) -> list[str]:
    """List all object keys under a session prefix."""
    client, bucket = _get_client()
    response = client.list_objects(Bucket=bucket, Prefix=f"sessions/{session_id}/")
    contents = response.get("Contents", [])
    return [item["Key"] for item in contents]

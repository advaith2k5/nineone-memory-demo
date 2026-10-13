"""Step 0b: make exactly ONE tiny call to each chosen model and report what happened.

Total calls: 3 (two chat models, one embedding model). Nothing is saved.
The key is read from .env and never printed. Rate-limit headers and error
text ARE printed, because they tell us the real free-tier limits.

Run:  python scripts/smoke_test.py
"""
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
CHAT_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
EMBED_MODEL = "gemini-embedding-001"


def load_key() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("No GOOGLE_API_KEY in .env")


def post(model: str, method: str, body: dict, key: str):
    req = urllib.request.Request(
        f"{BASE}/{model}:{method}",
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r), time.time() - t0, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600], time.time() - t0, dict(e.headers)
    except (TimeoutError, urllib.error.URLError) as e:
        # No answer from Google at all (slow model, network, or blocked).
        return 0, f"no answer: {e!r}", time.time() - t0, {}


def main() -> int:
    key = load_key()
    ok = True

    for model in CHAT_MODELS:
        status, data, secs, _ = post(
            model,
            "generateContent",
            {"contents": [{"parts": [{"text": "Reply with exactly one word: pong"}]}]},
            key,
        )
        if status == 200:
            text = data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
            usage = data.get("usageMetadata", {})
            print(f"[OK ] {model:28s} {secs:5.1f}s  reply={text!r}  tokens={usage.get('totalTokenCount')}")
        else:
            ok = False
            print(f"[ERR] {model:28s} HTTP {status}  {secs:5.1f}s\n      {data}")

    # Embedding: ask for 768 numbers, then check the size and the length of the vector.
    status, data, secs, _ = post(
        EMBED_MODEL,
        "embedContent",
        {
            "content": {"parts": [{"text": "RNA1301000057_1 accessibility dropped after tilt change"}]},
            "outputDimensionality": 768,
        },
        key,
    )
    if status == 200:
        vec = data["embedding"]["values"]
        norm = math.sqrt(sum(v * v for v in vec))
        print(f"[OK ] {EMBED_MODEL:28s} {secs:5.1f}s  dims={len(vec)}  length(norm)={norm:.4f}")
        if abs(norm - 1.0) > 0.01:
            print("      Length is not 1.0, so we MUST normalize vectors ourselves (as planned).")
    else:
        ok = False
        print(f"[ERR] {EMBED_MODEL:28s} HTTP {status}  {secs:5.1f}s\n      {data}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

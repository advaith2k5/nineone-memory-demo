"""Step 0: ask Google which models this API key may use.

This makes ONE call to the 'models.list' endpoint. It does not use a model, so
it should not eat into the free chat quota. It only reads and prints; it
changes nothing. The key is read from .env and is never printed.

Run:  python scripts/list_models.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict:
    # Tiny .env reader so we do not need to install anything for this step.
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    env = load_env(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ.get("GOOGLE_API_KEY") or env.get("GOOGLE_API_KEY")
    if not key:
        print("No GOOGLE_API_KEY found in .env")
        return 1

    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
    # The key goes in a header, not the URL, so it cannot leak into logs.
    req = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"Google answered HTTP {e.code}.")
        print(e.read().decode("utf-8", "replace")[:500])
        print("\nIf this says the key is invalid, the key may not be a Gemini API key.")
        return 2
    except Exception as e:  # network down, DNS, etc.
        print("Could not reach Google:", repr(e))
        return 3

    chat, embed = [], []
    for m in data.get("models", []):
        methods = m.get("supportedGenerationMethods", [])
        name = m["name"].removeprefix("models/")
        row = (name, m.get("inputTokenLimit"), m.get("outputTokenLimit"))
        if "generateContent" in methods:
            chat.append(row)
        if "embedContent" in methods:
            embed.append(row)

    print(f"\nCHAT models ({len(chat)}):")
    for n, i, o in sorted(chat):
        print(f"  {n:45s} in={i}  out={o}")
    print(f"\nEMBEDDING models ({len(embed)}):")
    for n, i, o in sorted(embed):
        print(f"  {n:45s} in={i}")
    print("\nNote: this list shows what EXISTS for the key, not your daily free limit.")
    print("Check limits in AI Studio (aistudio.google.com) for the project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

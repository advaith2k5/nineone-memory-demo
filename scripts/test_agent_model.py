"""Step 0c: ONE call to the agent model, checking it can answer AND call a tool.

The agent (RCA) works by calling tools such as search_memory, so a model that
only chats is not good enough. We hand the model one fake tool and ask a
question that needs it. A good answer is a 'functionCall' with the right
argument, not plain text.

Usage:  python scripts/test_agent_model.py [model-name]
Default model: gemini-2.5-flash.   Calls made: 1.   Timeout: 30 seconds.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash"

    key = next(
        (line.split("=", 1)[1].strip()
         for line in (Path(__file__).resolve().parent.parent / ".env").read_text(encoding="utf-8").splitlines()
         if line.startswith("GOOGLE_API_KEY=")),
        None,
    )
    if not key:      # a missing line used to crash with StopIteration, which says nothing useful
        sys.exit("No GOOGLE_API_KEY= line in memory_demo/.env")

    body = {
        "contents": [{"role": "user", "parts": [{"text": "What happened the last time we changed tilt on cell RNA1301000057_1? Use the tool."}]}],
        "tools": [{
            "functionDeclarations": [{
                "name": "search_memory",
                "description": "Search past cases and fixes stored in memory.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "what to look for"},
                        "cell_id": {"type": "STRING", "description": "exact cell id"},
                    },
                    "required": ["query", "cell_id"],
                },
            }]
        }],
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"[ERR] {model}: HTTP {e.code} after {time.time()-t0:.1f}s\n{e.read().decode('utf-8','replace')[:600]}")
        sys.exit(1)
    except (TimeoutError, urllib.error.URLError) as e:
        print(f"[ERR] {model}: no answer in 30s ({e!r})")
        sys.exit(2)

    parts = data["candidates"][0]["content"]["parts"]
    calls = [p["functionCall"] for p in parts if "functionCall" in p]
    print(f"[OK ] {model}: answered in {time.time()-t0:.1f}s, tokens={data.get('usageMetadata',{}).get('totalTokenCount')}")
    if calls:
        print("      tool call:", json.dumps(calls[0]))
        good = calls[0].get("args", {}).get("cell_id") == "RNA1301000057_1"
        print("      cell_id copied exactly:", good)
    else:
        print("      NO tool call. Plain text instead:", [p.get("text") for p in parts])


if __name__ == "__main__":
    main()

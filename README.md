# NineOne memory demo

A small working demo of agent memory for the NineOne platform. One real agent, the RCA (root-cause) agent,
runs on Gemini. The same tests run on two memory libraries, LangMem and Mem0, so you can see how each one
saves, finds, changes and deletes memory, and where each one goes wrong. On top of both sits a "guard" that
enforces the rules from Saurabh's NineOne Memory Architecture v3: one writer per memory, every memory cites
its source, no personal data, an SME approves changes, and old cases can be replayed.

The slides and the presenter guide (what to say on each slide, which file to open, what to run and what the
output means) are in `docs/`.

## What you need

- Windows with **Docker Desktop**, and Docker running
- **Python 3.11**
- A **Gemini API key** from Google AI Studio (the free tier works, slowly)

## Set it up (once)

Run these from the `memory_demo` folder. The commands are for Git Bash. In PowerShell, write
`.venv\Scripts\python.exe` instead of `.venv/Scripts/python.exe`.

1. Start the database (Postgres 16 with pgvector, on port 5433):

   ```
   docker compose up -d
   ```

2. Make a virtual environment and install the pinned packages:

   ```
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and put your key in it. `.env` is in `.gitignore`, so it is never committed.

4. Load the fake network data (cells, KPIs, alarms, config changes, and 90 closed cases):

   ```
   .venv/Scripts/python.exe -m nineone_mem.seed.mock_data
   ```

   This needs `src` on the path. If Python cannot find `nineone_mem`, run `export PYTHONPATH=src` first
   (PowerShell: `$env:PYTHONPATH = "src"`).

5. Check that your key works and which models it can use:

   ```
   .venv/Scripts/python.exe scripts/list_models.py
   .venv/Scripts/python.exe scripts/test_agent_model.py gemini-3.1-flash-lite
   ```

   The second command makes one chat call and checks that the model can call a tool.

## Run the scenarios

Every scenario takes `--backend langmem`, `--backend mem0` or `--backend both`, and prints what happened
step by step.

| Command | What it shows | Chat calls |
|---|---|---|
| `python -m scenarios.s1_memory_types` | What is memory, skill and system prompt, plus one real agent run | 8 |
| `python -m scenarios.s2_retrieval` | Why you must filter by cell before searching by meaning | 0 |
| `python -m scenarios.s3_conflict` | What each library does with a contradicting fact, and what the guard does | 2 |
| `python -m scenarios.s4_garbage_in` | Four kinds of bad memory, with and without the guard (`--live-agent` adds a real run) | 0 |
| `python -m scenarios.s5_lifecycle` | Writing memory during a run vs after, soft delete, and replay | 2 |
| `python -m scenarios.s6_multi_agent` | Who can write and read which memory | 0 |
| `python -m scenarios.e2e_case` | A full case, a failed fix, an SME approval, and a smarter next case | 16 |

Use `.venv/Scripts/python.exe` in place of `python`. Embedding calls are also used, but they are cheap.

## Run the tests

```
.venv/Scripts/python.exe -m pytest tests -q              # everything, 8 to 20 minutes (Gemini speed varies)
.venv/Scripts/python.exe -m pytest tests -m s3 -v        # one scenario only
```

Most tests call Gemini for real, so they use your free quota. The whole suite uses about 30 chat calls.
Every test session reseeds the demo data first (`tests/conftest.py`), so a run that was stopped halfway
cannot break the next one.

## Start again with clean data

```
.venv/Scripts/python.exe scripts/reset_demo_data.py
```

This clears the case record, the guard's queue and the memory history, then reseeds the demo data. It does
not touch the LangMem and Mem0 stores. Every run uses its own tenant, so old memories there cannot affect a
new run. To wipe everything, run `docker compose down -v` and start the setup again.

## What is where

| Folder or file | What it holds |
|---|---|
| `harness/rca/` | The RCA agent's three harness files: `soul.md` (system prompt), `AGENTS.md` (static memory), `skills/rca-categorise/SKILL.md` (the method) |
| `src/nineone_mem/config.py` | Every setting in one place: model names, embedding size, rate limits, the 30-case floor |
| `src/nineone_mem/llm.py` | Gemini chat and embeddings, with rate limits, retries and a call counter |
| `src/nineone_mem/memory/` | The shared memory interface (`base.py`), the LangMem and Mem0 versions, and the NineOne guard (`guard.py`) |
| `src/nineone_mem/agent/` | The RCA agent: its four tools, the answer schema and the deepagents wiring |
| `src/nineone_mem/stubs/` | Rule-only stand-ins for the Intake, Performance, Config, Fault, Coverage and Action Watcher agents |
| `src/nineone_mem/consolidate.py` | The after-the-case job that turns closed cases into memory, counted by SQL |
| `src/nineone_mem/db/schema.sql` | The tables this project owns |
| `scenarios/` | The seven demos above |
| `tests/` | 93 tests |
| `scripts/` | Key checks, a single agent run, a library probe, and the data reset |
| `docs/` | The slide deck, the presenter guide (`presenter_guide.md`), and the deck builder |

## If something goes wrong

- **"failed to connect to the docker API"**: Docker Desktop is not running. Start it and wait until it says it is running.
- **Port 5433 is already in use**: change `5433:5432` in `docker-compose.yml` and the port in `.env`.
- **429 RESOURCE_EXHAUSTED**: you hit a Gemini limit. Chat and embedding calls already wait and retry. If it
  keeps happening, you have used the day's free quota, so try again later.
- **503 "high demand"**: that Gemini model is overloaded. On 13 Oct 2026 the larger Flash models were, so
  everything runs on `gemini-3.1-flash-lite`. To try another model, test it with
  `scripts/test_agent_model.py <model>` and then change `AGENT_MODEL` in `src/nineone_mem/config.py`.
- **"run_id ... already has saved checkpoints"**: every case needs a new run id. Reusing one would continue
  the old conversation.

Mem0's usage reporting (telemetry) is switched off in `config.py`, so nothing leaves the machine except the
calls to Gemini.

## Known limits

This is a demo, not production code. The main limits are: the personal-data and injection checks are simple
pattern lists; the guard checks the shape of an SME review id, not that the review happened; the agent never
opened its skill file in our runs; and there is no digital twin, knowledge graph or topology feed. The full
list is on slide 18 of the deck and in `docs/presenter_guide.md`.

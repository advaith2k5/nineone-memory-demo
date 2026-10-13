"""Builds the RCA agent with deepagents and runs one case.

How the pieces map to the harness template:
  system_prompt  <- harness/rca/soul.md                  (A: who it is)
  memory=[...]   <- harness/rca/AGENTS.md                (B: what is true here, cached, static)
  skills=[...]   <- harness/rca/skills/*/SKILL.md        (C: how to do the task; body loads on demand)
  tools          <- agent/tools.py                       (the 4 guarded tools)
  permissions    <- deny all writes                      (E: read-only except through emit_verdict)
  checkpointer   <- PostgresSaver, thread_id = run_id    (short-term memory, resumable)
  recursion_limit<- step limit                           (E: stop a runaway loop)
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.errors import GraphRecursionError

from .. import config
from ..llm import get_chat_model
from .context import RunContext
from .tools import make_tools, recall

HARNESS = config.ROOT / "harness" / "rca"
STEP_LIMIT = 25


def build_rca_agent(ctx: RunContext, checkpointer=None):
    return create_deep_agent(
        model=get_chat_model(config.AGENT_MODEL),
        tools=make_tools(ctx),
        system_prompt=(HARNESS / "soul.md").read_text(encoding="utf-8"),
        memory=["/AGENTS.md"],
        skills=["/skills/"],
        # "/" means the harness/rca folder. virtual_mode keeps the agent inside it.
        backend=FilesystemBackend(root_dir=HARNESS, virtual_mode=True),
        permissions=[FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        checkpointer=checkpointer,
        name="RAN_A8_rca",
    )


RECALL_QUERY = "earlier incidents, fixes and their results, and expert corrections for this cell"


def facts_turn(ctx: RunContext) -> str:
    """The per-run message. Everything that changes every run goes HERE, never into soul/AGENTS.

    The top-3 memories are searched by our code BEFORE the model starts (HLD slide 1, v3 MI-3),
    so the model does not have to remember to look.
    """
    return (f"Worst cell: {ctx.cell_id} on site {ctx.site_id}. Window: {ctx.window}. KPI: accessibility. "
            "Find the root cause.\n\n"
            "RECALLED MEMORY (already searched for you; call search_memory only if you need something more):\n"
            f"{recall(ctx, RECALL_QUERY)}")


@contextmanager
def open_agent(ctx: RunContext):
    """Yields (agent, config). Keeps the Postgres checkpointer connection open while the agent runs."""
    with PostgresSaver.from_conn_string(config.DATABASE_URL) as saver:
        saver.setup()   # creates the checkpoint tables if missing
        yield build_rca_agent(ctx, saver), {
            "configurable": {"thread_id": ctx.run_id},
            "recursion_limit": STEP_LIMIT,
        }


def _run_id_already_used(run_id: str) -> bool:
    with psycopg.connect(config.DATABASE_URL) as conn:
        try:
            return conn.execute("SELECT 1 FROM checkpoints WHERE thread_id=%s LIMIT 1", (run_id,)).fetchone() is not None
        except psycopg.errors.UndefinedTable:      # first ever run: the checkpoint tables do not exist yet
            return False


def run_case(ctx: RunContext) -> dict:
    """Run one case end to end. Returns the raw messages plus the checked verdict (or None).

    If the agent hits the step limit, we return verdict=None and an "error" text instead of crashing:
    "no answer" is a normal outcome that the caller can show.
    """
    # The run id is the checkpoint thread id. Reusing one would silently CONTINUE the old conversation,
    # and the new case would start with the old case's messages. Refuse instead.
    if _run_id_already_used(ctx.run_id):
        raise ValueError(f"run_id '{ctx.run_id}' already has saved checkpoints. Use a new run id for a new case.")
    try:
        with open_agent(ctx) as (agent, cfg):
            result = agent.invoke({"messages": [{"role": "user", "content": facts_turn(ctx)}]}, config=cfg)
    except GraphRecursionError:
        return {"messages": [], "verdict": ctx.verdict, "skills_loaded": loaded_skills(),
                "error": f"step limit of {STEP_LIMIT} reached before the agent answered"}
    return {"messages": result["messages"], "verdict": ctx.verdict, "skills_loaded": loaded_skills(), "error": None}


def loaded_skills() -> list[str]:
    """Which skills deepagents puts into the prompt (name + description only) at the start of a run.

    deepagents does not return this in the run output, so we run the same loader it uses. A skill can
    be loaded this way and still never opened: opening the body is the model's choice (in our runs,
    gemini-3.1-flash-lite never opened it).
    """
    from deepagents.middleware.skills import SkillsMiddleware

    class _Runtime:   # the loader only needs a runtime object to exist
        store = None
        context = None

    mw = SkillsMiddleware(backend=FilesystemBackend(root_dir=HARNESS, virtual_mode=True), sources=["/skills/"])
    out = mw.before_agent({}, _Runtime(), {}) or {}
    return [s["name"] for s in out.get("skills_metadata", [])]


def trace(messages) -> str:
    """Readable list of what the agent did: each tool call and what came back."""
    lines = []
    for m in messages:
        kind = m.__class__.__name__
        if kind == "AIMessage" and m.tool_calls:
            for c in m.tool_calls:
                lines.append(f"  AGENT -> {c['name']}({_short(c['args'])})")
        elif kind == "ToolMessage":
            lines.append(f"  TOOL  <- {_short(m.text, 160)}")
    return "\n".join(lines)


def _short(x, n: int = 120) -> str:
    s = str(x).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "..."

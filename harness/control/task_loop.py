"""The agentic task loop — PK2 §T2-E1.

KEYSTONE gave the organism tools it can call *within a turn* (``run_with_tools``) and a
memory-maintenance ROUND (``agency_round``). This module adds the missing middle: a bounded,
resumable, receipted **multi-step task** — give it a goal, it plans/acts/observes across
several tool rounds under a step + wall-clock budget, persists its state to disk after every
step (so a crash or restart resumes), and stops with an honest verdict.

Design notes
------------
* Reuses ``run_with_tools`` as the per-step actuator (all the coding/memory/system tools, the
  malformed-recovery + no-progress guards land for free).
* State is a plain JSON doc (``TaskState``) written under ``SP_TASK_ROOT`` (default
  ``_task_state/`` beside the harness). It is the mid-tier "work queue" the KAIROS scheduler
  drains — nothing engine-side needed.
* Every step appends a receipt line so the whole run is auditable (the project rule: no action
  without a record).
* Default-off in the sense that it does nothing until a goal is posted; ``run_task`` is a pure
  additive entry point (no existing path changes).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

from harness.inference.client import SPDaemonClient, get_client
from harness.inference.inference_config import InferenceConfig

logger = logging.getLogger(__name__)


def _task_root() -> str:
    root = os.environ.get("SP_TASK_ROOT") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "_task_state")
    os.makedirs(root, exist_ok=True)
    return root


@dataclass
class TaskStep:
    n: int
    action: str          # the model's text for this step (may contain tool calls)
    observation: str      # tool outputs / result summary
    ts: float


@dataclass
class TaskState:
    task_id: str
    goal: str
    status: str = "pending"          # pending | running | done | failed | exhausted
    steps: List[TaskStep] = field(default_factory=list)
    result: str = ""
    created: float = 0.0
    updated: float = 0.0

    def path(self) -> str:
        return os.path.join(_task_root(), f"{self.task_id}.json")

    def save(self) -> None:
        self.updated = time.time()
        d = asdict(self)
        tmp = self.path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, self.path())   # atomic — a crash never leaves half a state file

    @classmethod
    def load(cls, task_id: str) -> Optional["TaskState"]:
        p = os.path.join(_task_root(), f"{task_id}.json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        d["steps"] = [TaskStep(**s) for s in d.get("steps", [])]
        return cls(**d)


TASK_SYSTEM = (
    "You are Shannon-Prime working a multi-step task on the operator's machine. Break the goal "
    "into small steps. Each step: think briefly, then EITHER call ONE tool (to read, edit, run, "
    "or test) OR — when the goal is fully achieved — reply with a line beginning 'DONE:' and a "
    "one-sentence summary. If you get stuck, reply with a line beginning 'BLOCKED:' and why. "
    "Prefer edit_file over rewriting; run_tests after code changes; never claim success you did "
    "not verify."
)


def _plan_prompt(state: TaskState) -> List[dict]:
    """Build the conversation for the next step from the goal + the step history."""
    lines = [f"GOAL: {state.goal}", ""]
    if state.steps:
        lines.append("Progress so far:")
        for s in state.steps[-6:]:          # last few steps keep the prompt bounded
            lines.append(f"[step {s.n}] {s.action.strip()[:300]}")
            lines.append(f"   -> {s.observation.strip()[:300]}")
        lines.append("")
    lines.append("Do the NEXT step now (one tool call), or reply 'DONE:'/'BLOCKED:'.")
    return [{"role": "user", "content": "\n".join(lines)}]


def run_task(
    goal: str,
    *,
    task_id: Optional[str] = None,
    max_steps: int = 12,
    budget_s: float = 600.0,
    tools=None,
    verify: Optional[Callable[[], bool]] = None,
    client: Optional[SPDaemonClient] = None,
    config: Optional[InferenceConfig] = None,
    on_step: Optional[Callable[[TaskState], None]] = None,
    on_tool: Optional[Callable[[str, dict, str], None]] = None,
) -> TaskState:
    """Run (or RESUME) a bounded agentic task. Returns the final TaskState.

    Resumable: pass an existing ``task_id`` to continue a persisted run from its last saved step.
    Bounded: stops at ``max_steps`` OR ``budget_s`` wall-clock, whichever first, with an honest
    status. Every step is persisted + receipted before the next begins.

    ``verify``: an OPTIONAL zero-arg predicate that returns True iff the goal is objectively met
    (e.g. `lambda: run pytest and check exit 0`). When given, a model 'DONE:' claim is only
    ACCEPTED if verify() passes — otherwise the false claim is fed back and the loop continues.
    This closes the confabulation gap (G-PK2-TASKLOOP-E2E, 2026-07-07): a 12B will happily say
    "I fixed it" without its edit ever landing; the harness must check, not trust.
    """
    from harness.mcp.tools import ToolSpec, run_with_tools, _parse_tool_calls

    if tools is None:
        # FOCUSED coding set (<=6): the 12B picks reliably from a few tools; the full 14 make it
        # explore and stall (the same lesson agent.default_tools() banks). read/write/edit/search/
        # run_tests + run_command is the coding-task minimum.
        from harness.skills.builtin.coding import (read_file, write_file, edit_file,
                                                   search, run_tests, run_command)
        tools = [ToolSpec.from_callable(fn) for fn in
                 (read_file, write_file, edit_file, search, run_tests, run_command)]

    state = (TaskState.load(task_id) if task_id else None) or TaskState(
        task_id=task_id or uuid.uuid4().hex[:12], goal=goal, created=time.time())
    if not state.goal:
        state.goal = goal
    state.status = "running"
    state.save()

    cfg = config or InferenceConfig(temperature=0.3, repetition_penalty=1.3,
                                    eot_bias=4.0, max_tokens=256, auto_recall=False)
    client = client or get_client()
    t0 = time.time()

    while len(state.steps) < max_steps and (time.time() - t0) < budget_s:
        n = len(state.steps) + 1
        # One actuation step: the model may take several tool rounds internally to complete it.
        captured: List[str] = []

        def _cap(name, args, result):
            captured.append(f"{name} -> {result}")
            if on_tool:
                on_tool(name, args, result)

        text = run_with_tools(
            _plan_prompt(state), tools, client=client, config=cfg,
            on_tool=_cap, max_rounds=4, system_prefix=TASK_SYSTEM)
        obs = "\n".join(captured) if captured else "(no tool call this step)"
        step = TaskStep(n=n, action=text, observation=obs, ts=time.time())
        state.steps.append(step)

        low = text.strip()
        if low.startswith("DONE:") or "\nDONE:" in low:
            claim = low.split("DONE:", 1)[1].strip()[:500]
            # VERIFY-BEFORE-ACCEPT: never trust a DONE claim on faith (the confabulation gap).
            if verify is not None:
                ok = False
                try:
                    ok = bool(verify())
                except Exception as exc:
                    logger.warning("[task] verify() raised: %s", exc)
                if not ok:
                    step.observation += "\n[verify] Your 'DONE' claim did NOT pass verification — " \
                        "the goal is not actually met yet. Look again (did your edit really land?) " \
                        "and keep working."
                    state.save()
                    if on_step:
                        on_step(state)
                    continue      # reject the false DONE, keep going
            state.status = "done"
            state.result = claim
            state.save()
            if on_step:
                on_step(state)
            break
        if low.startswith("BLOCKED:") or "\nBLOCKED:" in low:
            state.status = "failed"
            state.result = low.split("BLOCKED:", 1)[1].strip()[:500]
            state.save()
            if on_step:
                on_step(state)
            break
        state.save()                     # persist AFTER every step -> resumable
        if on_step:
            on_step(state)
    else:
        state.status = "exhausted" if len(state.steps) >= max_steps else "exhausted"
        if not state.result:
            state.result = f"(stopped after {len(state.steps)} steps / {time.time()-t0:.0f}s without a DONE)"
        state.save()

    logger.info("[task] %s -> %s (%d steps)", state.task_id, state.status, len(state.steps))
    return state


# ──── The work queue (PK2 §T2-E4): tasks the KAIROS tick advances ────────────
def list_tasks(status: Optional[str] = None) -> List[TaskState]:
    """All persisted tasks, optionally filtered by status (the operator's work queue)."""
    out: List[TaskState] = []
    root = _task_root()
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".json"):
            continue
        st = TaskState.load(fn[:-5])
        if st and (status is None or st.status == status):
            out.append(st)
    return out


def post_task(goal: str) -> str:
    """Enqueue a task (status=pending) without running it; returns its id. The KAIROS
    scheduler picks pending tasks up on an idle tick (see agency.run_agency_scheduler)."""
    st = TaskState(task_id=uuid.uuid4().hex[:12], goal=goal, status="pending", created=time.time())
    st.save()
    logger.info("[task] posted %s: %s", st.task_id, goal[:80])
    return st.task_id


def advance_pending_task(**kw) -> Optional[TaskState]:
    """Run the OLDEST pending task to completion (one per call). Returns its final state, or
    None if the queue is empty. Called by the agency tick so the organism drains its own queue."""
    pend = [t for t in list_tasks("pending")]
    if not pend:
        return None
    pend.sort(key=lambda t: t.created)
    return run_task(pend[0].goal, task_id=pend[0].task_id, **kw)

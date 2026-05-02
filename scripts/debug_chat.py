"""Debug harness for the i2i chat / orchestrator flow.

Drives a real session through the chat-with-tools loop or the
prompt-generation orchestrator **without going through the HTTP layer
or the frontend**. Every LLM round-trip lands in
``data/llm_log/<YYYY-MM-DD>.jsonl`` the same way the live endpoints do
(see ``backend/app/services/llm_log.py``), so the debug session and the
live app share the same log file.

The harness never writes to the chat history or prompts tables — it
runs read-only against ``data/app.db`` (orchestrator does write a row to
``prompts`` because that's how it persists results; pass
``--no-persist`` to skip that).

Usage::

    python scripts/debug_chat.py list-sessions [--limit 20]
    python scripts/debug_chat.py inspect <session_id>
    python scripts/debug_chat.py chat <session_id> --message "the user message"
    python scripts/debug_chat.py orchestrator <session_id> --brief "agreed direction"
    python scripts/debug_chat.py tail-log [--follow]

Run from the repo root. Backend imports are bootstrapped automatically.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

# --- Bootstrapping: make `app.*` importable from this script -----------------
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Imports must come AFTER the path tweak.
# ruff: noqa: E402
from app.api import chat as chat_api
from app.config import resolve_data_root
from app.services import (
    chat_summarizer,
    llm_log,
    lmstudio_client,
    prompt_orchestrator,
)
from app.storage import db, session_repo, settings_repo, source_image_repo

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _open_conn() -> sqlite3.Connection:
    return db.connect()


def _resolve_endpoint_and_model(
    conn: sqlite3.Connection, session_row: dict,
) -> tuple[dict, str, dict]:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise SystemExit("LMStudio base_url is not configured (Settings → LMStudio).")
    model_name = session_row.get("prompt_model_name")
    if not model_name:
        raise SystemExit("session has no prompt_model_name selected.")
    model_row = settings_repo.get_lm_model(conn, model_name)
    if model_row is None or not model_row["enabled"]:
        raise SystemExit(f"prompt model {model_name!r} is not enabled in lm_models.")
    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }
    return endpoint, model_name, model_row


def _hr(label: str = "") -> None:
    bar = "─" * 78
    print(f"\n{bar}", flush=True)
    if label:
        print(f"  {label}", flush=True)
        print(bar, flush=True)


# ---------------------------------------------------------------------------
# subcommand: list-sessions
# ---------------------------------------------------------------------------

def cmd_list_sessions(args: argparse.Namespace) -> int:
    conn = _open_conn()
    rows = conn.execute(
        "SELECT s.id, s.name, s.session_type, s.prompt_model_name, "
        "s.updated_at, p.name AS project_name "
        "FROM sessions s JOIN projects p ON p.id = s.project_id "
        "ORDER BY s.updated_at DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    print(f"{'session_id':<14} {'type':<5} {'model':<32} {'project':<24} name")
    print("-" * 100)
    for r in rows:
        sid = r["id"]
        stype = r["session_type"] or "?"
        model = (r["prompt_model_name"] or "—")[:32]
        proj = (r["project_name"] or "—")[:24]
        name = r["name"] or "—"
        print(f"{sid:<14} {stype:<5} {model:<32} {proj:<24} {name}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: inspect
# ---------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> int:
    conn = _open_conn()
    session = session_repo.get_session_with_pinned(conn, args.session_id)
    if session is None:
        print(f"session not found: {args.session_id}")
        return 1
    print(json.dumps(
        {k: v for k, v in session.items() if k not in ("pinned_loras",)},
        indent=2, ensure_ascii=False, default=str,
    ))
    print("\nPinned LoRAs:")
    for p in session.get("pinned_loras") or []:
        print(f"  - {p['lora_name']} (override={p.get('weight_override')})")
    sources = source_image_repo.list_for_session(conn, args.session_id)
    print(f"\nSource images ({len(sources)}):")
    for s in sources:
        analyzed = "yes" if (s.get("analysis") or "").strip() else "NO"
        flag = "★" if s["is_main"] else " "
        print(
            f"  {flag} Image_{s['image_number']:<3} analyzed={analyzed} "
            f"file={s['original_filename']}"
        )
    msgs = session_repo.list_messages(conn, session_id=args.session_id)
    print(f"\nLast {min(args.tail, len(msgs))} messages of {len(msgs)} total:")
    for m in msgs[-args.tail:]:
        body = (m["content"] or "").replace("\n", " ")[:120]
        print(f"  [{m['role']:>9}] {body}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: chat
# ---------------------------------------------------------------------------

def cmd_chat(args: argparse.Namespace) -> int:
    conn = _open_conn()
    session_row = session_repo.get_session(conn, args.session_id)
    if session_row is None:
        print(f"session not found: {args.session_id}")
        return 1
    endpoint, model, _ = _resolve_endpoint_and_model(conn, session_row)
    payload_messages = chat_api._build_payload_messages(
        conn, session_row, args.message,
    )

    _hr(f"chat session={args.session_id}  model={model}")
    print(f"  user message: {args.message!r}")
    print(f"  payload: {len(payload_messages)} messages, "
          f"first system content len = {len(payload_messages[0]['content'])}")

    with llm_log.run_context() as rid:
        print(f"  run_id: {rid}")
        _hr("LLM stream")
        accumulated: list[str] = []
        try:
            for chunk in lmstudio_client.chat_stream(
                endpoint=endpoint, model=model, messages=payload_messages,
            ):
                accumulated.append(chunk)
                sys.stdout.write(chunk)
                sys.stdout.flush()
        except lmstudio_client.LmError as exc:
            print(f"\n[LmError {exc.kind}] {exc.detail}", flush=True)
            return 2

    print()
    _hr("done")
    print(f"  total assistant text: {len(''.join(accumulated))} chars")
    print(f"  log: {llm_log._log_path()}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: summarize
# ---------------------------------------------------------------------------

def cmd_summarize(args: argparse.Namespace) -> int:
    conn = _open_conn()
    session_row = session_repo.get_session(conn, args.session_id)
    if session_row is None:
        print(f"session not found: {args.session_id}")
        return 1
    endpoint, model, _ = _resolve_endpoint_and_model(conn, session_row)
    _hr(f"summarize session={args.session_id}  model={model}")
    with llm_log.run_context() as rid:
        print(f"  run_id: {rid}")
        try:
            brief = chat_summarizer.summarize_session_chat(
                conn,
                session_id=args.session_id,
                endpoint=endpoint,
                prompt_model=model,
            )
        except lmstudio_client.LmError as exc:
            print(f"\n[LmError {exc.kind}] {exc.detail}")
            return 2
    _hr("brief")
    print(brief)
    print(f"\n  log: {llm_log._log_path()}")
    return 0


# ---------------------------------------------------------------------------
# subcommand: orchestrator
# ---------------------------------------------------------------------------

def cmd_orchestrator(args: argparse.Namespace) -> int:
    conn = _open_conn()
    session_row = session_repo.get_session(conn, args.session_id)
    if session_row is None:
        print(f"session not found: {args.session_id}")
        return 1
    endpoint, model, _ = _resolve_endpoint_and_model(conn, session_row)

    _hr(f"orchestrator session={args.session_id}  model={model}")
    print(f"  brief: {args.brief!r}")
    if args.no_persist:
        print("  --no-persist: result will NOT be written to prompts table")

    if args.no_persist:
        # Monkey-patch append_prompt to a no-op for this run.
        original = session_repo.append_prompt
        session_repo.append_prompt = lambda *a, **kw: {  # type: ignore
            "id": -1, "created_at": 0,
        }

    try:
        with llm_log.run_context() as rid:
            print(f"  run_id: {rid}")
            try:
                out = prompt_orchestrator.generate(
                    conn,
                    session_id=args.session_id,
                    endpoint=endpoint,
                    prompt_model=model,
                    brief=args.brief,
                )
            except prompt_orchestrator.PreconditionError as exc:
                print(f"\n[PreconditionError] {exc}")
                return 2
            except lmstudio_client.LmError as exc:
                print(f"\n[LmError {exc.kind}] {exc.detail}")
                return 2

        _hr("intents")
        for i in out["intents"]:
            print(f"  - kind={i['kind']!r}  query={i['query']!r}")
        _hr("retrieved")
        for entry in out["retrieved"]:
            kind = entry.get("kind")
            query = entry.get("query")
            cands = entry.get("candidates") or []
            print(f"  • kind={kind!r} query={query!r} -> {len(cands)} candidates")
            for c in cands[:5]:
                print(f"      - {c.get('name')} (score={c.get('score'):.3f})")
        _hr("composition")
        prompt = out["prompt"]
        print(f"  positive: {prompt['positive']}")
        print(f"  negative: {prompt.get('negative')}")
        print(f"  loras   : {json.dumps(prompt.get('loras') or [], ensure_ascii=False)}")
        print(f"\n  log: {llm_log._log_path()}")
        return 0
    finally:
        if args.no_persist:
            session_repo.append_prompt = original  # type: ignore


# ---------------------------------------------------------------------------
# subcommand: tail-log
# ---------------------------------------------------------------------------

def cmd_tail_log(args: argparse.Namespace) -> int:
    log_dir = resolve_data_root() / "llm_log"
    if not log_dir.exists():
        print(f"no log dir at {log_dir}")
        return 0
    files = sorted(log_dir.glob("*.jsonl"))
    if not files:
        print(f"no log files in {log_dir}")
        return 0
    target = files[-1]
    print(f"tailing {target}")
    with target.open("r", encoding="utf-8") as f:
        if not args.follow:
            for line in f:
                _print_log_line(line, verbose=args.verbose)
            return 0
        f.seek(0, 2)  # end
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                _print_log_line(line, verbose=args.verbose)
        except KeyboardInterrupt:
            return 0


def _print_log_line(line: str, *, verbose: bool) -> None:
    line = line.rstrip()
    if not line:
        return
    try:
        rec = json.loads(line)
    except ValueError:
        print(line)
        return
    head = (
        f"{rec.get('ts')}  run={rec.get('run_id')}  "
        f"{rec.get('kind'):<24} model={rec.get('model')}  "
        f"{rec.get('duration_ms')}ms"
    )
    if rec.get("error"):
        head += f"  ERROR={rec['error']}"
    print(head)
    if verbose:
        print(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    else:
        resp = rec.get("response") or {}
        text = resp.get("text") or resp.get("content")
        if text:
            preview = text if len(text) <= 240 else text[:240] + "…"
            print(f"    response.text: {preview!r}")
        tc = resp.get("tool_call")
        if tc:
            print(f"    tool_call: {tc.get('name')}  args={tc.get('arguments')}")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="debug_chat")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-sessions", help="list recent sessions")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list_sessions)

    p_inspect = sub.add_parser("inspect", help="show session config + last messages")
    p_inspect.add_argument("session_id")
    p_inspect.add_argument("--tail", type=int, default=10, help="tail N messages")
    p_inspect.set_defaults(func=cmd_inspect)

    p_chat = sub.add_parser("chat", help="drive a chat turn (no DB persistence)")
    p_chat.add_argument("session_id")
    p_chat.add_argument("--message", required=True, help="the user message")
    p_chat.set_defaults(func=cmd_chat)

    p_sum = sub.add_parser("summarize", help="run chat summarization for a session")
    p_sum.add_argument("session_id")
    p_sum.set_defaults(func=cmd_summarize)

    p_orch = sub.add_parser("orchestrator", help="run the prompt orchestrator with a brief")
    p_orch.add_argument("session_id")
    p_orch.add_argument("--brief", required=True, help="self-contained direction summary")
    p_orch.add_argument(
        "--no-persist", action="store_true",
        help="skip writing the result to the prompts table",
    )
    p_orch.set_defaults(func=cmd_orchestrator)

    p_tail = sub.add_parser("tail-log", help="print or follow today's LLM log")
    p_tail.add_argument("--follow", "-f", action="store_true")
    p_tail.add_argument("--verbose", "-v", action="store_true",
                        help="print full JSON record per line")
    p_tail.set_defaults(func=cmd_tail_log)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

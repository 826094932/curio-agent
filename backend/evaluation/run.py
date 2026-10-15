"""Local regression evaluation for product-decision-agent (Python 3.11)."""
import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def check(case, turn, answer, state, products, calls, tool_logs=None):
    expected = turn.get("expect", {})
    checks = {"nonempty_answer": bool(answer.strip())}
    allowed_errors = case.get("expected_tool_errors", [])
    checks["no_unexpected_tool_errors"] = all(t["status"] == "succeeded" or t["result"].get("error") in allowed_errors for t in tool_logs or [])
    checks["no_unauthorized_preference_write"] = not any(t["name"] == "save_user_preference" and t["status"] == "succeeded" for t in tool_logs or [])
    names = {c["name"] for c in calls}
    for name in expected.get("tools", []):
        checks["tool:" + name] = name in names
    for name in expected.get("forbidden_tools", []):
        checks["no_tool:" + name] = name not in names
    for key, value in expected.get("state", {}).items():
        checks["state:" + key] = state.get(key) == value
    for key, values in expected.get("state_contains", {}).items():
        checks["state_contains:" + key] = all(v in state.get(key, []) for v in values)
    if expected.get("constraint_conflict"):
        checks["constraint_conflict"] = bool(state.get("constraint_conflict"))
    if products:
        from app.products.service import eligible
        checks["recommendations_match_constraints"] = all(eligible(p, state) for p in products)
    return checks


def summarize(rows):
    durations = [r["latency_s"] for r in rows]
    first = [r["first_visible_token_s"] for r in rows if r["first_visible_token_s"] is not None]
    tools = [t for r in rows for t in r["tool_logs"]]
    unexpected = [t for r in rows for t in r["tool_logs"] if t["status"] != "succeeded" and t["result"].get("error") not in r.get("expected_tool_errors", [])]
    measured = [r for r in rows if r["input_tokens"] is not None]
    args = [c for r in rows for c in r["tool_calls"] if c["schema_valid"] is not None]
    return {
        "turns": len(rows), "execution_success_rate": sum(r["status"] == "succeeded" for r in rows) / len(rows),
        "rule_pass_rate": sum(r["rule_pass"] for r in rows) / len(rows),
        "latency_p50_s": statistics.median(durations), "latency_p95_s": percentile(durations, .95),
        "first_visible_token_p50_s": statistics.median(first) if first else None,
        "tool_execution_success_rate": sum(t["status"] == "succeeded" for t in tools) / len(tools) if tools else None,
        "unexpected_tool_error_rate": len(unexpected) / len(tools) if tools else None,
        "tool_schema_valid_rate": sum(c["schema_valid"] for c in args) / len(args) if args else None,
        "usage_coverage": len(measured) / len(rows),
        "input_tokens": sum(r["input_tokens"] for r in measured) if measured else None,
        "output_tokens": sum(r["output_tokens"] for r in measured) if measured else None,
        "model_calls": sum(r["model_calls"] for r in rows),
        "estimated_cost": sum(r["estimated_cost"] for r in rows) if all(r["estimated_cost"] is not None for r in rows) else None,
        "human_quality_score": None,
    }


async def evaluate(args, cases, out):
    # Disable hosted telemetry; model inference still uses the project's DeepSeek API.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    sys.path.insert(0, str(Path(args.project).resolve() / "backend"))
    from importlib.metadata import version
    from langchain_core.callbacks import BaseCallbackHandler
    from langsmith import tracing_context
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.config import settings
    from app.db.mysql import database
    from app.db.models import Base, Category, User, ChatSession, SessionContext, AgentRun, ToolLog, Product, Price, Review, uid
    from app.chat import service, memory
    from app.chat.schemas import ChatInput
    from app.agent.prompts import SYSTEM_PROMPT

    if database.engine is None:
        raise RuntimeError("MYSQL_DSN 未配置；请先完成项目原有数据库初始化。")

    class Capture(BaseCallbackHandler):
        def __init__(self):
            self.calls, self.usages, self.model_calls = [], {}, 0
            self.schemas = {}

        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.model_calls += 1

        def on_llm_end(self, response, *, run_id, **kwargs):
            # Record each model invocation once, including extraction and summary.
            for generation in response.generations:
                for item in generation:
                    message = getattr(item, "message", None)
                    usage = getattr(message, "usage_metadata", None)
                    if usage:
                        self.usages[str(run_id)] = usage
                    for call in getattr(message, "tool_calls", []) or []:
                        if call["name"] not in self.schemas:
                            continue  # Requirement extraction is not a business tool.
                        try:
                            self.schemas[call["name"]].model_validate(call["args"])
                            valid = True
                        except Exception:
                            valid = False
                        self.calls.append({"name": call["name"], "args": call["args"], "schema_valid": valid})

    original_model, original_agent = memory.create_model, service.build_agent
    rows = []
    source_engine, source_sessions = database.engine, database.sessions
    async with database.session() as db:
        snapshot = {}
        for entity in (Category, Product, Price, Review):
            key = entity.code if entity is Category else entity.id
            values = (await db.scalars(select(entity).order_by(key))).all()
            snapshot[entity.__name__] = [{column.name: getattr(v, column.name) for column in entity.__table__.columns} for v in values]
    # Isolate chat writes from FastAPI's startup cleanup and normal user sessions.
    database.engine = create_async_engine("sqlite+aiosqlite:///" + (out / "evaluation.sqlite3").resolve().as_posix())
    database.sessions = async_sessionmaker(database.engine, expire_on_commit=False)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as db:
        for entity in (Category, Product, Price, Review):
            db.add_all([entity(**values) for values in snapshot[entity.__name__]])
        await db.commit()
        user = User(email="eval-" + uid().lower() + "@example.invalid", nickname="本地评测专用用户", password_hash="evaluation-login-disabled", status="disabled")
        db.add(user)
        await db.commit()
        user_id = user.id
    manifest = {
        "version": args.version, "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": digest(cases), "facts_sha256": digest(snapshot), "prompt_sha256": digest(SYSTEM_PROMPT),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model": settings.deepseek_model, "embedding_model": settings.embedding_model,
        "price_stale_hours": settings.price_stale_hours, "request_timeout": settings.request_timeout,
        "max_agent_steps": settings.max_agent_steps, "repeat": args.repeat, "evaluation_user_id": user_id,
        "packages": {p: version(p) for p in ("langchain", "langchain-core", "langchain-deepseek", "langgraph")},
        "pricing_per_million": {"input": args.input_price, "output": args.output_price},
        "scope": "actual chat service; isolated SQLite copy of MySQL facts, existing Chroma index; no frontend; no hosted LangSmith",
    }
    dump(out / "manifest.json", manifest)
    try:
        with tracing_context(enabled=False):
            for case in cases:
                for repeat in range(args.repeat):
                    async with database.session() as db:
                        session = ChatSession(user_id=user_id, title="[EVAL] " + case["id"])
                        db.add(session)
                        await db.flush()
                        db.add(SessionContext(session_id=session.id))
                        await db.commit()
                        session_id = session.id
                    for number, turn in enumerate(case["turns"], 1):
                        capture = Capture()
                        def captured_model():
                            model = original_model()
                            model.callbacks = [capture]
                            return model
                        def captured_agent(tools):
                            capture.schemas = {tool.name: tool.args_schema for tool in tools}
                            return original_agent(tools).with_config(callbacks=[capture])
                        memory.create_model, service.build_agent = captured_model, captured_agent
                        start, first_token, result, error, run = perf_counter(), None, {}, None, None
                        async def emit(event, data):
                            nonlocal first_token
                            if event == "token" and data.get("text") and first_token is None:
                                first_token = perf_counter() - start
                        try:
                            data = ChatInput(session_id=session_id, request_id="eval-" + uid(), message=turn["message"], save_preference=False)
                            run, _ = await service.prepare(user_id, data)
                            result = await service.execute(run, data, emit)
                        except Exception as exc:
                            # Log type/code only: provider exception strings may contain credentials.
                            error = {"type": type(exc).__name__, "code": getattr(exc, "code", None)}
                        latency = perf_counter() - start
                        async with database.session() as db:
                            state = (await db.get(SessionContext, session_id)).state
                            logs = (await db.scalars(select(ToolLog).where(ToolLog.run_id == run.id))).all() if run else []
                        tool_logs = [{"name": t.tool_name, "status": t.status, "latency_ms": t.latency_ms, "result": t.result_summary} for t in logs]
                        checks = check(case, turn, result.get("answer", ""), state, result.get("products", []), capture.calls, tool_logs)
                        known = bool(capture.usages) and len(capture.usages) == capture.model_calls
                        input_tokens = sum(u["input_tokens"] for u in capture.usages.values()) if known else None
                        output_tokens = sum(u["output_tokens"] for u in capture.usages.values()) if known else None
                        # Full input rate used; no claimed cache discount. Units/currency are supplied by the operator.
                        cost = (input_tokens * args.input_price + output_tokens * args.output_price) / 1e6 if known and args.input_price is not None and args.output_price is not None else None
                        row = {"case_id": case["id"], "repeat": repeat + 1, "turn": number, "message": turn["message"],
                               "status": "failed" if error else "succeeded", "rule_pass": not error and all(checks.values()),
                               "checks": checks, "latency_s": round(latency, 3), "first_visible_token_s": first_token,
                               "model_calls": capture.model_calls, "input_tokens": input_tokens, "output_tokens": output_tokens,
                               "cache_read_tokens": sum(u.get("input_token_details", {}).get("cache_read", 0) for u in capture.usages.values()) if known else None,
                               "estimated_cost": cost, "error": error, "tool_calls": capture.calls,
                               "tool_logs": tool_logs, "expected_tool_errors": case.get("expected_tool_errors", []),
                               "state": state, "result": result, "human_quality_score": None, "rubric": case["rubric"]}
                        rows.append(row)
                        with (out / "runs.jsonl").open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        print(f"{case['id']} #{repeat+1} turn {number}: {row['status']}, rules={row['rule_pass']}, {latency:.2f}s", flush=True)
                        if error:
                            break  # Dependent follow-ups cannot be evaluated after failure.
    finally:
        memory.create_model, service.build_agent = original_model, original_agent
        await database.engine.dispose()
        database.engine, database.sessions = source_engine, source_sessions
        await source_engine.dispose()
    summary = summarize(rows)
    dump(out / "summary.json", summary)
    columns = ["case_id", "repeat", "turn", "status", "rule_pass", "latency_s", "first_visible_token_s", "model_calls", "input_tokens", "output_tokens", "estimated_cost", "human_quality_score", "rubric"]
    with (out / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    if args.baseline:
        previous = Path(args.baseline)
        before = json.loads((previous / "summary.json").read_text(encoding="utf-8"))
        baseline_manifest = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
        same = {k: manifest[k] == baseline_manifest.get(k) for k in ("dataset_sha256", "evaluator_sha256", "facts_sha256", "model", "embedding_model", "price_stale_hours", "repeat")}
        dump(out / "comparison.json", {"same_conditions": same, "metrics": {k: {"before": before.get(k), "after": value, "delta": value-before[k] if isinstance(value, (float, int)) and isinstance(before.get(k), (float, int)) else None} for k, value in summary.items()}})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--version", default="baseline")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, help="结果根目录；默认项目根目录下的 log")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--input-price", type=float)
    parser.add_argument("--output-price", type=float)
    parser.add_argument("--dry-run", action="store_true", help="Check dataset; do not access DB or API")
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.repeat < 1 or (args.limit is not None and args.limit < 1):
        parser.error("repeat 和 limit 必须为正整数")
    if len({c["id"] for c in cases}) != len(cases) or not cases:
        parser.error("案例 ID 必须唯一，数据集不能为空")
    for case in cases:
        if not case.get("turns") or not case.get("rubric") or any(not t.get("message") for t in case["turns"]):
            parser.error("每个案例必须包含 turns/message 和人工评分 rubric")
    if args.limit:
        cases = cases[:args.limit]
    if args.dry_run:
        print(f"数据集有效：{len(cases)} 个案例，{sum(len(c['turns']) for c in cases)*args.repeat} 轮；未调用数据库或模型。")
        return
    root = args.output if args.output is not None else Path(args.project) / 'log'
    out = root / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-agent-" + digest(args.version)[:8])
    out.mkdir(parents=True, exist_ok=False)
    try:
        asyncio.run(evaluate(args, cases, out))
    except Exception as exc:
        dump(out / "fatal.json", {"type": type(exc).__name__, "code": getattr(exc, "code", None)})
        print(f"评测中止：{type(exc).__name__}；检查数据库、模型配置。已保存的结果：{out}", file=sys.stderr)
        return 1
    print(f"结果目录：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

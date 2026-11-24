"""Runs tests.json against a deployed (or local) DealDesk API and prints a markdown benchmark table.

Usage:
    python scripts/run_benchmark.py --base http://localhost:8000
    python scripts/run_benchmark.py --base https://your-space.hf.space --runs 3
    python scripts/run_benchmark.py --only 3,11,33          # a few tests
    python scripts/run_benchmark.py --category safety       # one rubric category

Uses only the standard library. Each run uses fresh user ids, so tests never share memory.

Placeholders available in user_id / thread_id / message:
    {run}            unique id for this run
    {slot} {slot2}   a random future visit slot inside business hours, e.g. "on 2026-12-14 at 3 PM"
    {date}           the date part of {slot} (YYYY-MM-DD)
    {<name>}         any value captured from an earlier step with "capture": {"<name>": "<regex with one group>"}

Check types (per step via "checks", and for the last step via the test's "checks"):
    tool_called          str or list: tool(s) that must appear in tool_calls
    tool_not_called      list: tools that must NOT appear
    no_tools             true: no tool may be called
    tool_args            {tool: {arg: expected}} numbers exact, [lo, hi] a numeric range, strings case-insensitive substring
    tool_status          {tool: status} e.g. {"book_visit": "executed"}
    reply_contains_any / reply_contains_all / reply_not_contains   (case-insensitive)
    reply_regex / reply_not_regex                                  (case-insensitive)
    reply_ids_subset_of  list: every listing ID (P-123 / C-123) in the reply must be in this list (catches
                         hallucinated or out-of-budget listings)
    zero_tokens          true: the turn must not call the LLM (guard / approval paths)
    max_tokens_in        int: input-token budget for the turn (cost)
    max_latency_s        float: latency budget for the turn
Every turn is also checked for a non-empty reply, the response schema, and no "temporary problem" error.
"""
import argparse
import sys
import json
import random
import re
import statistics
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# claude-haiku-5-5 list price in USD per token (input / output). Update if your pricing differs.
PRICE_IN, PRICE_OUT = 0.10 / 1e6, 0.50 / 1e6
RUBRIC = {"task_success": 25, "tool_use": 10, "short_term_memory": 10, "long_term_memory": 10,
          "user_isolation": 5, "reliability": 15, "cost": 10, "safety": 5}
ID_RE = re.compile(r"\b([PC]-\d{2,5})\b", re.I)


def post(base: str, payload: dict) -> tuple[dict, float]:
    req = urllib.request.Request(base.rstrip("/") + "/chat", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data, time.time() - t


def random_slot(rng: random.Random) -> tuple[str, str]:
    day = datetime.now() + timedelta(days=rng.randint(3, 55))
    hour = rng.choice([11, 12, 13, 14, 15, 16, 17])
    label = f"{hour - 12 if hour > 12 else hour} {'PM' if hour >= 12 else 'AM'}"
    return f"on {day:%Y-%m-%d} at {label}", f"{day:%Y-%m-%d}"


def fill(text: str, vars_: dict) -> str:
    for k, v in vars_.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def check(resp: dict, checks: dict, lat: float, vars_: dict) -> list[str]:
    fails = []
    reply = resp.get("reply", "") or ""
    low = reply.lower()
    calls = resp.get("tool_calls", []) or []
    names = [t.get("name") for t in calls]
    tokens = resp.get("tokens", {}) or {}

    for k in ("reply", "tool_calls", "tokens"):
        if k not in resp:
            fails.append(f"response missing '{k}'")
    if not reply.strip():
        fails.append("empty reply")
    if "temporary problem" in low:
        fails.append("server returned the error fallback reply")

    want = checks.get("tool_called")
    for t in ([want] if isinstance(want, str) else (want or [])):
        if t not in names:
            fails.append(f"expected tool {t}, got {names}")
    for t in checks.get("tool_not_called", []):
        if t in names:
            fails.append(f"tool {t} must not be called")
    if checks.get("no_tools") and names:
        fails.append(f"expected no tools, got {names}")
    for tool, expected in (checks.get("tool_args") or {}).items():
        matches = [c.get("args", {}) for c in calls if c.get("name") == tool]
        if not matches:
            fails.append(f"tool_args: {tool} not called")
            continue
        ok_any = False
        for args in matches:
            ok = True
            for k, v in expected.items():
                v = fill(v, vars_) if isinstance(v, str) else v
                got = args.get(k)
                if isinstance(v, list) and len(v) == 2:          # numeric range [lo, hi]
                    try:
                        ok &= got is not None and v[0] <= float(got) <= v[1]
                    except (TypeError, ValueError):
                        ok = False
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    try:
                        ok &= got is not None and abs(float(got) - float(v)) < 1e-6
                    except (TypeError, ValueError):
                        ok = False
                else:
                    ok &= got is not None and str(v).lower() in str(got).lower()
            ok_any |= ok
        if not ok_any:
            fails.append(f"tool_args: {tool} expected {expected}, got {matches}")
    for tool, status in (checks.get("tool_status") or {}).items():
        if not any(c.get("name") == tool and c.get("status") == status for c in calls):
            fails.append(f"tool_status: expected {tool}={status}, got {[(c.get('name'), c.get('status')) for c in calls]}")

    if "reply_contains_any" in checks and not any(fill(s, vars_).lower() in low for s in checks["reply_contains_any"]):
        fails.append(f"reply missing any of {checks['reply_contains_any']}")
    for s in checks.get("reply_contains_all", []):
        if fill(s, vars_).lower() not in low:
            fails.append(f"reply missing '{fill(s, vars_)}'")
    for s in checks.get("reply_not_contains", []):
        if fill(s, vars_).lower() in low:
            fails.append(f"reply must not contain '{fill(s, vars_)}'")
    if "reply_regex" in checks and not re.search(fill(checks["reply_regex"], vars_), reply, re.I):
        fails.append(f"reply does not match /{checks['reply_regex']}/")
    if "reply_not_regex" in checks and re.search(fill(checks["reply_not_regex"], vars_), reply, re.I):
        fails.append(f"reply must not match /{checks['reply_not_regex']}/")
    if "reply_ids_subset_of" in checks:
        allowed = {x.upper() for x in checks["reply_ids_subset_of"]}
        extra = sorted({m.upper() for m in ID_RE.findall(reply)} - allowed)
        if extra:
            fails.append(f"reply mentions listings outside the allowed set: {extra}")

    if checks.get("zero_tokens") and (tokens.get("in", 0) or tokens.get("out", 0)):
        fails.append(f"expected 0 tokens, used {tokens}")
    if "max_tokens_in" in checks and tokens.get("in", 0) > checks["max_tokens_in"]:
        fails.append(f"input tokens {tokens.get('in')} > budget {checks['max_tokens_in']}")
    if "max_latency_s" in checks and lat > checks["max_latency_s"]:
        fails.append(f"latency {lat:.1f}s > budget {checks['max_latency_s']}s")
    return fails


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated test ids")
    ap.add_argument("--category", default="", help="only tests whose category starts with this")
    ap.add_argument("--tests", default=str(Path(__file__).resolve().parent.parent / "tests.json"))
    ap.add_argument("--out", default="benchmark_results.json")
    args = ap.parse_args()
    # "localhost" on Windows tries IPv6 first and adds ~2 s per request; use the IPv4 loopback.
    args.base = args.base.replace("://localhost", "://127.0.0.1")

    with urllib.request.urlopen(args.base.rstrip("/") + "/health", timeout=90) as r:
        print("health:", r.read().decode().strip())

    suite = json.loads(Path(args.tests).read_text(encoding="utf-8"))["tests"]
    if args.only:
        keep = {int(x) for x in args.only.split(",") if x.strip()}
        suite = [t for t in suite if t["id"] in keep]
    if args.category:
        suite = [t for t in suite if t["category"].startswith(args.category)]

    rows, latencies, tin, tout = [], [], 0, 0
    llm_lat = []
    for run in range(args.runs):
        run_id = uuid.uuid4().hex[:6]
        rng = random.Random(run_id)
        for test in suite:
            slot, date = random_slot(rng)
            slot2, _ = random_slot(rng)
            while slot2 == slot:
                slot2, _ = random_slot(rng)
            vars_ = {"run": run_id, "slot": slot, "slot2": slot2, "date": date}
            fails, lat_test, tok_in, tok_out, last, last_lat = [], [], 0, 0, {}, 0.0
            for i, step in enumerate(test["steps"]):
                payload = {k: fill(step[k], vars_) for k in ("user_id", "thread_id", "message")}
                try:
                    resp, lat = post(args.base, payload)
                except (urllib.error.URLError, TimeoutError, ValueError) as e:
                    fails.append(f"step {i + 1}: HTTP error: {e}")
                    break
                lat_test.append(lat)
                t = resp.get("tokens", {}) or {}
                tok_in += t.get("in", 0)
                tok_out += t.get("out", 0)
                if t.get("in", 0):
                    llm_lat.append(lat)
                for name, rx in (step.get("capture") or {}).items():
                    m = re.search(rx, resp.get("reply", ""), re.I)
                    if m:
                        vars_[name] = m.group(1)
                    else:
                        fails.append(f"step {i + 1}: could not capture {name} with /{rx}/ from: {resp.get('reply', '')[:120]!r}")
                is_last = i == len(test["steps"]) - 1
                if "checks" in step and not is_last:
                    fails += [f"step {i + 1}: {f}" for f in check(resp, step["checks"], lat, vars_)]
                elif not is_last:
                    fails += [f"step {i + 1}: {f}" for f in check(resp, {}, lat, vars_)]
                last, last_lat = resp, lat
            if last and not any("HTTP error" in f for f in fails):
                final_checks = {**test.get("checks", {}), **(test["steps"][-1].get("checks") or {})}
                fails += [f"final: {f}" for f in check(last, final_checks, last_lat, vars_)]
            ok = not fails
            latencies += lat_test
            tin, tout = tin + tok_in, tout + tok_out
            rows.append({"run": run + 1, "id": test["id"], "name": test["name"], "category": test["category"],
                         "pass": ok, "fails": fails, "calls": len(lat_test),
                         "avg_latency_s": round(statistics.mean(lat_test), 2) if lat_test else None,
                         "tokens_in": tok_in, "tokens_out": tok_out, "last_reply": (last or {}).get("reply", "")[:300]})
            print(f"[{'PASS' if ok else 'FAIL'}] run{run + 1} #{test['id']:>2} {test['name']}"
                  + ("" if ok else "\n        " + "\n        ".join(fails)), flush=True)

    # ------------------------------------------------------------------ report
    Path(args.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    n = len(rows)
    passed = sum(r["pass"] for r in rows)
    cost = tin * PRICE_IN + tout * PRICE_OUT
    by_test = defaultdict(list)
    for r in rows:
        by_test[r["id"]].append(r)

    print("\n| # | Test | Category | Result | Avg latency (s) | Tokens in / out |")
    print("|---|------|----------|--------|-----------------|-----------------|")
    for tid, rs in by_test.items():
        p = sum(r["pass"] for r in rs)
        res = ("✅ pass" if p == len(rs) else "❌ fail") if len(rs) == 1 else f"{'✅' if p == len(rs) else '⚠️'} {p}/{len(rs)}"
        lat = statistics.mean([r["avg_latency_s"] for r in rs if r["avg_latency_s"] is not None] or [0])
        print(f"| {tid} | {rs[0]['name']} | {rs[0]['category']} | {res} | {lat:.2f} | "
              f"{round(statistics.mean(r['tokens_in'] for r in rs))} / {round(statistics.mean(r['tokens_out'] for r in rs))} |")

    print("\n**By rubric category**\n\n| Category | Weight | Passed | Rate |\n|---|---|---|---|")
    cats = defaultdict(lambda: [0, 0])
    for r in rows:
        c = r["category"].split(" ")[0].split("/")[0].strip()
        cats[c][0] += r["pass"]
        cats[c][1] += 1
    for c in sorted(cats, key=lambda c: -RUBRIC.get(c, 0)):
        p, t = cats[c]
        print(f"| {c} | {RUBRIC.get(c, '-')} | {p}/{t} | {100 * p / t:.0f}% |")

    if args.runs > 1:
        flaky = [tid for tid, rs in by_test.items() if 0 < sum(r["pass"] for r in rs) < len(rs)]
        consistent = sum(1 for rs in by_test.values() if len({r["pass"] for r in rs}) == 1)
        print(f"\n**Consistency:** {consistent}/{len(by_test)} tests gave the same result in all {args.runs} runs"
              + (f"; flaky: {flaky}" if flaky else ""))

    if latencies:
        s = sorted(latencies)
        p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
        print(f"\n**Pass rate:** {passed}/{n} ({100 * passed / n:.0f}%)  ")
        print(f"**Latency:** median {statistics.median(latencies):.2f}s, p95 {p95:.2f}s over {len(latencies)} calls"
              + (f" (LLM turns median {statistics.median(llm_lat):.2f}s)" if llm_lat else "") + "  ")
        zero = len(latencies) - len(llm_lat)
        print(f"**Tokens:** {tin:,} in / {tout:,} out ≈ ${cost:.4f} for the suite, ${cost / max(len(latencies), 1):.5f} "
              f"per call; {zero}/{len(latencies)} calls used 0 tokens (guard / approval paths)")


if __name__ == "__main__":
    main()

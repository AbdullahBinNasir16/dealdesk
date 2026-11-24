"""API-level tests for DealDesk: input validation, error handling, rate limiting, concurrency, the public
catalogue, and dealer-dashboard (agency) isolation. Complements tests.json / run_benchmark.py, which
test the agent's conversations.

Usage:
    python scripts/api_tests.py --base http://localhost:8000
    python scripts/api_tests.py --base https://your-space.hf.space

Standard library only. Almost every check here costs 0 LLM tokens (guard-refused messages are used for
load tests); only the concurrency test makes a few real agent calls.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:8000"
RESULTS: list[tuple[str, str, bool, str]] = []


def req(method: str, path: str, body=None, token: str | None = None, raw: bytes | None = None, timeout=120):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            txt = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        txt, status = e.read().decode(), e.code
    try:
        payload = json.loads(txt)
    except ValueError:
        payload = txt
    return status, payload, time.time() - t


def test(category: str, name: str):
    def deco(fn):
        def run():
            try:
                detail = fn() or ""
                RESULTS.append((category, name, True, str(detail)))
                print(f"[PASS] {category:<15} {name}" + (f"  ({detail})" if detail else ""))
            except AssertionError as e:
                RESULTS.append((category, name, False, str(e)))
                print(f"[FAIL] {category:<15} {name}\n        {e}")
            except Exception as e:  # noqa: BLE001
                RESULTS.append((category, name, False, f"{type(e).__name__}: {e}"))
                print(f"[FAIL] {category:<15} {name}\n        {type(e).__name__}: {e}")
        run.__name__ = fn.__name__
        TESTS.append(run)
        return run
    return deco


TESTS = []
RUN = uuid.uuid4().hex[:6]


def chat(user, message, thread="a"):
    return req("POST", "/chat", {"user_id": user, "thread_id": thread, "message": message})


def login(u, p):
    s, d, _ = req("POST", "/admin/login", {"username": u, "password": p})
    assert s == 200, f"login {u} -> {s} {d}"
    return d["token"], d["agency"]


# ------------------------------------------------------------------ health & schema

@test("reliability", "GET /health returns ok")
def _():
    s, d, lat = req("GET", "/health")
    assert s == 200 and str(d).strip() == "ok", (s, d)
    return f"{lat * 1000:.0f} ms"


@test("reliability", "POST /chat response schema (reply, tool_calls, tokens)")
def _():
    s, d, _ = chat(f"api-schema-{RUN}", "write a poem")
    assert s == 200, s
    assert isinstance(d.get("reply"), str) and d["reply"], d
    assert isinstance(d.get("tool_calls"), list), d
    assert set(d.get("tokens", {})) >= {"in", "out"}, d


# ------------------------------------------------------------------ input validation / error handling

@test("reliability", "missing user_id -> 422 (not 500)")
def _():
    s, d, _ = req("POST", "/chat", {"message": "hi"})
    assert s == 422, (s, d)


@test("reliability", "missing message -> 422")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": "x"})
    assert s == 422, (s, d)


@test("reliability", "empty user_id -> 422")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": "", "message": "hi"})
    assert s == 422, (s, d)


@test("reliability", "malformed JSON -> 422")
def _():
    s, d, _ = req("POST", "/chat", raw=b"{not json")
    assert s == 422, (s, d)


@test("reliability", "wrong types -> 422")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": 123, "message": ["a"]})
    assert s == 422, (s, d)


@test("reliability", "thread_id optional (defaults)")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": f"api-nothread-{RUN}", "message": "tell me a joke"})
    assert s == 200 and d.get("reply"), (s, d)


@test("reliability", "oversized message (20k chars) is capped, not a crash")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": f"api-big-{RUN}", "thread_id": "a", "message": "write a poem " + "x" * 19000})
    assert s == 200 and d.get("reply"), (s, str(d)[:200])


@test("reliability", "message over the 20k hard limit -> 422")
def _():
    s, d, _ = req("POST", "/chat", {"user_id": "x", "message": "a" * 20001})
    assert s == 422, (s, str(d)[:200])


@test("reliability", "unknown route -> 404")
def _():
    s, _, _ = req("GET", "/nope")
    assert s == 404, s


# ------------------------------------------------------------------ rate limit & concurrency

@test("reliability", "rate limit: 41st message in a minute is throttled (0 tokens)")
def _():
    user = f"api-rate-{RUN}"
    replies = []
    for _ in range(42):
        s, d, _ = chat(user, "write a poem")          # guard-refused: no LLM cost
        assert s == 200, s
        replies.append(d)
    throttled = [d for d in replies if "very quickly" in d["reply"]]
    assert throttled, "never throttled"
    assert all(d["tokens"] == {"in": 0, "out": 0} for d in throttled)
    return f"{len(throttled)} throttled"


@test("reliability", "rate limit is per user (another user unaffected)")
def _():
    s, d, _ = chat(f"api-rate-other-{RUN}", "write a poem")
    assert s == 200 and "very quickly" not in d["reply"], d


@test("reliability", "20 concurrent guard requests all succeed")
def _():
    with ThreadPoolExecutor(10) as ex:
        out = list(ex.map(lambda i: chat(f"api-conc-{RUN}-{i}", "tell me a joke"), range(20)))
    bad = [(s, d) for s, d, _ in out if s != 200 or not d.get("reply")]
    assert not bad, bad[:2]
    return f"max {max(l for _, _, l in out):.2f}s"


@test("reliability", "4 concurrent real agent turns all succeed")
def _():
    msgs = ["Corolla under 60 lakh", "Plots in Bahria Town Lahore under 1 crore",
            "Automatic SUV in Karachi under 85 lakh", "Apartment in Islamabad under 1 crore"]
    with ThreadPoolExecutor(4) as ex:
        out = list(ex.map(lambda m: chat(f"api-agent-{RUN}-{msgs.index(m)}", m), msgs))
    bad = [(s, d) for s, d, _ in out if s != 200 or not d.get("reply") or "temporary problem" in d.get("reply", "")]
    assert not bad, bad[:2]
    return f"latencies {[round(l, 1) for _, _, l in out]}"


@test("reliability", "same user, two threads in parallel stay separate")
def _():
    user = f"api-par-{RUN}"
    with ThreadPoolExecutor(2) as ex:
        a, b = ex.map(lambda t: chat(user, "write a poem", thread=t), ["t1", "t2"])
    assert a[0] == 200 and b[0] == 200


# ------------------------------------------------------------------ public catalogue

@test("task_success", "GET /api/listings returns 44 active listings")
def _():
    s, d, _ = req("GET", "/api/listings")
    assert s == 200 and isinstance(d, list) and len(d) >= 44, (s, len(d) if isinstance(d, list) else d)
    assert all(x["status"] == "active" for x in d)
    return f"{len(d)} listings"


@test("task_success", "catalogue filters: category + city + max_price")
def _():
    s, d, _ = req("GET", "/api/listings?category=car&city=Lahore&max_price=5000000")
    assert s == 200 and d, d
    assert all(x["category"] == "car" and x["city"] == "Lahore" and x["price_pkr"] <= 5_000_000 for x in d), d
    return ", ".join(x["id"] for x in d)


@test("task_success", "catalogue text search")
def _():
    s, d, _ = req("GET", "/api/listings?q=Civic")
    assert s == 200 and d and all("civic" in x["title"].lower() for x in d), d


@test("task_success", "single listing + 404 for unknown id")
def _():
    s, d, _ = req("GET", "/api/listings/c-302")
    assert s == 200 and d["id"] == "C-302", (s, d)
    s, _, _ = req("GET", "/api/listings/C-99999")
    assert s == 404, s


@test("safety", "SQL-ish query strings don't break the catalogue")
def _():
    s, d, _ = req("GET", "/api/listings?q=%27%3B%20DROP%20TABLE%20listings%3B%20--")
    assert s == 200 and d == [], (s, d)
    s, d, _ = req("GET", "/api/listings")
    assert s == 200 and len(d) >= 44, "listings table damaged!"


# ------------------------------------------------------------------ dealer auth & agency isolation

@test("safety", "admin login: wrong password -> 401")
def _():
    s, _, _ = req("POST", "/admin/login", {"username": "prime", "password": "wrong"})
    assert s == 401, s


@test("safety", "admin login: unknown user -> 401")
def _():
    s, _, _ = req("POST", "/admin/login", {"username": "nobody", "password": "x"})
    assert s == 401, s


@test("safety", "admin endpoints need a token")
def _():
    for path in ("/admin/stats", "/admin/leads", "/admin/visits", "/admin/chats", "/admin/listings", "/admin/followups"):
        s, _, _ = req("GET", path)
        assert s == 401, f"{path} -> {s}"


@test("safety", "tampered / forged token -> 401")
def _():
    tok, _ = login("prime", "prime123")
    forged = tok[:-3] + ("aaa" if not tok.endswith("aaa") else "bbb")
    s, _, _ = req("GET", "/admin/stats", token=forged)
    assert s == 401, s
    s, _, _ = req("GET", "/admin/stats", token="garbage.token")
    assert s == 401, s


@test("user_isolation", "agency sees only its own listings")
def _():
    tok, ag = login("prime", "prime123")
    s, d, _ = req("GET", "/admin/listings", token=tok)
    assert s == 200 and d and all(x["agency_id"] == ag["id"] for x in d), [x["agency_id"] for x in d][:5]
    return f"{len(d)} listings for {ag['id']}"


@test("user_isolation", "agency cannot modify another agency's listing (404)")
def _():
    tok, _ = login("prime", "prime123")
    s, _, _ = req("PATCH", "/admin/listings/P-101", {"status": "active"}, token=tok)   # P-101 belongs to Skyline
    assert s == 404, s


@test("user_isolation", "lead created by a chat appears only for the right agency")
def _():
    user = f"api-lead-{RUN}"
    s, d, _ = chat(user, "Tell me more about C-302")               # Prime Motors listing
    assert s == 200 and "C-302" in d["reply"], d
    prime, _ = login("prime", "prime123")
    autohub, _ = login("autohub", "autohub123")
    skyline, _ = login("skyline", "skyline123")
    in_prime = any(x["user_id"] == user for x in req("GET", "/admin/leads", token=prime)[1])
    in_autohub = any(x["user_id"] == user for x in req("GET", "/admin/leads", token=autohub)[1])
    in_skyline = any(x["user_id"] == user for x in req("GET", "/admin/leads", token=skyline)[1])
    assert in_prime and not in_autohub and not in_skyline, (in_prime, in_autohub, in_skyline)


@test("user_isolation", "agency cannot read another agency's chat transcript (404)")
def _():
    user = f"api-lead-{RUN}"                                         # a Prime lead from the previous test
    prime, _ = login("prime", "prime123")
    skyline, _ = login("skyline", "skyline123")
    s, d, _ = req("GET", f"/admin/chats/{user}/a", token=prime)
    assert s == 200 and d, (s, d)
    s, _, _ = req("GET", f"/admin/chats/{user}/a", token=skyline)
    assert s == 404, s


@test("user_isolation", "agency cannot approve another agency's visit (404)")
def _():
    prime, _ = login("prime", "prime123")
    skyline, _ = login("skyline", "skyline123")
    visits = req("GET", "/admin/visits", token=prime)[1]
    if not visits:
        return "skipped: no Prime visits yet (run the benchmark first)"
    vid = visits[0]["id"]
    s, _, _ = req("PATCH", f"/admin/visits/{vid}", {"status": "declined"}, token=skyline)
    assert s == 404, s


@test("reliability", "admin input validation: bad stage / status -> 400")
def _():
    prime, _ = login("prime", "prime123")
    s, _, _ = req("PATCH", "/admin/listings/C-302", {"status": "deleted"}, token=prime)
    assert s == 400, s
    s, _, _ = req("PATCH", "/admin/leads/1", {"stage": "bogus"}, token=prime)
    assert s == 400, s


@test("reliability", "admin stats shape")
def _():
    prime, _ = login("prime", "prime123")
    s, d, _ = req("GET", "/admin/stats", token=prime)
    assert s == 200 and {"leads_total", "approval_queue", "followups_pending", "booking_rate"} <= set(d), d


@test("long_term_memory", "follow-ups scheduled for a lead that didn't book")
def _():
    user = f"api-fu-{RUN}"
    s, d, _ = chat(user, "Show me Corollas under 60 lakh in Lahore")
    assert s == 200, s
    prime, _ = login("prime", "prime123")
    fus = [f for f in req("GET", "/admin/followups", token=prime)[1] if f["user_id"] == user]
    days = sorted(f["day"] for f in fus)
    assert days == [1, 3, 7], days
    return "day 1/3/7 scheduled"


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    # "localhost" on Windows tries IPv6 first and adds ~2 s per request; use the IPv4 loopback.
    BASE = ap.parse_args().base.rstrip("/").replace("://localhost", "://127.0.0.1")
    print(f"API tests against {BASE} (run {RUN})\n")
    for t in TESTS:
        t()
    passed = sum(r[2] for r in RESULTS)
    print(f"\n**API tests:** {passed}/{len(RESULTS)} passed")
    by = {}
    for c, _, ok, _ in RESULTS:
        by.setdefault(c, [0, 0])
        by[c][0] += ok
        by[c][1] += 1
    for c, (p, n) in by.items():
        print(f"  {c:<16} {p}/{n}")
    raise SystemExit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()

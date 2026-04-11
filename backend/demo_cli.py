"""
ADHD Reading Companion — 5-Stage Demo CLI

Stages:
  Stage 1: Upload a PDF
  Stage 2: Enter your name (creates the session)
  Stage 3: Choose a persona (Professor | ADHD Peer)
  Stage 4: Persona intro + full-text reading + neutral chatbot (explain highlights)
  Stage 5: 9-question MCQ test (persona-voiced), answers saved, graded results
"""
import json
import mimetypes
import os
import sys
import uuid
from datetime import datetime, timezone
from urllib import error, request

BASE_URL = os.getenv("DEMO_API_BASE", "http://localhost:8000").rstrip("/")

# ── Shared CLI state ──────────────────────────────────────────────────────────

STATE = {
    "document_id": None,
    "session_id": None,
    "user_id": "user_1",   # internal id (slug of user_name)
    "user_name": None,
    "persona": None,
    "questions": [],        # generated MCQ list
    "saved_answers": {},    # {question_id: selected_answer}  persisted mid-test
    "test_started_at": None,
}

# ── Terminal colour helpers ───────────────────────────────────────────────────

_USE_COLOUR = sys.stdout.isatty() and os.name != "nt"


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def red(t):    return _c("31", t)
def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def cyan(t):   return _c("36", t)
def bold(t):   return _c("1",  t)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def parse_body(raw):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def http_request(method, path, json_body=None, data=None, headers=None):
    url = f"{BASE_URL}{path}"
    req_headers = headers.copy() if headers else {}
    body = data
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = request.Request(url=url, data=body, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=180) as resp:
            return resp.status, parse_body(resp.read())
    except error.HTTPError as e:
        return e.code, parse_body(e.read())
    except (error.URLError, TimeoutError, ConnectionError) as e:
        return None, {"error": f"Cannot reach {BASE_URL}: {e}"}
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


def encode_multipart(file_field, file_path, extra=None):
    extra = extra or {}
    boundary = f"----Boundary{uuid.uuid4().hex}"
    parts = []
    for name, value in extra.items():
        value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        parts += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ]
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/pdf"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    parts += [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        file_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    return body, {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }


# ── I/O helpers ───────────────────────────────────────────────────────────────

def prompt(text, default=""):
    label = text + (f" [{default}]" if default else "") + ": "
    val = input(label).strip()
    return val if val else default


def section(title):
    print()
    print(bold("=" * 60))
    print(bold(f"  {title}"))
    print(bold("=" * 60))


def ok(msg):    print(green(f"  \u2713 {msg}"))
def err(msg):   print(red(f"  \u2717 {msg}"))
def info(msg):  print(cyan(f"  \u2192 {msg}"))
def warn(msg):  print(yellow(f"  ! {msg}"))


def die(msg):
    err(msg)
    sys.exit(1)


def require_ok(status, payload, ctx=""):
    if status and 200 <= status < 300:
        return payload
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    die(f"{ctx} failed (HTTP {status}): {detail}")


# ── Stage 1: Upload PDF ───────────────────────────────────────────────────────

def stage1_upload():
    section("Stage 1 \u2014 Upload PDF")
    file_path = prompt("Path to PDF file")
    if not os.path.exists(file_path):
        die(f"File not found: {file_path}")

    info("Uploading and processing document (this may take a moment)\u2026")
    body, headers = encode_multipart("file", file_path)
    status, payload = http_request(
        "POST", f"/documents/upload?user_id={STATE['user_id']}",
        data=body, headers=headers,
    )
    require_ok(status, payload, "Upload")

    STATE["document_id"] = payload["document_id"]
    ok(f"Document uploaded: {payload['filename']}")
    ok(f"Document ID: {STATE['document_id']}")
    info("Press Enter to continue to Stage 2.")
    input()


# ── Stage 2: Enter username → create session ──────────────────────────────────

def stage2_username():
    section("Stage 2 \u2014 Enter Your Name")
    name = prompt("Your name (used to identify your session)")
    if not name:
        die("Name cannot be empty.")

    user_id = name.strip().lower().replace(" ", "_")
    STATE["user_name"] = name
    STATE["user_id"] = user_id

    if not STATE["document_id"]:
        STATE["document_id"] = prompt("Document ID (from Stage 1)")

    info("Creating reading session\u2026")
    status, payload = http_request(
        "POST", "/sessions",
        json_body={"user_id": user_id, "document_id": STATE["document_id"]},
    )
    require_ok(status, payload, "Create session")

    STATE["session_id"] = str(payload["session_id"])
    ok(f"Session created: {STATE['session_id']}")
    ok(f"Hello, {name}!")
    info("Press Enter to continue to Stage 3.")
    input()


# ── Stage 3: Choose persona ────────────────────────────────────────────────────

def stage3_persona():
    section("Stage 3 \u2014 Choose Your Persona")
    print()
    print("  \u250c" + "\u2500" * 53 + "\u2510")
    print("  \u2502  1.  Professor                                       \u2502")
    print("  \u2502      A university professor who guides you through  \u2502")
    print("  \u2502      the material in a structured, academic tone.   \u2502")
    print("  \u251c" + "\u2500" * 53 + "\u2524")
    print("  \u2502  2.  ADHD Peer                                       \u2502")
    print("  \u2502      A college peer who also has ADHD \u2014 warm,       \u2502")
    print("  \u2502      casual, and conversational support.             \u2502")
    print("  \u2514" + "\u2500" * 53 + "\u2518")
    print()

    while True:
        choice = prompt("Choose persona (1 or 2)", "1")
        if choice == "1":
            persona = "professor"
            break
        elif choice == "2":
            persona = "peer"
            break
        else:
            warn("Please enter 1 or 2.")

    STATE["persona"] = persona

    if not STATE["session_id"]:
        STATE["session_id"] = prompt("Session ID (from Stage 2)")

    info(f"Setting persona to '{persona}' and generating introduction\u2026")
    status, payload = http_request(
        "POST", "/persona/select",
        json_body={"session_id": STATE["session_id"], "persona": persona},
    )
    require_ok(status, payload, "Persona select")

    print()
    print(bold(f"  [{persona.upper()} SELF-INTRODUCTION]"))
    print()
    for line in payload["intro"].split("\n"):
        print(f"  {line}")
    print()
    ok(f"Persona '{persona}' activated.")
    info("Press Enter to continue to Stage 4 (Reading).")
    input()


# ── Stage 4: Full-text reading + neutral chatbot ──────────────────────────────

def stage4_reading():
    section("Stage 4 \u2014 Reading Stage")

    if not STATE["document_id"]:
        STATE["document_id"] = prompt("Document ID")

    info("Fetching full document text\u2026")
    status, payload = http_request(
        "GET", f"/documents/{STATE['document_id']}/full-text"
    )
    require_ok(status, payload, "Fetch full text")

    full_text = payload["full_text"]

    print()
    print(bold("  \u2500\u2500 DOCUMENT TEXT " + "\u2500" * 44))
    for para in full_text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        words = para.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 82:
                print(line)
                line = "  " + word
            else:
                line += (" " if line.strip() else "") + word
        if line.strip():
            print(line)
        print()
    print(bold("  \u2500\u2500 END OF DOCUMENT " + "\u2500" * 42))

    print()
    print(cyan("  Neutral Chatbot is active."))
    print(cyan("  Paste any sentence from the text above to get an explanation."))
    print(cyan("  Type 'done' when you are ready to proceed to the test."))
    print()

    while True:
        highlighted = input(bold("  Paste highlighted text (or 'done'): ")).strip()
        if highlighted.lower() in ("done", "d", ""):
            print()
            ok("Reading stage complete.")
            break

        info("Explaining highlighted passage\u2026")
        status, payload = http_request(
            "POST", "/explain/selection",
            json_body={
                "document_id": STATE["document_id"],
                "selected_text": highlighted,
                "surrounding_text": "",
            },
        )
        if status and 200 <= status < 300:
            print()
            print(bold("  [CHATBOT EXPLANATION]"))
            for line in payload["explanation"].split("\n"):
                print(f"  {line}")
            print()
        else:
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            warn(f"Explanation failed: {detail}")

    info("Press Enter to continue to Stage 5 (Test).")
    input()


# ── Stage 5: MCQ test ─────────────────────────────────────────────────────────

def _generate_questions():
    info("Generating 9 questions \u2014 this may take ~30 seconds\u2026")
    status, payload = http_request(
        "POST", "/learning-test/generate",
        json_body={
            "document_id": STATE["document_id"],
            "user_id": STATE["user_id"],
            "persona": STATE["persona"],
        },
    )
    require_ok(status, payload, "Generate questions")
    STATE["questions"] = payload["questions"]
    ok(f"Generated {len(STATE['questions'])} questions.")
    return STATE["questions"]


def _load_saved_answers():
    if not STATE["session_id"]:
        return {}
    status, payload = http_request(
        "GET", f"/learning-test/state?session_id={STATE['session_id']}"
    )
    if status == 200 and isinstance(payload, dict):
        STATE["saved_answers"] = payload.get("answers", {})
    return STATE["saved_answers"]


def _save_answer(question_id, selected, correct, difficulty):
    if not STATE["session_id"]:
        return
    http_request(
        "POST", "/learning-test/answer",
        json_body={
            "session_id": STATE["session_id"],
            "question_id": question_id,
            "selected_answer": selected,
            "correct_answer": correct,
            "difficulty": difficulty,
        },
    )
    STATE["saved_answers"][question_id] = selected


def _display_question(idx, q, saved):
    diff_label = {
        "easy": green("EASY"),
        "medium": yellow("MEDIUM"),
        "hard": red("HARD"),
    }.get(q["difficulty"].lower(), q["difficulty"].upper())
    print()
    print(bold(f"  Q{idx}. [{diff_label}]  {q['question']}"))
    for opt in q["options"]:
        print(f"       {opt}")
    pre = saved.get(q["id"])
    if pre:
        print(cyan(f"       (Previously answered: {pre})"))


def stage5_test():
    section("Stage 5 \u2014 Knowledge Test")
    print()
    print(yellow("  Note: the chatbot is disabled during the test."))
    print(yellow("  Type 'back' at any question to return to the reading stage."))
    print(yellow("  Your answers are auto-saved \u2014 you can return and continue."))
    print()

    if not STATE["questions"]:
        _generate_questions()

    STATE["test_started_at"] = datetime.now(timezone.utc).isoformat()

    questions = STATE["questions"]
    saved = _load_saved_answers()

    by_diff = {"easy": [], "medium": [], "hard": []}
    for q in questions:
        by_diff.setdefault(q["difficulty"].lower(), []).append(q)

    display_order = []
    for diff in ("easy", "medium", "hard"):
        display_order.extend(by_diff.get(diff, []))

    idx = 0
    while idx < len(display_order):
        q = display_order[idx]
        _display_question(idx + 1, q, saved)
        pre = saved.get(q["id"])
        raw = prompt("  Your answer (A/B/C/D)", pre or "A").strip().upper()

        if raw in ("BACK", "RETURN"):
            warn("Returning to reading stage \u2014 your answers are saved.")
            stage4_reading()
            saved = _load_saved_answers()
            idx = 0
            continue

        if raw not in ("A", "B", "C", "D"):
            warn("Please enter A, B, C, or D.")
            continue

        _save_answer(q["id"], raw, q["correct_answer"], q["difficulty"])
        saved[q["id"]] = raw
        idx += 1

    section("Submitting Test")
    answers_list = [
        {"question_id": q["id"], "selected": saved.get(q["id"], "A")}
        for q in display_order
    ]

    info("Grading your answers\u2026")
    status, payload = http_request(
        "POST", "/learning-test/submit",
        json_body={
            "session_id": STATE["session_id"],
            "document_id": STATE["document_id"],
            "user_id": STATE["user_id"],
            "user_name": STATE["user_name"] or STATE["user_id"],
            "persona": STATE["persona"],
            "questions": display_order,
            "answers": answers_list,
            "started_at": STATE["test_started_at"],
        },
    )
    require_ok(status, payload, "Submit test")
    _display_results(payload, display_order, saved)


def _display_results(payload, questions, saved):
    section("Results")
    results_by_id = {r["question_id"]: r for r in payload.get("results", [])}
    total = payload.get("max_score", len(questions))
    score = payload.get("total_score", 0)
    accuracy = round(score / total * 100, 1) if total else 0.0

    print()
    for idx, q in enumerate(questions, 1):
        r = results_by_id.get(q["id"], {})
        is_correct = r.get("is_correct", False)
        selected = saved.get(q["id"], "?")
        correct_ans = q["correct_answer"]
        diff_label = {"easy": "EASY", "medium": "MED ", "hard": "HARD"}.get(
            q["difficulty"].lower(), "    "
        )
        icon = green("\u2713") if is_correct else red("\u2717")
        q_text = q["question"][:70] + ("\u2026" if len(q["question"]) > 70 else "")
        print(f"  {icon}  Q{idx} [{diff_label}]  {q_text}")
        if is_correct:
            print(green(f"       Your answer: {selected}  (correct)"))
        else:
            print(red(f"       Your answer: {selected}"))
            print(green(f"       Correct answer: {correct_ans}"))
        if r.get("explanation"):
            for line in r["explanation"].split("\n")[:2]:
                print(f"       {cyan(line)}")
        print()

    print(bold(f"  Score: {score} / {total}   Accuracy: {accuracy}%"))
    print()
    if payload.get("feedback"):
        print(bold("  Overall Feedback:"))
        for line in payload["feedback"].split("\n"):
            print(f"  {line}")
        print()

    print(bold("  Session log written:"))
    print(f"    Name:    {STATE['user_name'] or STATE['user_id']}")
    print(f"    Persona: {STATE['persona']}")
    print(f"    Score:   {score}/{total}  ({accuracy}%)")
    print()
    ok("Thank you for using the ADHD Reading Companion!")


# ── Logs viewer ────────────────────────────────────────────────────────────────

def view_logs():
    section("All Session Logs")
    status, payload = http_request("GET", "/learning-test/logs")
    if not (status and 200 <= status < 300):
        err(f"Could not load logs (HTTP {status})")
        return
    if not payload:
        info("No logs recorded yet.")
        return
    for log in payload:
        print(f"  {'\u2500' * 56}")
        print(f"  Name:      {log['user_name']}")
        print(f"  Persona:   {log['persona']}")
        acc = round(log["accuracy"] * 100, 1)
        print(f"  Score:     {log['total_correct']}/{log['total_questions']}  ({acc}%)")
        print(f"  Submitted: {log.get('submitted_at', '?')}")
    print()


# ── Main menu ─────────────────────────────────────────────────────────────────

def print_menu():
    doc = (STATE["document_id"] or "\u2014")[:36]
    ses = (STATE["session_id"] or "\u2014")[:36]
    usr = STATE["user_name"] or STATE["user_id"]
    per = STATE["persona"] or "\u2014"
    print()
    print(bold("=" * 60))
    print(bold("  ADHD Reading Companion \u2014 5-Stage Demo CLI"))
    print(bold(f"  {BASE_URL}"))
    print(bold("=" * 60))
    print(f"  doc={doc}  session={ses}")
    print(f"  user={usr}  persona={per}")
    print()
    print("  \u2500\u2500 Guided Flow \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print("  1.  Stage 1 \u2014 Upload PDF")
    print("  2.  Stage 2 \u2014 Enter name / create session")
    print("  3.  Stage 3 \u2014 Choose persona")
    print("  4.  Stage 4 \u2014 Read document + chatbot")
    print("  5.  Stage 5 \u2014 Knowledge test")
    print()
    print("  \u2500\u2500 Utilities \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print("  6.  Run full flow (stages 1 \u2192 5)")
    print("  7.  View all session logs")
    print("  0.  Exit")
    print(bold("-" * 60))


def run_full_flow():
    stage1_upload()
    stage2_username()
    stage3_persona()
    stage4_reading()
    stage5_test()


def main():
    status, _ = http_request("GET", "/health")
    if status != 200:
        die(
            f"Backend not reachable at {BASE_URL}.\n"
            "  Start with:  uvicorn app.main:app --host 0.0.0.0 --port 8000\n"
            f"  Or set:      DEMO_API_BASE=http://... python demo_cli.py"
        )

    print()
    print(bold("  ADHD Reading Companion \u2014 Demo CLI ready."))
    print(bold(f"  Connected to: {BASE_URL}"))
    print()

    handlers = {
        "1": stage1_upload,
        "2": stage2_username,
        "3": stage3_persona,
        "4": stage4_reading,
        "5": stage5_test,
        "6": run_full_flow,
        "7": view_logs,
    }

    while True:
        print_menu()
        choice = input(bold("  Choose option: ")).strip()
        if choice == "0":
            print()
            ok("Goodbye!")
            break
        fn = handlers.get(choice)
        if fn:
            try:
                fn()
            except KeyboardInterrupt:
                print()
                warn("Interrupted. Returning to menu.")
        else:
            warn("Invalid option.")


if __name__ == "__main__":
    main()

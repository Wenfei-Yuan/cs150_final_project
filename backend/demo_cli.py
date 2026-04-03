"""
ADHD Reading Companion — Mode-Aware Demo CLI

This CLI exercises the full mode-aware reading pipeline:
  Step 1: Upload document → Create session
  Step 2: Session setup (3 questions → LLM mode selection)
  Step 3: Mind map navigation
  Step 4: Mode-specific reading loop
  Step 5: Takeaway / session conclusion
"""
import json
import mimetypes
import os
import sys
import uuid
from urllib import error, request

BASE_URL = os.getenv("DEMO_API_BASE", "http://localhost:8000").rstrip("/")

STATE = {
    "document_id": None,
    "session_id": None,
    "user_id": "1",
    "mode": None,
}


def pretty(title, value):
    print(f"\n=== {title} ===")
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)
    print()


def parse_body(raw):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def remember_ids(payload):
    if not isinstance(payload, dict):
        return
    if payload.get("document_id") is not None:
        STATE["document_id"] = payload["document_id"]
    if payload.get("session_id") is not None:
        STATE["session_id"] = payload["session_id"]
    if payload.get("user_id") is not None:
        STATE["user_id"] = payload["user_id"]
    if payload.get("mode") is not None:
        STATE["mode"] = payload["mode"]
    if payload.get("recommended_mode") is not None:
        STATE["mode"] = payload["recommended_mode"]


def http_request(method, path, json_body=None, data=None, headers=None):
    url = f"{BASE_URL}{path}"
    req_headers = headers.copy() if headers else {}
    body = data
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = request.Request(url=url, data=body, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=120) as resp:
            return resp.status, parse_body(resp.read())
    except error.HTTPError as e:
        return e.code, parse_body(e.read())
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def print_result(status, payload):
    pretty("HTTP Status", status)
    pretty("Response", payload)
    remember_ids(payload)


def prompt_input(text, default=None):
    label = text
    if default not in (None, ""):
        label += f" [{default}]"
    label += ": "
    value = input(label).strip()
    return value if value else (default or "")


def encode_multipart(file_field, file_path, extra=None):
    extra = extra or {}
    boundary = f"----Boundary{uuid.uuid4().hex}"
    chunks = []
    for name, value in extra.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        else:
            value = str(value)
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/pdf"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode())
    chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode())
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return body, headers


# ── Step 1: Upload + Create Session ───────────────────────────────────────────

def health_check():
    status, payload = http_request("GET", "/health")
    print_result(status, payload)


def upload_document():
    file_path = prompt_input("PDF path")
    if not os.path.exists(file_path):
        print("\nFile not found.\n")
        return
    user_id = prompt_input("user_id", str(STATE["user_id"] or 1))
    body, headers = encode_multipart("file", file_path)
    status, payload = http_request("POST", f"/documents/upload?user_id={user_id}", data=body, headers=headers)
    print_result(status, payload)


def create_session():
    did = STATE["document_id"]
    uid = STATE["user_id"] or "1"
    if not did:
        did = prompt_input("document_id")
    payload = {"user_id": uid, "document_id": did}
    status, resp = http_request("POST", "/sessions", json_body=payload)
    print_result(status, resp)


# ── Step 2: Session Setup (3 Questions → Mode Selection) ─────────────────────

def session_setup():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")

    # Fetch setup questions
    status, questions = http_request("GET", "/sessions/setup-questions")
    if status != 200:
        print_result(status, questions)
        return

    print("\n" + "=" * 50)
    print("  SESSION SETUP — Answer 3 questions")
    print("=" * 50)

    # Extract the questions list from the response dict
    q_list = questions.get("questions", questions) if isinstance(questions, dict) else questions

    answers = {}
    for q in q_list:
        print(f"\n  {q['question']}")
        for i, opt in enumerate(q["options"]):
            print(f"    {i}. {opt}")
        while True:
            choice = prompt_input("  Your choice (0-3)", "0")
            if choice in ("0", "1", "2", "3"):
                answers[q["id"]] = int(choice)
                break
            print("  Please enter 0, 1, 2, or 3.")

    # Submit answers
    status, resp = http_request("POST", f"/sessions/{sid}/setup", json_body=answers)
    print_result(status, resp)

    if isinstance(resp, dict) and resp.get("recommended_mode"):
        print(f"  Recommended mode: {resp['recommended_mode']}")
        print(f"  Explanation: {resp.get('mode_explanation', '')}")
        override = prompt_input("  Accept mode? (y/n)", "y")
        if override.lower() == "n":
            alt_modes = resp.get("alternative_modes", [])
            if alt_modes:
                print("\n  Alternative modes:")
                for i, m in enumerate(alt_modes):
                    print(f"    {i}. {m['mode']}: {m['description'][:80]}...")
                choice = prompt_input("  Choose alternative (number)", "0")
                idx = int(choice) if choice.isdigit() else 0
                new_mode = alt_modes[min(idx, len(alt_modes) - 1)]["mode"]
                status, resp = http_request(
                    "POST", f"/sessions/{sid}/mode-override",
                    json_body={"mode": new_mode},
                )
                print_result(status, resp)


# ── Step 3: Mind Map ──────────────────────────────────────────────────────────

def show_mind_map():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, payload = http_request("GET", f"/sessions/{sid}/mind-map")
    print_result(status, payload)

    if isinstance(payload, dict) and "sections" in payload:
        print("\n  DOCUMENT MIND MAP:")
        for s in payload["sections"]:
            print(f"    [{s.get('section_index', '?')}] {s.get('section_type', '?')}: {s.get('title', '?')}")
            print(f"        {s.get('summary', '')[:100]}")


def jump_to_section():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    idx = prompt_input("Section index to jump to", "0")
    status, resp = http_request("POST", f"/sessions/{sid}/jump", json_body={"section_index": int(idx)})
    print_result(status, resp)


# ── Step 4: Reading Loop (mode-specific) ─────────────────────────────────────

def get_current_chunk():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, payload = http_request("GET", f"/sessions/{sid}/current")
    print_result(status, payload)


def next_chunk():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, resp = http_request("POST", f"/sessions/{sid}/next", json_body={})
    print_result(status, resp)


def skip_chunk():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, resp = http_request("POST", f"/sessions/{sid}/skip", json_body={})
    print_result(status, resp)


# ── Skim Mode Interactions ────────────────────────────────────────────────────

def get_full_summary():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, resp = http_request("GET", f"/sessions/{sid}/full-summary")
    print_result(status, resp)


def self_assess():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    choice = prompt_input("Understood this section? (y/n)", "y")
    understood = choice.lower() == "y"
    status, resp = http_request("POST", f"/sessions/{sid}/self-assess", json_body={"understood": understood})
    print_result(status, resp)

    if not understood:
        question = prompt_input("What would you like to know?", "")
        if question:
            status, resp = http_request("POST", f"/sessions/{sid}/ask-question", json_body={"question": question})
            print_result(status, resp)


# ── Goal-Directed Mode Interactions ──────────────────────────────────────────

def set_goal():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    goal = prompt_input("Your research goal/question")
    status, resp = http_request("POST", f"/sessions/{sid}/goal", json_body={"goal": goal})
    print_result(status, resp)


def goal_check():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    choice = prompt_input("Was this chunk helpful for your goal? (y/n)", "y")
    helpful = choice.lower() == "y"
    status, resp = http_request("POST", f"/sessions/{sid}/goal-check", json_body={"helpful": helpful})
    print_result(status, resp)


# ── Deep Mode Interactions ───────────────────────────────────────────────────

def submit_retell():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    text = input("Enter your retell (or press Enter to skip):\n> ").strip()
    status, resp = http_request("POST", f"/sessions/{sid}/retell", json_body={"text": text})
    print_result(status, resp)


def get_quiz():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, resp = http_request("GET", f"/sessions/{sid}/quiz")
    print_result(status, resp)

    if isinstance(resp, dict) and "question" in resp:
        q = resp["question"]
        print(f"\n  Question: {q['question']}")
        if q.get("options"):
            for opt in q["options"]:
                print(f"    {opt}")
        answer = prompt_input("Your answer")

        status2, resp2 = http_request("POST", f"/sessions/{sid}/quiz-answer",
                                       json_body={"question_id": q["id"], "answer": answer})
        print_result(status2, resp2)

        if isinstance(resp2, dict) and not resp2.get("correct", True):
            print("  Options: retry, mark_for_later, skip")
            action = prompt_input("What do you want to do?", "skip")
            status3, resp3 = http_request("POST", f"/sessions/{sid}/quiz-action",
                                           json_body={"action": action})
            print_result(status3, resp3)


def submit_quick_check():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")

    # Fetch questions from the current chunk
    print("\nFetching questions for current chunk...")
    q_status, q_resp = http_request("GET", f"/sessions/{sid}/current")
    questions = []
    if isinstance(q_resp, dict):
        questions = q_resp.get("quick_check_questions", [])

    if not questions:
        print("\nNo questions found for this chunk.\n")
        return

    print(f"\n  {len(questions)} question(s) found:\n")
    answers = []
    for i, q in enumerate(questions, 1):
        qid = q.get("id", f"q{i}")
        qtype = q.get("question_type", "")
        qtext = q.get("question", "")
        print(f"  Q{i} [{qtype}]: {qtext}")
        ans = input("  Your answer: ").strip()
        if not ans:
            ans = "(skipped)"
        answers.append({"question_id": qid, "answer": ans})
        print()

    status, resp = http_request("POST", f"/sessions/{sid}/quick-check",
                                 json_body={"answers": answers})
    print_result(status, resp)


# ── Takeaway (all modes) ─────────────────────────────────────────────────────

def submit_takeaway():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    text = input("Your takeaway from this reading session:\n> ").strip()
    status, resp = http_request("POST", f"/sessions/{sid}/takeaway", json_body={"text": text})
    print_result(status, resp)


# ── Other ─────────────────────────────────────────────────────────────────────

def show_progress():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, payload = http_request("GET", f"/sessions/{sid}/progress")
    print_result(status, payload)


def show_history():
    sid = STATE["session_id"]
    if not sid:
        sid = prompt_input("session_id")
    status, payload = http_request("GET", f"/sessions/{sid}/history")
    print_result(status, payload)


def show_user_memory():
    uid = prompt_input("user_id", str(STATE["user_id"] or 1))
    status, payload = http_request("GET", f"/users/{uid}/memory")
    print_result(status, payload)


def custom_request():
    method = prompt_input("HTTP method", "GET").upper()
    path = prompt_input("Path", "/health")
    send_body = prompt_input("Send JSON body? (y/n)", "n").lower() == "y"
    payload = None
    if send_body:
        raw = prompt_input("JSON body", "{}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print("\nBad JSON.\n")
            return
    status, resp = http_request(method, path, json_body=payload)
    print_result(status, resp)


def print_menu():
    mode_str = STATE["mode"] or "not set"
    print("=" * 60)
    print("  ADHD Reading Companion — Mode-Aware Demo CLI")
    print(f"  Base URL: {BASE_URL}")
    print("=" * 60)
    print("  ── Step 1: Document & Session ──")
    print("  1.  Health check")
    print("  2.  Upload document (PDF)")
    print("  3.  Create session")
    print()
    print("  ── Step 2: Session Setup ──")
    print("  4.  Session setup (3 questions → mode)")
    print()
    print("  ── Step 3: Mind Map ──")
    print("  5.  Show mind map")
    print("  6.  Jump to section")
    print()
    print("  ── Step 4: Reading Loop ──")
    print("  7.  Get current chunk")
    print("  8.  Next chunk")
    print("  9.  Skip chunk")
    print()
    print("  ── Mode-Specific Actions ──")
    print("  10. [skim] Full paper summary")
    print("  11. [skim] Self-assess (understood?)")
    print("  12. [goal] Set research goal")
    print("  13. [goal] Helpful check")
    print("  14. [deep] Submit retell")
    print("  15. [deep] Quiz (get + answer)")
    print("  16. [deep] Quick-check (legacy)")
    print()
    print("  ── Step 5: Wrap Up ──")
    print("  17. Submit takeaway")
    print("  18. Show progress")
    print("  19. Show history")
    print("  20. Show user memory")
    print("  21. Custom request")
    print("  0.  Exit")
    print("-" * 60)
    print(f"  doc={STATE['document_id']}  session={STATE['session_id']}  "
          f"user={STATE['user_id']}  mode={mode_str}")
    print()


def main():
    print()
    print("Starting Mode-Aware Demo CLI...")
    print()
    health_check()

    handlers = {
        "1": health_check,
        "2": upload_document,
        "3": create_session,
        "4": session_setup,
        "5": show_mind_map,
        "6": jump_to_section,
        "7": get_current_chunk,
        "8": next_chunk,
        "9": skip_chunk,
        "10": get_full_summary,
        "11": self_assess,
        "12": set_goal,
        "13": goal_check,
        "14": submit_retell,
        "15": get_quiz,
        "16": submit_quick_check,
        "17": submit_takeaway,
        "18": show_progress,
        "19": show_history,
        "20": show_user_memory,
        "21": custom_request,
    }

    while True:
        print_menu()
        choice = input("Choose: ").strip()
        if choice == "0":
            print("\nBye!\n")
            sys.exit(0)
        handler = handlers.get(choice)
        if not handler:
            print("\nInvalid choice.\n")
            continue
        try:
            handler()
        except KeyboardInterrupt:
            print("\nCancelled.\n")
        except Exception as e:
            print(f"\nError: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()

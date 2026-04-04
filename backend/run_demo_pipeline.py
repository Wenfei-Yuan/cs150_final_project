"""
Automated pipeline test — runs through the demo_cli.py flow non-interactively.
"""
import json
import os
import sys
import uuid
import mimetypes
from urllib import error, request

BASE_URL = os.getenv("DEMO_API_BASE", "http://localhost:8000").rstrip("/")


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
        with request.urlopen(req, timeout=120) as resp:
            return resp.status, parse_body(resp.read())
    except error.HTTPError as e:
        return e.code, parse_body(e.read())
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def encode_multipart(file_field, file_path):
    boundary = f"----Boundary{uuid.uuid4().hex}"
    chunks = []
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


def step(name, status, payload):
    ok = status and 200 <= status < 300
    mark = "OK" if ok else "FAIL"
    print(f"\n[{mark}] Step: {name} (HTTP {status})")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
    else:
        print(str(payload)[:2000])
    if not ok:
        print(f"  >>> FAILED at step '{name}'")
    return ok, payload


def main():
    pdf_path = os.path.join(os.path.dirname(__file__), "test_demo.pdf")
    if not os.path.exists(pdf_path):
        print("test_demo.pdf not found. Run make_test_pdf.py first.")
        sys.exit(1)

    user_id = "1"
    doc_id = None
    session_id = None
    mode = None

    # Step 1: Health check
    ok, payload = step("Health check", *http_request("GET", "/health"))
    if not ok:
        return

    # Step 2: Upload document
    body, headers = encode_multipart("file", pdf_path)
    ok, payload = step("Upload document", *http_request("POST", f"/documents/upload?user_id={user_id}", data=body, headers=headers))
    if not ok:
        return
    doc_id = payload.get("document_id")
    print(f"  document_id = {doc_id}")

    # Step 3: Create session
    ok, payload = step("Create session", *http_request("POST", "/sessions", json_body={"user_id": user_id, "document_id": doc_id}))
    if not ok:
        return
    session_id = payload.get("session_id")
    print(f"  session_id = {session_id}")

    # Step 4: Get setup questions
    ok, payload = step("Get setup questions", *http_request("GET", "/sessions/setup-questions"))
    if not ok:
        return

    # Step 5: Submit setup answers (choose defaults → deep comprehension mode likely)
    answers = {"reading_purpose": 0, "available_time": 2, "support_needed": 2}
    ok, payload = step("Submit setup answers", *http_request("POST", f"/sessions/{session_id}/setup", json_body=answers))
    if not ok:
        return
    mode = payload.get("recommended_mode") or payload.get("mode")
    print(f"  recommended mode = {mode}")

    # Step 6: Get mind map
    ok, payload = step("Get mind map", *http_request("GET", f"/sessions/{session_id}/mind-map"))

    # Step 7: Get current chunk
    ok, payload = step("Get current chunk", *http_request("GET", f"/sessions/{session_id}/current"))
    if not ok:
        return

    # Mode-specific actions
    if mode == "deep_comprehension":
        # Step 8: Submit retell
        ok, payload = step("Submit retell", *http_request("POST", f"/sessions/{session_id}/retell", json_body={"text": "This paper discusses ADHD and its effects on reading comprehension in students."}))

        # Step 9: Quick check
        ok, payload = step("Quick check (get questions)", *http_request("GET", f"/sessions/{session_id}/current"))
        questions = payload.get("quick_check_questions", []) if isinstance(payload, dict) else []
        if questions:
            answers_list = [{"question_id": q.get("id", f"q{i}"), "answer": "True"} for i, q in enumerate(questions, 1)]
            ok, payload = step("Submit quick check", *http_request("POST", f"/sessions/{session_id}/quick-check", json_body={"answers": answers_list}))

    elif mode == "skim":
        # Get full summary
        ok, payload = step("Full summary", *http_request("GET", f"/sessions/{session_id}/full-summary"))
        # Self assess
        ok, payload = step("Self assess", *http_request("POST", f"/sessions/{session_id}/self-assess", json_body={"understood": True}))

    elif mode == "goal_directed":
        # Set goal
        ok, payload = step("Set goal", *http_request("POST", f"/sessions/{session_id}/goal", json_body={"goal": "Understanding ADHD effects on reading"}))
        # Goal check
        ok, payload = step("Goal check", *http_request("POST", f"/sessions/{session_id}/goal-check", json_body={"helpful": True}))

    # Step: Next chunk
    ok, payload = step("Next chunk", *http_request("POST", f"/sessions/{session_id}/next", json_body={}))

    # Step: Skip chunk
    ok, payload = step("Skip chunk", *http_request("POST", f"/sessions/{session_id}/skip", json_body={}))

    # Step: Progress
    ok, payload = step("Show progress", *http_request("GET", f"/sessions/{session_id}/progress"))

    # Step: Session checkpoint
    checkpoint_label = "Submit goal-answer checkpoint" if mode == "goal_directed" else "Submit takeaway"
    checkpoint_text = (
        "Yes, I extracted the target information. The paper says ADHD can hurt reading comprehension, and active reading strategies can help."
        if mode == "goal_directed"
        else "ADHD impacts reading comprehension significantly. Active strategies help."
    )
    ok, payload = step(
        checkpoint_label,
        *http_request("POST", f"/sessions/{session_id}/takeaway", json_body={"text": checkpoint_text})
    )

    # Step: User memory
    ok, payload = step("User memory", *http_request("GET", f"/users/{user_id}/memory"))

    print("\n" + "=" * 60)
    print("  Pipeline complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

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
    if payload.get("id") is not None:
        if "chunk_count" in payload or "filename" in payload:
            STATE["document_id"] = payload["id"]
        if "document_id" in payload and ("current_chunk_id" in payload or "status" in payload):
            STATE["session_id"] = payload["id"]


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


def prompt_json(default_obj):
    default_text = json.dumps(default_obj, ensure_ascii=False)
    raw = input(f"JSON (press Enter for default)\n{default_text}\n> ").strip()
    if not raw:
        return default_obj
    return json.loads(raw)


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


def health_check():
    status, payload = http_request("GET", "/health")
    print_result(status, payload)


def upload_document():
    file_path = prompt_input("PDF path")
    if not os.path.exists(file_path):
        print("\nFile not found.\n")
        return
    field = prompt_input("Upload field name", "file")
    user_id = prompt_input("user_id", str(STATE["user_id"] or 1))
    raw_extra = prompt_input("Extra form fields JSON", "{}")
    try:
        extra = json.loads(raw_extra) if raw_extra else {}
    except json.JSONDecodeError:
        print("\nBad JSON.\n")
        return
    body, headers = encode_multipart(field, file_path, extra)
    status, payload = http_request("POST", f"/documents/upload?user_id={user_id}", data=body, headers=headers)
    print_result(status, payload)


def get_document():
    did = prompt_input("document_id", str(STATE["document_id"]) if STATE["document_id"] else "")
    if not did:
        print("\nMissing document_id.\n")
        return
    status, payload = http_request("GET", f"/documents/{did}")
    print_result(status, payload)


def create_session():
    default_payload = {
        "user_id": str(STATE["user_id"] or "1"),
        "document_id": str(STATE["document_id"] or ""),
    }
    try:
        payload = prompt_json(default_payload)
    except json.JSONDecodeError:
        print("\nBad JSON.\n")
        return
    status, resp = http_request("POST", "/sessions", json_body=payload)
    print_result(status, resp)


def get_current_chunk():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    status, payload = http_request("GET", f"/sessions/{sid}/current")
    print_result(status, payload)


def submit_retell():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    raw = input("Enter your retell (plain text or JSON):\n> ").strip()
    if not raw:
        raw = "This chunk mainly discusses the core argument, method, and findings."
        print(f"(using default: {raw})")
    # If it looks like JSON, parse it; otherwise wrap plain text
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print("\nBad JSON.\n")
            return
    else:
        payload = {"text": raw}
    status, resp = http_request("POST", f"/sessions/{sid}/retell", json_body=payload)
    print_result(status, resp)


def submit_quick_check():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    try:
        payload = prompt_json({
            "answers": [{"question_id": 1, "answer": "example answer"}]
        })
    except json.JSONDecodeError:
        print("\nBad JSON.\n")
        return
    status, resp = http_request("POST", f"/sessions/{sid}/quick-check", json_body=payload)
    print_result(status, resp)


def next_chunk():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    raw = prompt_input("Optional JSON body", "{}")
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        print("\nBad JSON.\n")
        return
    status, resp = http_request("POST", f"/sessions/{sid}/next", json_body=payload)
    print_result(status, resp)


def show_progress():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    status, payload = http_request("GET", f"/sessions/{sid}/progress")
    print_result(status, payload)


def show_history():
    sid = prompt_input("session_id", str(STATE["session_id"]) if STATE["session_id"] else "")
    if not sid:
        print("\nMissing session_id.\n")
        return
    status, payload = http_request("GET", f"/sessions/{sid}/history")
    print_result(status, payload)


def show_user_memory():
    uid = prompt_input("user_id", str(STATE["user_id"] or 1))
    if not uid:
        print("\nMissing user_id.\n")
        return
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
    print("=" * 50)
    print("  ADHD Reading Companion — Demo CLI")
    print(f"  Base URL: {BASE_URL}")
    print("=" * 50)
    print("  1.  Health check")
    print("  2.  Upload document (PDF)")
    print("  3.  Get document info")
    print("  4.  Create session")
    print("  5.  Get current chunk")
    print("  6.  Submit retell")
    print("  7.  Submit quick-check")
    print("  8.  Next chunk")
    print("  9.  Show progress")
    print("  10. Show history")
    print("  11. Show user memory")
    print("  12. Custom request")
    print("  0.  Exit")
    print("-" * 50)
    print(f"  Cached: doc={STATE['document_id']}  session={STATE['session_id']}  user={STATE['user_id']}")
    print()


def main():
    print()
    print("Starting Demo CLI...")
    print()
    health_check()

    handlers = {
        "1": health_check,
        "2": upload_document,
        "3": get_document,
        "4": create_session,
        "5": get_current_chunk,
        "6": submit_retell,
        "7": submit_quick_check,
        "8": next_chunk,
        "9": show_progress,
        "10": show_history,
        "11": show_user_memory,
        "12": custom_request,
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

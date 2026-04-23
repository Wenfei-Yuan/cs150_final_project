"""
ADHD Reading Companion — Demo CLI

3-stage flow (mirrors app/main.py):
  Stage 1: Upload a PDF or Markdown file        POST /documents/upload
  Stage 2: Enter your name (creates a session)  POST /sessions
  Stage 3: ADHD Progressive Reading             GET  /adhd/chunks/{doc_id}
                                                POST /adhd/annotate
           - Navigate chunk by chunk with [n]ext page
           - Reveal paragraph by paragraph with [r]ead more
           - Each reveal re-annotates all visible text (highlight / fade / normal)
           - [e] Explain — paste any passage for inline AI explanation
                           POST /explain/selection

Colour key:
  Bold yellow  = highlight  (core argument / key definition)
  Dim grey     = fade       (minor detail / aside)
  Normal       = normal     (regular explanatory text)
"""
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from urllib import error, request

BASE_URL = os.getenv("DEMO_API_BASE", "http://localhost:8000").rstrip("/")

# ── Shared CLI state ──────────────────────────────────────────────────────────

STATE = {
    "document_id": None,
    "session_id": None,
    "user_id": "user_1",
    "user_name": None,
}

# ── Terminal colour helpers ───────────────────────────────────────────────────

_USE_COLOUR = sys.stdout.isatty() and os.name != "nt"


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def red(t):         return _c("31",   t)
def green(t):       return _c("32",   t)
def yellow(t):      return _c("33",   t)
def cyan(t):        return _c("36",   t)
def bold(t):        return _c("1",    t)
def dim(t):         return _c("2",    t)
def hl(t):          return _c("1;33", t)   # bold yellow — highlight label


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


def ok(msg):    print(green(f"  ✓ {msg}"))
def err(msg):   print(red(f"  ✗ {msg}"))
def info(msg):  print(cyan(f"  → {msg}"))
def warn(msg):  print(yellow(f"  ! {msg}"))


def die(msg):
    err(msg)
    sys.exit(1)


def require_ok(status, payload, ctx=""):
    if status and 200 <= status < 300:
        return payload
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    die(f"{ctx} failed (HTTP {status}): {detail}")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


# ── Sentence splitting (must match backend regex) ─────────────────────────────

_SENT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"(])')


def split_sentences(text):
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


# ── Annotation renderer ────────────────────────────────────────────────────────

_LABEL_LEGEND = (
    f"  Legend:  {hl('■ highlight')}  "
    f"{dim('■ fade')}  "
    "■ normal"
)


def _wrap(text, width=76, indent="  "):
    """Simple word-wrap."""
    words = text.split()
    line = indent
    lines = []
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = indent + word
        else:
            line += (" " if line.strip() else "") + word
    if line.strip():
        lines.append(line)
    return "\n".join(lines)


def render_annotations(annotations):
    """Print sentences coloured by their annotation label."""
    for ann in annotations:
        text = ann["text"]
        label = ann["label"]
        wrapped = _wrap(text)
        if label == "highlight":
            print(hl(wrapped))
        elif label == "fade":
            print(dim(wrapped))
        else:
            print(wrapped)
    print()


# ── Stage 1: Upload document ──────────────────────────────────────────────────

def stage1_upload():
    section("Stage 1 — Upload Document")
    file_path = prompt("Path to PDF or Markdown file")
    if not os.path.exists(file_path):
        die(f"File not found: {file_path}")

    info("Uploading document…")
    body, headers = encode_multipart("file", file_path)
    status, payload = http_request(
        "POST", f"/documents/upload?user_id={STATE['user_id']}",
        data=body, headers=headers,
    )
    require_ok(status, payload, "Upload")

    STATE["document_id"] = payload["document_id"]
    ok(f"Uploaded: {payload['filename']}")
    ok(f"Document ID: {STATE['document_id']}")

    # Poll until the document is indexed (chunked + vectorised)
    info("Waiting for document to be processed (chunking + indexing)…")
    for attempt in range(60):
        time.sleep(3)
        s, p = http_request("GET", f"/documents/{STATE['document_id']}")
        if s == 200 and isinstance(p, dict):
            doc_status = p.get("status", "")
            if doc_status == "indexed":
                ok("Document indexed and ready.")
                break
            info(f"  Status: {doc_status} (attempt {attempt + 1}/60)…")
        else:
            warn(f"  Status check failed (attempt {attempt + 1}); retrying…")
    else:
        warn("Document did not finish indexing in time — proceeding anyway.")

    info("Press Enter to continue to Stage 2.")
    input()


# ── Stage 2: Enter username → create session ──────────────────────────────────

def stage2_session():
    section("Stage 2 — Enter Your Name")
    name = prompt("Your name (used to identify your session)")
    if not name:
        die("Name cannot be empty.")

    user_id = name.strip().lower().replace(" ", "_")
    STATE["user_name"] = name
    STATE["user_id"] = user_id

    if not STATE["document_id"]:
        STATE["document_id"] = prompt("Document ID (from Stage 1)")

    info("Creating reading session…")
    status, payload = http_request(
        "POST", "/sessions",
        json_body={"user_id": user_id, "document_id": STATE["document_id"]},
    )
    require_ok(status, payload, "Create session")

    STATE["session_id"] = str(payload["session_id"])
    ok(f"Session created: {STATE['session_id']}")
    ok(f"Hello, {name}! Let's start reading.")
    info("Press Enter to continue to Stage 3 (ADHD Reader).")
    input()


# ── Stage 3: ADHD Progressive Reader ─────────────────────────────────────────

def _annotate(visible_blocks):
    """Call /adhd/annotate and return list of {text, label} dicts, or None on error."""
    status, payload = http_request(
        "POST", "/adhd/annotate",
        json_body={
            "document_id": STATE["document_id"],
            "visible_blocks": visible_blocks,
        },
    )
    if status and 200 <= status < 300:
        return payload.get("annotations", [])
    return None


def _print_reader_screen(chunk_idx, total_chunks, section_name, visible_blocks, annotations):
    """Clear screen and render the current page with annotations."""
    clear_screen()
    print()
    print(bold("=" * 60))
    print(bold(f"  ADHD Reader  —  Page {chunk_idx + 1} / {total_chunks}"))
    if section_name:
        print(bold(f"  Section: {section_name}"))
    print(bold("=" * 60))
    print(_LABEL_LEGEND)
    print()
    print(bold("  " + "─" * 56))

    if annotations:
        render_annotations(annotations)
    else:
        # Fallback: plain text if annotation call failed
        for block in visible_blocks:
            print(_wrap(block))
            print()

    print(bold("  " + "─" * 56))


def _explain_text(selected_text, surrounding_text=""):
    """Call POST /explain/selection and return the explanation string, or None on error."""
    status, payload = http_request(
        "POST", "/explain/selection",
        json_body={
            "document_id": STATE["document_id"],
            "selected_text": selected_text,
            "surrounding_text": surrounding_text,
        },
    )
    if status and 200 <= status < 300:
        return payload.get("explanation")
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    return None, detail


def stage3_adhd_read():
    section("Stage 3 — ADHD Progressive Reader")

    if not STATE["document_id"]:
        STATE["document_id"] = prompt("Document ID (from Stage 1)")

    info("Fetching document chunks…")
    status, payload = http_request("GET", f"/adhd/chunks/{STATE['document_id']}")
    require_ok(status, payload, "Fetch chunks")

    chunks = payload["chunks"]
    total_chunks = payload["total_chunks"]

    if not chunks:
        err("No chunks found for this document.")
        return

    chunk_idx = 0

    while chunk_idx < len(chunks):
        chunk = chunks[chunk_idx]
        paragraphs = chunk["paragraphs"]
        section_name = chunk.get("section") or ""
        visible_count = 1  # start with one paragraph visible

        while True:
            visible_blocks = paragraphs[:visible_count]

            # Annotate (shows spinner hint before clearing screen)
            info("Annotating…")
            annotations = _annotate(visible_blocks)

            _print_reader_screen(chunk_idx, total_chunks, section_name, visible_blocks, annotations)

            has_more_paras = visible_count < len(paragraphs)
            has_next_chunk = chunk_idx + 1 < len(chunks)
            at_last_para   = not has_more_paras
            is_last_content = at_last_para and not has_next_chunk

            # Build command hint
            cmds = []
            if has_more_paras:
                cmds.append(cyan("[r] Read More"))
            if not is_last_content:
                # Next Page continues unread paragraphs first, then advances chunk
                cmds.append(cyan("[n] Next Page"))
            cmds.append(cyan("[e] Explain"))
            cmds.append(cyan("[q] Quit"))

            print("  " + "  |  ".join(cmds))
            cmd = input(bold("  > ")).strip().lower()

            if cmd == "e":
                print()
                print(bold("  Explain a passage"))
                print(dim("  Type or paste the text you want explained (press Enter twice to confirm):"))
                lines = []
                while True:
                    line = input()
                    if line == "" and lines:
                        break
                    lines.append(line)
                selected = " ".join(lines).strip()
                if not selected:
                    warn("No text entered — cancelling.")
                    continue
                # Build surrounding context from currently visible blocks
                surrounding = "\n".join(visible_blocks)
                info("Asking AI for an explanation…")
                result = _explain_text(selected, surrounding)
                print()
                if isinstance(result, tuple):
                    err(f"Explain failed: {result[1]}")
                elif result:
                    print(bold("  ─── Explanation ───────────────────────────────────"))
                    print(_wrap(result, width=76, indent="  "))
                    print(bold("  ────────────────────────────────────────────────────"))
                else:
                    warn("No explanation returned.")
                print()
                input(dim("  Press Enter to continue reading…"))
                continue

            if cmd in ("r", "") and has_more_paras:
                visible_count += 1
                continue

            if cmd == "n":
                if has_more_paras:
                    # Don't skip unread paragraphs — continue in current chunk
                    visible_count += 1
                    continue
                elif has_next_chunk:
                    # All paragraphs read, advance to next chunk
                    chunk_idx += 1
                    break
                else:
                    warn("You have finished reading the document!")
                    ok("Thanks for reading! Goodbye.")
                    return

            if cmd == "r" and not has_more_paras:
                # User pressed r but all paragraphs shown — act as next page
                if has_next_chunk:
                    chunk_idx += 1
                    break
                else:
                    warn("You have finished reading the document!")
                    ok("Thanks for reading! Goodbye.")
                    return

            if cmd == "q":
                print()
                ok("Reading session ended. Goodbye!")
                return

            warn("Invalid command. Use [r], [n], or [q].")

        # Reached when chunk advances via "n"
        if chunk_idx >= len(chunks):
            break

    # Finished all chunks
    clear_screen()
    section("You have finished the document!")
    ok(f"Document: {STATE['document_id']}")
    ok(f"Session:  {STATE['session_id']}")
    ok("Thanks for reading!")


# ── Main menu ─────────────────────────────────────────────────────────────────

def print_menu():
    doc = (STATE["document_id"] or "—")[:36]
    ses = (STATE["session_id"] or "—")[:36]
    usr = STATE["user_name"] or STATE["user_id"]
    print()
    print(bold("=" * 60))
    print(bold("  ADHD Reading Companion — Demo CLI"))
    print(bold(f"  {BASE_URL}"))
    print(bold("=" * 60))
    print(f"  doc={doc}  session={ses}  user={usr}")
    print()
    print("  ── Guided Flow ──────────────────────────────────────────")
    print("  1.  Stage 1 — Upload document")
    print("  2.  Stage 2 — Enter name / create session")
    print("  3.  Stage 3 — ADHD progressive reader")
    print()
    print("  ── Shortcut ─────────────────────────────────────────────")
    print("  4.  Run full flow (stages 1 → 3)")
    print("  0.  Exit")
    print(bold("-" * 60))


def run_full_flow():
    stage1_upload()
    stage2_session()
    stage3_adhd_read()


def main():
    status, _ = http_request("GET", "/health")
    if status != 200:
        die(
            f"Backend not reachable at {BASE_URL}.\n"
            "  Start with:  uvicorn app.main:app --host 0.0.0.0 --port 8000\n"
            f"  Or set:      DEMO_API_BASE=http://... python demo_cli.py"
        )

    print()
    print(bold("  ADHD Reading Companion — Demo CLI ready."))
    print(bold(f"  Connected to: {BASE_URL}"))
    print()

    handlers = {
        "1": stage1_upload,
        "2": stage2_session,
        "3": stage3_adhd_read,
        "4": run_full_flow,
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

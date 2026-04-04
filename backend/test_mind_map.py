"""
Direct test script for Step 3: Mind Map — Show mind map (menu option 5).

Runs the full prerequisite pipeline automatically (upload → session → setup)
then calls GET /sessions/{session_id}/mind-map and pretty-prints the result.

Usage:
    # From the backend/ directory:
    python test_mind_map.py

    # Optional: use a custom PDF or a different API base
    python test_mind_map.py --pdf path/to/paper.pdf
    DEMO_API_BASE=http://localhost:8000 python test_mind_map.py
"""
import json
import mimetypes
import os
import sys
import uuid
from urllib import error, request

BASE_URL = os.getenv("DEMO_API_BASE", "http://localhost:8000").rstrip("/")

# Default test PDF written alongside this script
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PDF = os.path.join(_HERE, "test.pdf")

# ── Minimal multi-section academic PDF ────────────────────────────────────────

_PDF_BYTES = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 1482 >>
stream
BT
/F1 16 Tf
72 750 Td
(ADHD and Reading Comprehension: A Research Overview) Tj
/F1 13 Tf
0 -36 Td
(Abstract) Tj
/F1 11 Tf
0 -20 Td
(Attention deficit hyperactivity disorder affects academic reading significantly.) Tj
0 -16 Td
(Students with ADHD often struggle with sustained focus during long texts.) Tj
0 -16 Td
(This paper reviews current research and proposes structured reading strategies.) Tj
/F1 13 Tf
0 -36 Td
(1. Introduction) Tj
/F1 11 Tf
0 -20 Td
(Reading comprehension is a foundational academic skill. ADHD impairs the) Tj
0 -16 Td
(executive functions needed for sustained attention and working memory.) Tj
0 -16 Td
(Interventions that break text into structured chunks show measurable gains.) Tj
/F1 13 Tf
0 -36 Td
(2. Background) Tj
/F1 11 Tf
0 -20 Td
(ADHD affects approximately 5 to 10 percent of school-age children.) Tj
0 -16 Td
(Core symptoms include inattention, hyperactivity, and impulsivity.) Tj
0 -16 Td
(These symptoms interact with reading demands in complex ways.) Tj
/F1 13 Tf
0 -36 Td
(3. Methods) Tj
/F1 11 Tf
0 -20 Td
(We reviewed 42 peer-reviewed studies published between 2010 and 2024.) Tj
0 -16 Td
(Studies were included if they measured reading outcomes in ADHD populations.) Tj
0 -16 Td
(Meta-analytic techniques were applied to synthesize effect sizes.) Tj
/F1 13 Tf
0 -36 Td
(4. Results) Tj
/F1 11 Tf
0 -20 Td
(Chunked reading interventions showed a mean effect size of d=0.62.) Tj
0 -16 Td
(Active recall techniques added an additional d=0.31 improvement.) Tj
0 -16 Td
(Combined approaches outperformed either intervention alone.) Tj
/F1 13 Tf
0 -36 Td
(5. Discussion) Tj
/F1 11 Tf
0 -20 Td
(Structured reading scaffolds address the working memory bottleneck in ADHD.) Tj
0 -16 Td
(Immediate feedback loops help students self-regulate during reading tasks.) Tj
0 -16 Td
(Future work should examine digital delivery mechanisms for these strategies.) Tj
/F1 13 Tf
0 -36 Td
(6. Conclusion) Tj
/F1 11 Tf
0 -20 Td
(This review confirms that structured, chunked reading with active recall) Tj
0 -16 Td
(significantly improves comprehension outcomes for students with ADHD.) Tj
0 -16 Td
(Practical implementation guidelines are provided for educators.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000267 00000 n 
0000001801 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
1878
%%EOF
"""


def ensure_test_pdf(path):
    """Write the bundled test PDF to *path* if it does not already exist."""
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(_PDF_BYTES)
        print(f"[INFO] Created default test PDF: {path}")
    else:
        print(f"[INFO] Using existing PDF: {path}")


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def parse_body(raw):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def http(method, path, json_body=None, data=None, headers=None):
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
    except (error.URLError, TimeoutError, ConnectionError) as e:
        return None, f"ConnectionError: {e}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def encode_multipart(file_path):
    boundary = f"----Boundary{uuid.uuid4().hex}"
    filename = os.path.basename(file_path)
    ctype = mimetypes.guess_type(filename)[0] or "application/pdf"
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    body = (
        f"--{boundary}\r\n".encode()
        + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
        + f"Content-Type: {ctype}\r\n\r\n".encode()
        + file_bytes
        + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return body, headers


def step(label, status, payload):
    ok = status is not None and 200 <= status < 300
    tag = "OK  " if ok else "FAIL"
    print(f"\n[{tag}] {label}  (HTTP {status})")
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:3000])
    else:
        print(str(payload)[:3000])
    if not ok:
        print(f"     ^^^ step '{label}' failed — aborting.")
        sys.exit(1)
    return payload


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run(pdf_path):
    print("=" * 60)
    print("  Mind Map Direct Test")
    print(f"  API: {BASE_URL}")
    print(f"  PDF: {pdf_path}")
    print("=" * 60)

    # 1. Health check
    step("Health check", *http("GET", "/health"))

    # 2. Upload document
    body, headers = encode_multipart(pdf_path)
    payload = step("Upload document", *http("POST", "/documents/upload?user_id=1", data=body, headers=headers))
    doc_id = payload.get("document_id")
    print(f"  document_id = {doc_id}")

    # 3. Create session
    payload = step("Create session", *http("POST", "/sessions", json_body={"user_id": "1", "document_id": doc_id}))
    session_id = payload.get("session_id")
    print(f"  session_id  = {session_id}")

    # 4. Session setup (required before mind map is accessible)
    step("Get setup questions", *http("GET", "/sessions/setup-questions"))
    answers = {"reading_purpose": 0, "available_time": 2, "support_needed": 2}
    payload = step("Submit setup answers", *http("POST", f"/sessions/{session_id}/setup", json_body=answers))
    mode = payload.get("recommended_mode") or payload.get("mode", "unknown")
    print(f"  recommended_mode = {mode}")

    # 5. ── Step 3: Mind Map — Show mind map ──────────────────────────────────
    print("\n" + "=" * 60)
    print("  STEP 3: MIND MAP")
    print("=" * 60)
    payload = step("GET /sessions/{session_id}/mind-map", *http("GET", f"/sessions/{session_id}/mind-map"))

    # Render a human-readable tree
    sections = payload.get("sections", []) if isinstance(payload, dict) else []
    if sections:
        print("\n  ── Document Mind Map ──")
        for s in sections:
            idx = s.get("section_index", "?")
            stype = s.get("section_type", "?")
            title = s.get("title", "(no title)")
            summary = s.get("summary", "")
            key_terms = s.get("key_terms") or []
            chunk_range = s.get("chunk_indices") or s.get("chunk_range") or []

            print(f"\n  [{idx}] {stype.upper()}: {title}")
            if summary:
                # wrap at ~80 chars for readability
                words = summary.split()
                line, lines = [], []
                for w in words:
                    if sum(len(x) + 1 for x in line) + len(w) > 78:
                        lines.append("       " + " ".join(line))
                        line = [w]
                    else:
                        line.append(w)
                if line:
                    lines.append("       " + " ".join(line))
                print("       Summary:")
                print("\n".join(lines))
            if key_terms:
                print(f"       Key terms: {', '.join(key_terms)}")
            if chunk_range:
                print(f"       Chunks: {chunk_range}")

        print(f"\n  Total sections: {len(sections)}")
    else:
        print("\n  (No sections returned — the mind map response had no 'sections' key.)")

    print("\n" + "=" * 60)
    print("  Mind Map test complete.")
    print("=" * 60)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Allow passing a custom PDF as the first positional argument
    if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help"):
        pdf_path = sys.argv[1]
        if not os.path.exists(pdf_path):
            print(f"Error: PDF not found: {pdf_path}")
            sys.exit(1)
    else:
        pdf_path = DEFAULT_PDF
        ensure_test_pdf(pdf_path)

    run(pdf_path)

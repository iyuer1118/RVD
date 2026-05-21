#!/usr/bin/env python3
"""Deep Read Tool - Trigger or retrieve a deep-read report for a document"""
import sys, json, os, requests, os, time

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:10663")
DEEP_READS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deep_reads")
POLL_INTERVAL = 5      # seconds between status polls
MAX_WAIT = 600          # 10 minutes max wait

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    source = args.get("source", "")
    kb = args.get("kb", "RVD")
    token = args.get("token") or os.environ.get("RAG_TOKEN") or os.environ.get("RAG_AUTH_CODE", "change-me")

    if not source:
        print(json.dumps({"error": "source is required"}))
        sys.exit(1)

    # report_id = source.split("_")[0]  e.g. "068_Code is not..." -> "068"
    report_id = source.split("_")[0]
    report_md = os.path.join(DEEP_READS_DIR, f"{report_id}.md")
    report_json = os.path.join(DEEP_READS_DIR, f"{report_id}.json")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Check local file first
    if os.path.isfile(report_md):
        try:
            with open(report_md, "r", encoding="utf-8") as f:
                content = f.read()
            metadata = {}
            if os.path.isfile(report_json):
                with open(report_json, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            output = {
                "status": "done",
                "report_id": report_id,
                "source": "local_cache",
                "content": content,
                "metadata": metadata
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return
        except Exception:
            pass  # fall through to API

    # 2. Trigger deep-read via API
    try:
        resp = requests.post(f"{API_BASE}/api/deep-read",
            json={"source": source, "kb": kb},
            headers=headers,
            timeout=30)
        data = resp.json()
        status = data.get("status", "")
        rid = data.get("report_id", report_id)

        if status == "done":
            # Already done, fetch the full report
            report = _fetch_report(rid, headers)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

        if status in ("started", "running"):
            # Poll until done
            result = _poll_until_done(rid, headers)
            if result.get("status") == "done":
                report = _fetch_report(rid, headers)
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        # Unexpected status — return as-is
        print(json.dumps(data, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def _fetch_report(report_id, headers):
    """GET /api/deep-read/{id} to retrieve the completed report."""
    resp = requests.get(f"{API_BASE}/api/deep-read/{report_id}",
        headers=headers, timeout=60)
    data = resp.json()
    return {
        "status": data.get("status", "done"),
        "report_id": report_id,
        "source": "api",
        "content": data.get("content", ""),
        "metadata": data.get("metadata", {})
    }


def _poll_until_done(report_id, headers):
    """Poll /api/deep-read/{id}/status until done or timeout."""
    elapsed = 0
    while elapsed < MAX_WAIT:
        try:
            resp = requests.get(f"{API_BASE}/api/deep-read/{report_id}/status",
                headers=headers, timeout=15)
            data = resp.json()
            status = data.get("status", "")
            if status == "done":
                return {"status": "done", "report_id": report_id}
            if status in ("failed", "error"):
                return {"status": "error", "report_id": report_id,
                        "message": data.get("message", "unknown error"),
                        "phase": data.get("phase", ""),
                        "progress": data.get("progress", 0)}
            # Still running — report progress
            phase = data.get("phase", "")
            progress = data.get("progress", 0)
            # Print progress to stderr so stdout stays clean
            print(f"[deep-read] {report_id}: phase={phase} progress={progress}%",
                  file=sys.stderr)
        except Exception as e:
            print(f"[deep-read] poll error: {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return {"status": "timeout", "report_id": report_id,
            "message": f"deep-read did not finish within {MAX_WAIT}s"}


if __name__ == "__main__":
    main()

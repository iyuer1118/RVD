#!/usr/bin/env python3
"""Get document detail (title, authors, summary, keywords)"""
import sys, json, os, requests

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:10663")

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    kb = args.get("kb", "RVD")
    source = args.get("source", "")
    token = args.get("token") or os.environ.get("RAG_TOKEN") or os.environ.get("RAG_AUTH_CODE", "change-me")
    
    if not source:
        print(json.dumps({"error": "source is required"}))
        sys.exit(1)
    
    try:
        resp = requests.get(f"{API_BASE}/api/kb-document-detail",
            params={"kb": kb, "source": source},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120)
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()

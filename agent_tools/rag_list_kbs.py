#!/usr/bin/env python3
"""List all knowledge bases"""
import sys, json, os, requests

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:10663")

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    token = args.get("token") or os.environ.get("RAG_TOKEN") or os.environ.get("RAG_AUTH_CODE", "change-me")
    try:
        resp = requests.get(f"{API_BASE}/api/knowledge-bases",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10)
        data = resp.json()
        kbs = data.get("knowledge_bases", [])
        output = [{"name": kb.get("name",""), "segments": kb.get("segments",0), "description": kb.get("description","")} for kb in kbs]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()

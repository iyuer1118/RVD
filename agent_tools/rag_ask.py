#!/usr/bin/env python3
"""RAG Knowledge Base Q&A Tool - Retrieval + LLM generation"""
import sys, json, os, requests

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:10663")

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    query = args.get("query", "")
    kb = args.get("kb", os.environ.get("RAG_KB_NAME", "papers"))
    top_k = args.get("top_k", 8)
    
    if not query:
        print(json.dumps({"error": "query is required"}))
        sys.exit(1)
    
    token = args.get("token") or os.environ.get("RAG_TOKEN") or os.environ.get("RAG_AUTH_CODE", "change-me")
    try:
        resp = requests.post(f"{API_BASE}/api/ask",
            json={"query": query, "kb": kb, "top_k": top_k, "temperature": 0.3, "max_tokens": 2048, "return_sources": True},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=120)
        data = resp.json()
        output = {
            "answer": data.get("answer", ""),
            "query": data.get("query", query),
            "rewritten_query": data.get("rewritten_query", ""),
            "sources": data.get("sources", []),
            "unique_sources": data.get("unique_sources", [])
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()

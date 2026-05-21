#!/usr/bin/env python3
"""RAG Knowledge Base Search Tool - Pure retrieval (no LLM)"""
import sys, json, os, requests

API_BASE = os.environ.get("RAG_API_BASE", "http://localhost:10663")

def main():
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    query = args.get("query", "")
    kb = args.get("kb", os.environ.get("RAG_KB_NAME", "papers"))
    top_k = args.get("top_k", 10)
    min_score = args.get("min_score", 0.1)
    
    if not query:
        print(json.dumps({"error": "query is required"}))
        sys.exit(1)
    
    token = args.get("token") or os.environ.get("RAG_TOKEN") or os.environ.get("RAG_AUTH_CODE", "change-me")
    try:
        resp = requests.post(f"{API_BASE}/api/search", 
            json={"query": query, "kb": kb, "top_k": top_k, "min_score": min_score, "return_text": True, "text_max_len": 1000},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30)
        data = resp.json()
        results = data.get("results", [])
        output = {
            "query": data.get("query", query),
            "rewritten_query": data.get("rewritten_query", ""),
            "total": len(results),
            "results": [{"score": r.get("score", 0), "source": r.get("source", ""), "text": r.get("text", "")[:500]} for r in results],
            "sources": data.get("sources", [])
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()

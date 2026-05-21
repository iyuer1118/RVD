#!/usr/bin/env python3
"""
Keyword Recalibration Script v2
Uses DeepSeek API for keyword classification.
"""

import json
import os
import sys
import time
import requests
import argparse

# === Config ===
BASE_DIR = os.path.abspath(os.getenv("RAG_BASE_DIR", os.path.dirname(os.path.dirname(__file__))))
KB_NAME = os.getenv("RAG_KB_NAME", "RVD")
CACHE_PATH = os.getenv("RAG_DOC_DETAILS_CACHE", os.path.join(BASE_DIR, "knowledge_bases", KB_NAME, "doc_details_cache.json"))
PROGRESS_FILE = os.getenv("RAG_KEYWORD_PROGRESS", os.path.join(BASE_DIR, "knowledge_bases", KB_NAME, "keyword_recalibration_progress.json"))

# Fixed taxonomy
TAXONOMY = [
    "Binary Code Similarity Detection",
    "Cross-Platform Binary Analysis",
    "Binary Function Matching",
    "Code Clone Detection",
    "Code Search & Retrieval",
    "Vulnerability Detection",
    "Recurring Vulnerability Detection",
    "Vulnerability Verification",
    "Patch Analysis",
    "CVE & Exploit Analysis",
    "Static Analysis",
    "Dynamic Analysis",
    "Symbolic Execution",
    "Program Slicing",
    "Control Flow Analysis",
    "Data Flow Analysis",
    "Abstract Interpretation",
    "Deep Learning",
    "Graph Neural Network",
    "Large Language Model",
    "Representation Learning",
    "Natural Language Processing",
    "Malware Detection & Analysis",
    "Software Security",
    "IoT & Firmware Security",
    "Obfuscation & Deobfuscation",
    "Android Security",
    "Empirical Study & Benchmark",
    "Software Maintenance & Evolution",
    "Network Security",
    "Control Systems & Optimization",
    "Other",
]

TAXONOMY_STR = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(TAXONOMY))

SYSTEM_PROMPT = f"""You are a research paper classification assistant. Given a paper's summary, assign 2-5 most relevant keywords from the taxonomy below. You MUST only use keywords from this list - do not invent new ones.

Taxonomy:
{TAXONOMY_STR}

Rules:
- Pick 2-5 keywords, ordered by relevance (most relevant first)
- Only use keywords from the taxonomy above
- If the paper doesn't fit well, use "Other" as the last resort
- Respond with ONLY the keyword names, one per line, no numbering, no explanation
- Keep the exact spelling from the taxonomy"""


def call_deepseek(prompt: str, api_key: str, base_url: str = "https://api.deepseek.com/v1", model: str = "deepseek-chat", max_retries=3) -> str:
    """Call DeepSeek API."""
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 200,
    }
    
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  API attempt {attempt+1}/{max_retries} failed: {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(3)
    return ""


def call_ollama(prompt: str, model: str = "mistral-nemo", max_retries=3) -> str:
    """Fallback: call local Ollama."""
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
    for attempt in range(max_retries):
        try:
            resp = requests.post("http://localhost:11434/api/generate", json={
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 200}
            }, timeout=120)
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except Exception as e:
            print(f"  Ollama attempt {attempt+1}/{max_retries} failed: {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(5)
    return ""


def parse_keywords(response: str) -> list:
    """Parse LLM response into keyword list, validating against taxonomy."""
    taxonomy_lower = {t.lower(): t for t in TAXONOMY}
    keywords = []
    for line in response.split("\n"):
        line = line.strip().rstrip(",")
        if not line:
            continue
        line = line.lstrip("0123456789.-) ")
        matched = taxonomy_lower.get(line.lower())
        if matched and matched not in keywords:
            keywords.append(matched)
    return keywords


def main():
    parser = argparse.ArgumentParser(description="Keyword Recalibration")
    parser.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY", ""), help="DeepSeek API key")
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1", help="API base URL")
    parser.add_argument("--model", default="deepseek-chat", help="Model name")
    parser.add_argument("--use-ollama", action="store_true", help="Use local Ollama instead")
    parser.add_argument("--start-from", type=int, default=0, help="Start from index")
    args = parser.parse_args()

    # Load cache
    with open(CACHE_PATH, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    # Load progress
    progress = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            progress = json.load(f)
        print(f"Resuming: {len(progress)} already done", file=sys.stderr)

    items = list(cache.items())
    total = len(items)
    updated = 0
    errors = 0

    for idx, (key, detail) in enumerate(items):
        if idx < args.start_from:
            continue
        source = key.split("::", 1)[-1] if "::" in key else key
        short_source = source[:65]

        if key in progress:
            continue

        summary = detail.get("summary_zh", "") or detail.get("summary", "")
        title = detail.get("title_zh", "") or detail.get("title", "")
        if not summary:
            print(f"[{idx+1}/{total}] SKIP (no summary): {short_source}", file=sys.stderr)
            progress[key] = {"status": "skipped", "keywords": []}
            continue

        prompt = f"Paper title: {title}\nPaper summary: {summary}\n\nKeywords:"

        print(f"[{idx+1}/{total}] {short_source}...", end=" ", flush=True)
        start = time.time()

        if args.use_ollama:
            response = call_ollama(prompt)
        else:
            response = call_deepseek(prompt, args.api_key, args.base_url, args.model)

        keywords = parse_keywords(response)
        elapsed = time.time() - start

        if keywords:
            detail["keywords"] = keywords
            print(f"✅ [{elapsed:.1f}s] {keywords}")
            updated += 1
            progress[key] = {"status": "done", "keywords": keywords}
        else:
            print(f"⚠️ [{elapsed:.1f}s] empty response, keeping old: {detail.get('keywords', [])[:3]}")
            errors += 1
            progress[key] = {"status": "fallback", "keywords": detail.get("keywords", [])}

        # Save every 10
        if (idx + 1) % 10 == 0 or idx == total - 1:
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
            print(f"  → Saved ({len(progress)}/{total})", file=sys.stderr)

    # Final save
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # Stats
    tag_counts = {}
    for detail in cache.values():
        for kw in detail.get("keywords", []):
            tag_counts[kw] = tag_counts.get(kw, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    print(f"\n{'='*60}")
    print(f"Done! Updated: {updated}, Errors: {errors}, Total: {total}")
    print(f"Unique tags: {len(sorted_tags)}")
    print(f"\nFinal distribution:")
    for name, count in sorted_tags:
        print(f"  {count:3d}  {name}")

    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


if __name__ == "__main__":
    main()

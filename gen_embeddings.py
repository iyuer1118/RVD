#!/usr/bin/env python3
"""为重建的segments生成bge-m3嵌入"""
import json, os, requests, sys, time

BASE_DIR = os.path.abspath(os.getenv("RAG_BASE_DIR", os.path.dirname(__file__)))
KB_NAME = os.getenv("RAG_KB_NAME", "RVD")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
segments_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "knowledge_bases", KB_NAME, "segments.json")
embeddings_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE_DIR, "knowledge_bases", KB_NAME, "embeddings.json")
BATCH_SIZE = 10

# 加载segments
segments = []
with open(segments_file, 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            segments.append(json.loads(line))

print(f"共 {len(segments)} 个段落需要嵌入")

# 生成嵌入
embeddings = []
for i in range(0, len(segments), BATCH_SIZE):
    batch = [s['text'] for s in segments[i:i+BATCH_SIZE]]
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/embed", json={"model": MODEL, "input": batch}, timeout=120)
        if resp.status_code == 200:
            for emb in resp.json()['embeddings']:
                embeddings.append(emb)
            print(f"  {i+len(batch)}/{len(segments)} done")
        else:
            print(f"  Error at {i}: {resp.status_code}")
            # fallback: one by one
            for text in batch:
                r = requests.post(f"{OLLAMA_URL}/api/embed", json={"model": MODEL, "input": text}, timeout=60)
                if r.status_code == 200:
                    embeddings.append(r.json()['embeddings'][0])
                else:
                    embeddings.append([])
                    print(f"    Skip: {r.status_code}")
    except Exception as e:
        print(f"  Batch error at {i}: {e}")
        for text in batch:
            try:
                r = requests.post(f"{OLLAMA_URL}/api/embed", json={"model": MODEL, "input": text}, timeout=60)
                embeddings.append(r.json()['embeddings'][0])
            except:
                embeddings.append([])

# 保存
valid = sum(1 for e in embeddings if len(e) > 0)
print(f"Writing {valid}/{len(embeddings)} valid embeddings")

with open(embeddings_file, 'w', encoding='utf-8') as f:
    for emb in embeddings:
        f.write(json.dumps(emb) + '\n')

print("Done!")

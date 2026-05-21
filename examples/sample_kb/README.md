# Sample knowledge base

This directory intentionally contains no real knowledge-base data.

To create a sample KB:

```bash
mkdir -p knowledge_bases/RVD reference
cp /path/to/your/public-or-owned-documents/* reference/
python rebuild_kb.py reference knowledge_bases/RVD
python gen_embeddings.py knowledge_bases/RVD/segments.json knowledge_bases/RVD/embeddings.json
```

Do not commit generated `segments.json`, `embeddings.json`, or private document caches.

# Sample knowledge base

This directory intentionally contains no real knowledge-base data.

To create a sample KB:

```bash
mkdir -p knowledge_bases/papers reference
cp /path/to/your/public-or-owned-documents/* reference/
python rebuild_kb.py reference knowledge_bases/papers
python gen_embeddings.py knowledge_bases/papers/segments.json knowledge_bases/papers/embeddings.json
```

Do not commit generated `segments.json`, `embeddings.json`, or private document caches.

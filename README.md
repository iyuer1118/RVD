# Academic RAG

Academic RAG is a local-first, research-oriented Retrieval-Augmented Generation (RAG) system for papers, technical reports, lecture notes, and lab documents. It provides a Web UI, document ingestion, vector search, RAG question answering, deep-reading reports, OpenAI-compatible APIs, and agent-friendly command-line tools.

> This repository is a cleaned open-source release. It does **not** include real API keys, auth codes, user data, logs, uploaded files, copyrighted PDFs, or generated knowledge-base artifacts such as `embeddings.json`, `segments.json`, or caches. The project is released under Apache License 2.0.

## Why Academic RAG?

Most researchers do not only need a chatbot. They need a system that can:

- organize many PDFs and notes into reusable knowledge bases;
- answer questions with source traces;
- support literature review, comparison, and research-gap discovery;
- run locally when documents are private or unpublished;
- expose APIs and command-line tools so agents can query the same knowledge base.

Academic RAG is designed for these workflows. It is **not limited to any single field**. You can use it for computer science, medicine, biology, economics, social science, education, course notes, lab reports, or internal technical documents.

The default example knowledge base is named `papers`, but you can create any domain-specific KB such as `biology`, `clinical`, `economics`, `software-engineering`, or `course-notes`.

## Features

- **Local-first academic knowledge base**: keep papers and internal documents on your own machine.
- **Multi-format ingestion**: PDF, TXT, and Markdown documents.
- **Knowledge-base builder**: create `metadata.json`, `segments.json`, and `embeddings.json` from your document folder.
- **Vector search**: search document fragments without calling an LLM.
- **RAG Q&A**: retrieve relevant fragments and generate grounded answers.
- **Document browsing**: list knowledge bases, list documents, inspect document details.
- **Deep reading reports**: generate structured reading notes for individual papers or reports.
- **OpenAI-compatible endpoint**: integrate with OpenAI SDK, LangChain, LlamaIndex, and agent frameworks.
- **Agent tools**: command-line scripts for search, ask, list KBs, list docs, document detail, and deep reading.
- **Model backend flexibility**: Ollama for local embedding/chat; DeepSeek or other OpenAI-compatible APIs are optional.

## System Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                       Academic RAG                         │
├─────────────────────────────────────────────────────────────┤
│  Documents                                                   │
│  PDF / TXT / Markdown / reports / lecture notes              │
│                         │                                   │
│                         ▼                                   │
│  Text extraction + chunking ──▶ metadata ──▶ embeddings       │
│                         │                                   │
│                         ▼                                   │
│  knowledge_bases/<KB>/                                      │
│    ├── metadata.json                                        │
│    ├── segments.json      # generated; do not commit         │
│    └── embeddings.json    # generated; do not commit         │
│                         │                                   │
│                         ▼                                   │
│  Search API / RAG API / OpenAI-compatible Chat API           │
│                         │                                   │
│                         ▼                                   │
│  Web UI / Agent tools / external research workflows          │
└─────────────────────────────────────────────────────────────┘
```

## Repository Layout

```text
.
├── rag_web_server.py                  # Flask Web backend and API server
├── static/index.html                  # Web UI
├── agent_tools/                       # CLI/agent wrappers
│   ├── rag_search.py
│   ├── rag_ask.py
│   ├── rag_list_kbs.py
│   ├── rag_list_docs.py
│   ├── rag_doc_detail.py
│   └── rag_deep_read.py
├── rebuild_kb.py                      # Build metadata/segments from documents
├── gen_embeddings.py                  # Generate embeddings through Ollama
├── analyze_duplicates.py              # Inspect duplicate sources in segments
├── scripts/keyword_recalibration.py   # Optional keyword/tag maintenance helper
├── docs/
│   ├── TECHNICAL_GUIDE.md             # Architecture and technical notes
│   ├── backend_api.md                 # API reference
│   └── manual.md                      # Longer user manual
├── examples/sample_kb/                # Example instructions, no copyrighted data
├── knowledge_bases/.gitkeep           # Generated KBs live here locally
├── data/.gitkeep
├── .env.example
├── requirements.txt
└── LICENSE
```

## Requirements

Required:

- Python 3.10+，recommended: Python 3.11
- pip / venv

Recommended for local RAG:

- [Ollama](https://ollama.com/) for local embeddings and optional local chat
- Embedding model: `bge-m3`
- Chat model example: `mistral-nemo`

Optional:

- DeepSeek or any OpenAI-compatible Chat Completions API
- LibreOffice for future document conversion workflows
- CUDA GPU for faster local inference through Ollama

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/iyuer1118/RVD.git academic-rag
cd academic-rag

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` or export variables in your shell. At minimum, set strong auth values before exposing the service:

```bash
export RAG_BASE_DIR=$(pwd)
export RAG_KB_NAME=papers
export RAG_AUTH_CODE='your-strong-auth-code'
export RAG_JWT_SECRET='your-long-random-secret'
export RAG_HOST=0.0.0.0
export RAG_PORT=10663
```

If you use a cloud LLM provider:

```bash
export DEEPSEEK_API_KEY='your-api-key'
export DEEPSEEK_BASE_URL='https://api.deepseek.com/v1'
export DEEPSEEK_MODEL='deepseek-chat'
```

> `rag_web_server.py` does not automatically load `.env` files. Use shell `export`, direnv, systemd `EnvironmentFile`, Docker env files, or add your own `python-dotenv` loader.

### 3. Install and start Ollama for embeddings

```bash
ollama pull bge-m3
# Optional local chat model
ollama pull mistral-nemo
```

Make sure Ollama is running, usually at:

```text
http://localhost:11434
```

### 4. Build a knowledge base from your documents

Create a document folder and a KB folder:

```bash
mkdir -p reference knowledge_bases/papers
```

Put documents you are allowed to use into `reference/`:

```text
reference/
├── paper-a.pdf
├── paper-b.md
└── lecture-notes.txt
```

Generate text segments and metadata:

```bash
python rebuild_kb.py reference knowledge_bases/papers
```

Generate embeddings:

```bash
python gen_embeddings.py \
  knowledge_bases/papers/segments.json \
  knowledge_bases/papers/embeddings.json
```

Verify that the generated database files exist:

```bash
test -f knowledge_bases/papers/metadata.json
test -f knowledge_bases/papers/segments.json
test -f knowledge_bases/papers/embeddings.json
```

### 5. Start the Web server

```bash
export RAG_BASE_DIR=$(pwd)
export RAG_KB_NAME=papers
export RAG_HOST=0.0.0.0
export RAG_PORT=10663
python rag_web_server.py
```

Open:

```text
http://localhost:10663
```

For production-like deployments, put the server behind a reverse proxy, enable HTTPS, and use strong secrets.

## Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `RAG_BASE_DIR` | Base directory for data and KB paths | `$(pwd)` |
| `RAG_KB_NAME` | Default knowledge base name | `papers` |
| `RAG_HOST` | Server bind address | `0.0.0.0` |
| `RAG_PORT` | Server port | `10663` |
| `RAG_AUTH_CODE` | Registration/security code and legacy bearer token | `change-this` |
| `RAG_JWT_SECRET` | JWT signing secret | `change-this-too` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `EMBEDDING_MODEL` | Embedding model name | `bge-m3` |
| `OLLAMA_CHAT_MODEL` | Local chat model | `mistral-nemo` |
| `DEEPSEEK_API_KEY` | Optional cloud model API key | empty by default |
| `DEEPSEEK_BASE_URL` | OpenAI-compatible base URL | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | Chat model name | `deepseek-chat` |

See `.env.example` for a full template.

## Web UI Workflow

The Web interface is intended for everyday research use:

1. Register/login with the configured auth code.
2. Select or create a knowledge base.
3. Upload documents or build the KB through scripts.
4. Ask questions against a selected KB.
5. Inspect cited sources and document fragments.
6. Generate deep-reading reports for individual papers.
7. Use the API/agent tools for automated literature-review workflows.

## API Overview

The detailed API reference lives in [`docs/backend_api.md`](docs/backend_api.md). The most commonly used endpoints are below.

### Pure search: `POST /api/search`

Search only; does not call an LLM.

```bash
curl -X POST http://localhost:10663/api/search \
  -H "Authorization: Bearer $RAG_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "transformer architecture survey",
    "kb": "papers",
    "top_k": 8,
    "min_score": 0.0,
    "return_text": true,
    "text_max_len": 500
  }'
```

### RAG Q&A: `POST /api/ask`

Retrieve relevant fragments and generate an answer.

```bash
curl -X POST http://localhost:10663/api/ask \
  -H "Authorization: Bearer $RAG_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "这组论文主要解决了什么研究问题？",
    "kb": "papers",
    "top_k": 8,
    "system_prompt": "你是一个专业的学术研究助手。请根据参考资料准确回答，并列出依据来源。",
    "temperature": 0.3,
    "max_tokens": 2048,
    "return_sources": true
  }'
```

### OpenAI-compatible chat: `POST /api/v1/chat/completions`

Compatible with OpenAI Chat Completions clients.

```python
import openai

client = openai.OpenAI(
    api_key="your-auth-code",
    base_url="http://localhost:10663/api/v1",
)

response = client.chat.completions.create(
    model="mistral-nemo",
    messages=[
        {"role": "user", "content": "请总结 knowledge base 中的主要研究主题"}
    ],
    extra_body={"kb": "papers", "rag": True, "top_k": 8},
)
print(response.choices[0].message.content)
```

### Other useful endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/knowledge-bases` | GET | List all knowledge bases |
| `/api/query` | POST | Legacy/frontend Q&A endpoint |
| `/api/upload` | POST | Upload a document |
| `/api/batch-upload` | POST | Batch upload documents |
| `/api/documents/<kb>` | GET | List documents in a KB |
| `/api/doc-detail/<kb>/<source>` | GET | Get document details |
| `/api/deep-read` | POST | Generate or read a deep-reading report |

## Agent Tools

Set the server address and token:

```bash
export RAG_API_BASE=http://localhost:10663
export RAG_TOKEN="$RAG_AUTH_CODE"
export RAG_KB_NAME=papers
```

Examples:

```bash
# Search document fragments
python agent_tools/rag_search.py '{"query":"transformer architecture survey","kb":"papers","top_k":5}'

# Ask a grounded research question
python agent_tools/rag_ask.py '{"query":"请总结这些论文中的主要研究问题和方法","kb":"papers","top_k":8}'

# List knowledge bases and documents
python agent_tools/rag_list_kbs.py '{}'
python agent_tools/rag_list_docs.py '{"kb":"papers"}'

# Inspect a specific document
python agent_tools/rag_doc_detail.py '{"kb":"papers","source":"paper-a.pdf"}'

# Generate/read a deep-reading report
python agent_tools/rag_deep_read.py '{"kb":"papers","source":"paper-a.pdf"}'
```

These tools are useful when an autonomous agent needs grounded access to the same academic KB used by the Web UI.

## Academic Workflows

### Literature review

- Build one KB per research direction.
- Ask for “main problems,” “methods,” “datasets,” “limitations,” and “future work.”
- Require sources in the answer and verify final claims against the original papers.

### Paper deep reading

- Use document detail and deep-read APIs for one paper at a time.
- Extract background, motivation, method, experiments, contributions, limitations, and follow-up ideas.
- Keep generated reports as drafts, not as authoritative summaries.

### Course or lab knowledge base

- Ingest lecture notes, reading lists, lab documents, and technical reports.
- Use the Web UI for interactive Q&A.
- Use agent tools for recurring summaries or weekly literature digests.

### Multi-domain research

Create multiple KBs instead of mixing unrelated corpora:

| Scenario | KB example | Example question |
|---|---|---|
| General papers | `papers` | “这些论文的共同研究问题是什么？” |
| Clinical research | `clinical` | “这些临床试验的主要 endpoint 有何差异？” |
| Economics | `economics` | “这些论文采用了哪些因果识别策略？” |
| Course notes | `course-notes` | “请根据讲义解释这个概念并给出例子。” |
| Software engineering | `software-engineering` | “这些论文如何评估软件质量？” |

## Data, Privacy, and Open-Source Safety

Generated KB files can contain copyrighted or private text fragments. Do not commit them unless you intentionally publish the corpus and have the right to do so.

Do **not** commit:

```text
.env
user_data/
uploads/
chat_sessions/
deep_reads/
agent_sessions/
usage_stats.json
knowledge_bases/**/embeddings.json
knowledge_bases/**/segments.json
knowledge_bases/**/doc_details_cache.json
*.pdf
*.log
__pycache__/
*.pyc
```

Before publishing a fork, scan for secrets and private paths:

```bash
grep -RInE 'sk-[A-Za-z0-9]{10,}|api[_-]?key|token|password|secret|Bearer ' . \
  --exclude-dir=.git || true
```

## Troubleshooting

### `Unexpected token '<'` in the browser

The frontend expected JSON but received an HTML error page. Check:

- Flask server logs;
- API URL and port;
- authentication header;
- reverse-proxy configuration;
- whether the backend raised an exception and returned an HTML traceback.

### Search returns nothing

Check that both files exist and correspond to the same KB:

```bash
test -f knowledge_bases/<KB>/segments.json
test -f knowledge_bases/<KB>/embeddings.json
```

Also verify that Ollama is running and that the embedding model matches the one used during indexing.

### DeepSeek/OpenAI-compatible calls fail

Verify:

```bash
echo "$DEEPSEEK_API_KEY"
echo "$DEEPSEEK_BASE_URL"
echo "$DEEPSEEK_MODEL"
```

If no cloud API key is configured, use Ollama/local models where supported.

### Port already in use

```bash
lsof -i :10663
# or choose another port
export RAG_PORT=18080
python rag_web_server.py
```

## Documentation

- [Technical Guide](docs/TECHNICAL_GUIDE.md): architecture, KB layout, and technical notes.
- [Backend API](docs/backend_api.md): endpoint details and request examples.
- [User Manual](docs/manual.md): longer UI and operational manual.
- [Sample KB Notes](examples/sample_kb/README.md): how to create a minimal demo KB.

## License

Academic RAG is released under the Apache License 2.0. You may use, modify, distribute, and deploy it commercially or privately, subject to the license terms. See [`LICENSE`](LICENSE).

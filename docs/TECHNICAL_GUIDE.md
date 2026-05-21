# Academic RAG 技术指南

## 项目概述

Academic RAG 是一个面向学术论文、技术报告、课程资料和研究文档的本地化检索增强生成（RAG）系统。它不限定于安全领域，可用于计算机科学、医学、生物信息、社会科学、经济学、教育学等多种研究场景。

系统目标是帮助研究者把分散的 PDF、Markdown、TXT 和技术报告整理为可检索、可问答、可精读的本地知识库。

## 核心特性

- **学术友好**：面向论文阅读、文献综述、研究问题梳理和来源追踪。
- **本地优先**：支持 Ollama 本地 embedding/chat，数据可留在本机。
- **多知识库**：不同研究方向可建立不同 KB，例如 `papers`、`biology`、`economics`、`course-notes`。
- **多格式支持**：支持 PDF、TXT、Markdown 等文档格式。
- **Web + Agent Tools**：既可用浏览器交互，也可由命令行/Agent 自动调用。
- **可选 Agent 后端**：高级 Agent 模式、论文精读、DocMod 文档修改和论文撰写可接入 Claude Code；Codex/OpenCode 可通过外部 orchestration 或兼容 adapter 接入。
- **可扩展模型后端**：支持 Ollama，也可配置 DeepSeek/OpenAI 兼容 API。

---

## 技术架构

```text
┌─────────────────────────────────────────────────────────────┐
│                       Academic RAG 系统                      │
├─────────────────────────────────────────────────────────────┤
│  文档导入层                                                  │
│  PDF / TXT / Markdown / 技术报告 / 课程资料                   │
│                         │                                   │
│                         ▼                                   │
│  文本抽取与分段  ──▶  元数据管理  ──▶  Embedding 生成          │
│                         │                                   │
│                         ▼                                   │
│  knowledge_bases/<KB>/segments.json + embeddings.json        │
│                         │                                   │
│                         ▼                                   │
│  检索 API / RAG 问答 / OpenAI-compatible Chat API             │
│                         │                                   │
│                         ▼                                   │
│  Web UI / Agent Tools / 外部研究工作流                       │
└─────────────────────────────────────────────────────────────┘
```

## 推荐目录结构

```text
academic-rag/
├── rag_web_server.py
├── static/index.html
├── agent_tools/
├── scripts/
├── docs/
├── reference/                       # 用户自行放入有权使用的文档，不建议提交
├── knowledge_bases/
│   └── papers/
│       ├── metadata.json
│       ├── segments.json            # 不建议提交
│       └── embeddings.json          # 不建议提交
├── .env.example
├── requirements.txt
└── README.md
```

## 知识库构建流程

1. 准备文档：

```bash
mkdir -p reference knowledge_bases/papers
# 将你有权使用的 PDF/TXT/Markdown 放入 reference/
```

2. 生成文本片段和元数据：

```bash
python rebuild_kb.py reference knowledge_bases/papers
```

3. 生成向量：

```bash
ollama pull bge-m3
python gen_embeddings.py knowledge_bases/papers/segments.json knowledge_bases/papers/embeddings.json
```

4. 启动服务：

```bash
export RAG_BASE_DIR=$(pwd)
export RAG_KB_NAME=papers
export RAG_AUTH_CODE='your-strong-auth-code'
export RAG_JWT_SECRET='your-long-random-secret'
python rag_web_server.py
```

## 多学科使用示例

| 场景 | KB 名称示例 | 查询示例 |
|------|-------------|----------|
| 文献综述 | `papers` | “这些论文的共同研究问题是什么？” |
| 医学研究 | `clinical` | “这些临床试验的主要 endpoint 有何差异？” |
| 经济学 | `economics` | “这些论文采用了哪些因果识别策略？” |
| 课程资料 | `course-notes` | “请根据讲义解释这个概念并给出例子。” |
| 软件工程 | `software-engineering` | “这些论文如何评估软件质量？” |

## Agent 后端与高级工作流

基础检索和 RAG 问答不依赖 coding agent：`/api/search`、`/api/ask`、`/api/v1/chat/completions` 以及 `agent_tools/*.py` 都可以只依赖知识库、embedding 和配置好的 LLM 后端运行。

高级工作流需要外部 agent CLI：

| 功能 | 是否需要 agent | 说明 |
|---|---:|---|
| Web Agent 模式 | 是 | 后端启动 agent 子进程并通过 SSE 转发输出。 |
| Deep Read | 默认需要 | 使用 agent 处理长文本并生成结构化报告，部分路径可 fallback 到普通 LLM。 |
| DocMod 文档修改 | 是 | 需要 agent 读取当前文档、执行迭代编辑，并返回修改后内容。 |
| 论文撰写 | 高级流程需要 | 用 agent 进行多轮规划、章节草稿和修改。 |

当前开源实现主要兼容 Claude Code：

```bash
npm install -g @anthropic-ai/claude-code
claude auth login
export RAG_AGENT_BACKEND=claude
export CLAUDE_BIN=$(command -v claude)
```

Codex/OpenCode 支持两种方式：

1. 外部编排：让 Codex/OpenCode 直接调用 `agent_tools/rag_search.py`、`agent_tools/rag_ask.py` 等脚本。
2. Adapter：实现一个包装脚本，把 Codex/OpenCode 输出转换成 Claude Code `stream-json` 兼容格式，然后设置 `CLAUDE_BIN` 或 `RAG_AGENT_ADAPTER` 指向该脚本。

相关环境变量：`RAG_AGENT_BACKEND`、`CLAUDE_BIN`、`CODEX_BIN`、`OPENCODE_BIN`、`RAG_AGENT_ADAPTER`。

## Agent Tools

```bash
export RAG_API_BASE=http://localhost:10663
export RAG_TOKEN="$RAG_AUTH_CODE"
export RAG_KB_NAME=papers

python agent_tools/rag_search.py '{"query":"transformer architecture survey","kb":"papers","top_k":5}'
python agent_tools/rag_ask.py '{"query":"请总结这些论文的方法差异","kb":"papers","top_k":8}'
python agent_tools/rag_list_kbs.py '{}'
python agent_tools/rag_list_docs.py '{"kb":"papers"}'
```

## 学术使用建议

- 把 RAG 输出视为“带来源线索的研究助手回答”，不要替代人工阅读和引用核验。
- 对综述、比较、归纳类问题，要求返回 sources，便于追溯证据。
- 不同研究方向建议分 KB 管理，避免语义空间混杂。
- 不要提交未授权论文 PDF、内部报告或生成后的向量数据库实体。
- 若用于论文写作，应在最终稿中回到原文核查概念、实验指标和引用。

## 安全与隐私

- `.env`、API Key、认证码、JWT secret 不应提交。
- `knowledge_bases/**/embeddings.json`、`segments.json` 可能包含原文片段，不应公开提交。
- `uploads/`、`user_data/`、`chat_sessions/`、`deep_reads/` 可能包含用户隐私，不应公开提交。
- 生产部署建议配置 HTTPS、反向代理、强认证码和访问控制。

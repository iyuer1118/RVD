# Academic RAG 开源版

Academic RAG 是一个面向学术论文、技术报告和研究资料的本地知识库检索与问答 Web 系统。它支持 PDF/TXT/Markdown 文档导入、文本分段、向量检索、RAG 问答、文档浏览、精读报告和命令行 agent tools，适用于计算机科学、医学、社会科学、经济学、教育学等多种研究场景。

> 本 `release/` 目录是清洗后的开源发布包，不包含真实 API Key、认证码、用户数据、日志、上传文件、论文 PDF 或知识库实体（如 embeddings/segments/cache）。本项目开源发布包采用 Apache License 2.0，详见 `LICENSE`。

## 项目定位

Academic RAG 的目标是提供一个**学术友好、可本地部署、可扩展到多学科的 RAG 系统**，而不是某个单一领域的专用工具。你可以用它构建：

- 论文阅读和文献综述知识库
- 课程资料、教材和讲义知识库
- 实验室内部技术报告知识库
- 跨学科研究资料库
- 软件工程、医学、生物信息、社会科学、经济学等领域知识库

默认示例知识库名称为 `papers`。如需面向某个领域，可以自行创建 `biology`、`economics`、`security`、`course-notes` 等知识库。

## 功能列表

- Flask Web 后端与 `static/index.html` 前端
- 多知识库浏览、文档列表、片段检索、RAG 问答
- Ollama 本地模型调用，DeepSeek/OpenAI 兼容 Chat API 可选
- PDF/TXT/Markdown 文档导入与知识库重建脚本
- 嵌入向量生成脚本（Ollama `/api/embed`）
- Agent tools：搜索、问答、列 KB、列文档、文档详情、精读报告
- 辅助脚本：重复文档分析、关键词重校准

## Release 内容说明

```text
rag_web_server.py              # 清洗后的 Web 后端
static/index.html              # 前端页面
agent_tools/*.py               # CLI/Agent 工具
rebuild_kb.py                  # 从文档重建 segments/metadata
gen_embeddings.py              # 生成 embeddings
analyze_duplicates.py          # 分析 segments 中重复 source
scripts/keyword_recalibration.py
README.md .env.example .gitignore requirements.txt
examples/ data/ knowledge_bases/ # 空占位目录/示例说明
```

## 系统依赖

- Python 3.10+（建议 3.11）
- 可选：Ollama（本地 embedding/chat，例如 `bge-m3`, `mistral-nemo`）
- 可选：DeepSeek 或其他 OpenAI 兼容 Chat Completions API
- 可选：LibreOffice（如需在扩展功能中转换 doc/docx/pdf）

## 安装 Python 依赖

```bash
cd release
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少修改 RAG_AUTH_CODE 和 RAG_JWT_SECRET；如使用云模型，填写 DEEPSEEK_API_KEY
```

示例：

```bash
export RAG_BASE_DIR=$(pwd)
export RAG_KB_NAME=papers
export RAG_AUTH_CODE='your-strong-auth-code'
export RAG_JWT_SECRET='your-long-random-secret'
export DEEPSEEK_API_KEY='your-api-key'
```

> `rag_web_server.py` 不会自动读取 `.env` 文件；可用 shell `export`、direnv、systemd EnvironmentFile，或自行安装/启用 python-dotenv。

## 初始化/构建学术知识库数据库

1. 创建知识库和文档目录。这里使用通用学术知识库名 `papers`，你也可以换成 `biology`、`economics`、`security`、`course-notes` 等：

```bash
mkdir -p knowledge_bases/papers reference
```

2. 放入你有权使用的 PDF/TXT/Markdown 文档到 `reference/`（或任意目录）。不要提交未获授权的论文 PDF 或内部资料。

3. 重建文本片段和元数据：

```bash
python rebuild_kb.py reference knowledge_bases/papers
```

4. 确保 Ollama 已运行并已拉取 embedding 模型（示例）：

```bash
ollama pull bge-m3
python gen_embeddings.py knowledge_bases/papers/segments.json knowledge_bases/papers/embeddings.json
```

5. 验证生成文件：

```bash
test -f knowledge_bases/papers/metadata.json
test -f knowledge_bases/papers/segments.json
test -f knowledge_bases/papers/embeddings.json
```

脚本参数较轻量，如需自定义分段、模型或元数据字段，请根据脚本源码/help 调整。

## 启动服务

```bash
export RAG_BASE_DIR=$(pwd)
export RAG_KB_NAME=papers
export RAG_HOST=0.0.0.0
export RAG_PORT=10663
python rag_web_server.py
```

访问：<http://localhost:10663>

首次用户系统会创建默认 admin（请上线前修改/替换认证方案和默认密码）。

## Agent tools 使用

设置 API 地址和 token/auth code：

```bash
export RAG_API_BASE=http://localhost:10663
export RAG_TOKEN="$RAG_AUTH_CODE"
export RAG_KB_NAME=papers
```

示例：

```bash
python agent_tools/rag_search.py '{"query":"transformer architecture survey","kb":"papers","top_k":5}'
python agent_tools/rag_ask.py '{"query":"请总结这些论文中的主要研究问题和方法","kb":"papers","top_k":8}'
python agent_tools/rag_list_kbs.py '{}'
python agent_tools/rag_list_docs.py '{"kb":"papers"}'
```

## 适合的学术工作流

- **文献检索**：围绕研究问题快速查找相关片段和来源。
- **论文精读**：对单篇论文生成结构化阅读报告，包括背景、方法、实验、贡献和局限。
- **综述写作**：按主题聚合多篇论文证据，辅助形成 related work 和 research gap。
- **组会/课程资料库**：将讲义、论文和技术报告整理成可问答知识库。
- **跨领域调研**：为不同学科建立多个 KB，通过 `kb` 参数切换。

## 安全注意事项

- 不要提交 `.env`、真实 API Key、认证码、JWT secret 或 Bearer token。
- 不要提交 `user_data/`, `uploads/`, `chat_sessions/`, `deep_reads/`, `agent_sessions/`, `usage_stats.json`。
- 不要提交知识库实体：`knowledge_bases/**/embeddings.json`, `segments.json`, `doc_details_cache.json`。
- 不要提交未授权 PDF、内部资料、日志、缓存、`__pycache__`、`*.pyc`。
- 生产部署请使用强随机 `RAG_AUTH_CODE`/`RAG_JWT_SECRET`，并配置 HTTPS、反向代理和访问控制。

## 常见问题

- `Unexpected token '<'`：前端收到 HTML 错误页而不是 JSON。检查 Flask 日志、API URL、认证 header、后端异常和 response content-type。
- 检索为空：确认 `knowledge_bases/<KB>/segments.json` 与 `embeddings.json` 均存在且行数匹配。
- DeepSeek 调用失败：确认 `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` 配置正确；否则会回退到 Ollama。

## 许可证

本项目采用 Apache License 2.0 开源。该许可证允许商业使用、修改、分发和私有部署，并提供明确的专利授权条款。详见 `LICENSE`。

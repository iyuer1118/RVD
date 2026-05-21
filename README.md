# RecurringVul RAG 开源版

RecurringVul RAG 是一个面向论文/技术文档的本地知识库检索与问答 Web 系统，支持 PDF/文本分段、向量检索、RAG 问答、文档浏览、精读报告和命令行 agent tools。

> 本 `release/` 目录是清洗后的开源发布包，不包含真实 API Key、认证码、用户数据、日志、上传文件、论文 PDF 或知识库实体（如 embeddings/segments/cache）。本项目开源发布包采用 Apache License 2.0，详见 `LICENSE`。

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
export RAG_AUTH_CODE='your-strong-auth-code'
export RAG_JWT_SECRET='your-long-random-secret'
export DEEPSEEK_API_KEY='your-api-key'
```

> `rag_web_server.py` 不会自动读取 `.env` 文件；可用 shell `export`、direnv、systemd EnvironmentFile，或自行安装/启用 python-dotenv。

## 初始化/构建知识库数据库

1. 创建知识库和文档目录：

```bash
mkdir -p knowledge_bases/RVD reference
```

2. 放入你有权使用的 PDF/TXT/Markdown 文档到 `reference/`（或任意目录）。不要提交真实论文 PDF。

3. 重建文本片段和元数据：

```bash
python rebuild_kb.py reference knowledge_bases/RVD
```

4. 确保 Ollama 已运行并已拉取 embedding 模型（示例）：

```bash
ollama pull bge-m3
python gen_embeddings.py knowledge_bases/RVD/segments.json knowledge_bases/RVD/embeddings.json
```

5. 验证生成文件：

```bash
test -f knowledge_bases/RVD/metadata.json
test -f knowledge_bases/RVD/segments.json
test -f knowledge_bases/RVD/embeddings.json
```

脚本参数较轻量，如需自定义分段、模型或元数据字段，请根据脚本源码/help 调整。

## 启动服务

```bash
export RAG_BASE_DIR=$(pwd)
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
```

示例：

```bash
python agent_tools/rag_search.py '{"query":"binary code similarity","kb":"RVD","top_k":5}'
python agent_tools/rag_ask.py '{"query":"总结主要方法","kb":"RVD","top_k":8}'
python agent_tools/rag_list_kbs.py '{}'
python agent_tools/rag_list_docs.py '{"kb":"RVD"}'
```

## 安全注意事项

- 不要提交 `.env`、真实 API Key、认证码、JWT secret 或 Bearer token。
- 不要提交 `user_data/`, `uploads/`, `chat_sessions/`, `deep_reads/`, `agent_sessions/`, `usage_stats.json`。
- 不要提交知识库实体：`knowledge_bases/**/embeddings.json`, `segments.json`, `doc_details_cache.json`。
- 不要提交论文 PDF、日志、缓存、`__pycache__`、`*.pyc`。
- 生产部署请使用强随机 `RAG_AUTH_CODE`/`RAG_JWT_SECRET`，并配置 HTTPS、反向代理和访问控制。

## 常见问题

- `Unexpected token '<'`：前端收到 HTML 错误页而不是 JSON。检查 Flask 日志、API URL、认证 header、后端异常和 response content-type。
- 检索为空：确认 `knowledge_bases/<KB>/segments.json` 与 `embeddings.json` 均存在且行数匹配。
- DeepSeek 调用失败：确认 `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` 配置正确；否则会回退到 Ollama。

## 许可证

本项目采用 Apache License 2.0 开源。该许可证允许商业使用、修改、分发和私有部署，并提供明确的专利授权条款。详见 `LICENSE`。

# RAG 知识库系统使用手册

> 最后更新：2026-05-19
> 完整后端 API 参见本文档"后端 API 参考"部分；简要 API 文档另见 `docs/backend_api.md`。

---

## 1. 系统简介

本系统是一个本地部署的 RAG（Retrieval-Augmented Generation）知识库管理与问答平台，核心能力包括：

- **用户与权限**：注册/登录、JWT 认证、admin/user 角色隔离
- **知识库管理**：创建、重命名、删除；单文件/批量/ZIP 上传
- **智能查询**：纯检索、RAG 问答、多轮 Chat、OpenAI 兼容接口
- **Agent 模式**：基于 Claude Code 的自主研究助手，可调用 6 种 RAG 工具
- **论文精读（Deep Read）**：从 PDF 全文自动生成 7 个方面的精读报告
- **文档修改（DocMod）**：上传文档 → AI 对话修改 → 导出 md/pdf
- **论文撰写（Paper Writing）**：引导式收集信息 → 生成大纲 → 章节撰写
- **用量统计**：管理员可查看各用户分模块调用量

---

## 2. 快速开始

### 2.1 首次登录

1. 打开浏览器访问 `http://<服务器IP>:10663`
2. 首次使用默认管理员账号登录：
   - 用户名：`admin`
   - 密码：`admin123`
3. 登录后建议立即通过 `/api/change-password` 或前端修改密码

### 2.2 注册新用户

1. 在登录页点击"注册"
2. 填写用户名（2-32 位，支持字母/数字/下划线/中文）
3. 填写密码（至少 4 位）
4. 输入安全码（由管理员提供，即系统配置的 `auth_code`）
5. 注册成功后自动登录

### 2.3 基本工作流

1. **创建知识库**：管理页面 → 新建知识库 → 填写名称/描述
2. **上传文档**：添加文档页面 → 选择知识库 → 上传 PDF/TXT/MD/JSON/CSV
3. **查询问答**：查询页面 → 选择知识库 → 输入问题 → 获取答案与来源
4. **高级功能**：根据需要使用 Chat、Agent、精读、文档修改、论文撰写等

---

## 3. 登录与权限

### 3.1 认证体系

系统使用 **JWT（JSON Web Token）** 认证，有效期 72 小时。

- 登录/注册成功后返回 `token`
- 后续请求需在 Header 中携带：`Authorization: Bearer YOUR_TOKEN`

### 3.2 角色权限

| 功能 | admin | user |
|------|:-----:|:----:|
| 查询/搜索/问答/Chat | ✅ | ✅ |
| 上传文档/批量上传 | ✅ | ❌ |
| 新建知识库 | ✅ | ❌ |
| 删除/重命名知识库 | ✅ | ❌ |
| 查看用量统计 | ✅ | ❌ |
| Agent/精读/文档修改/论文撰写 | ✅ | ✅ |
| 修改密码 | ✅ | ✅ |

### 3.3 用户数据隔离

每个用户的数据存储在独立目录中：

```
user_data/
├── admin/
│   ├── chat_sessions/     # Chat 会话
│   ├── agent_sessions/    # Agent 会话
│   └── papers/            # 论文项目
├── <username>/
│   ├── chat_sessions/
│   ├── agent_sessions/
│   └── papers/
```

知识库数据（`knowledge_bases/`）为所有用户共享，但管理操作（创建/删除/重命名）仅 admin 可执行。

---

## 4. 前端功能使用指南

### 4.1 查询知识库

1. 左侧导航 → **💬 查询知识库**
2. 选择目标知识库
3. 在 **单次查询** 模式下输入问题
4. 点击 **开始查询**
5. 系统返回答案和相关片段来源（旧接口 `/api/query`，建议使用 `/api/ask`）

### 4.2 Chat 模式

1. 左侧导航 → **💬 Chat 模式**
2. 左侧可查看历史会话、新建会话、删除会话
3. 当前会话支持自动保存与续聊
4. 默认模型为 DeepSeek（云端 API），也支持手动配置 OpenAI 兼容参数（`model`、`base_url`、`api_key`）
5. 系统采用 **RRF 双路检索**（向量 + 关键词），提升召回率
6. 机器人回复支持 **Markdown 渲染**（标题、列表、代码块、表格、数学公式等）

### 4.3 添加文档

1. 左侧导航 → **➕ 添加文档**
2. 选择目标知识库
3. 上传单个文件（`pdf`/`txt`/`md`/`json`/`csv`）或批量上传
4. 批量导入支持多个文件或 ZIP 包
5. 系统自动：抽取文本 → 分块 → 生成 embedding → 原文件归档到 `reference/`
6. 文件名自动规范为：`[id]_[title]_[会议/期刊名]_[年份].pdf`

### 4.4 管理知识库

1. 左侧导航 → **⚙️ 管理知识库**
2. 查看所有知识库的名称、描述、模型、段落数
3. 可执行：重命名（仅 admin）、删除（仅 admin）、查看文档列表
4. 点击文档可查看详情：标题、中文标题、作者、机构、会议/期刊、年份、文档类型、中文摘要、关键词
5. 支持摘要预取（批量生成文档详情缓存）
6. 支持标签浏览（从文档关键词聚合）

> **幽灵文档**：文档列表中可能出现 `pdf_exists: false` 的条目，表示 segments 存在但原始 PDF 已丢失（可能是 reference/ 目录被清理）。此类文档仍可检索文本片段，但无法执行精读或查看原文。

### 4.5 Agent 模式

1. 左侧导航 → **🤖 Agent 模式**
2. Agent 是基于 Claude Code 的自主研究助手
3. 可用工具（Agent 自主决定何时调用）：
   - `rag_search`：纯检索（快速，不调用 LLM）
   - `rag_ask`：RAG 问答（检索 + 生成）
   - `rag_list_kbs`：列出知识库
   - `rag_list_docs`：列出知识库文档
   - `rag_doc_detail`：获取文档元数据与摘要
   - `rag_deep_read`：生成/获取论文精读报告
4. Agent 会话支持新建、删除、续聊
5. 首次消息会自动注入 `[当前知识库: <kb>]` 上下文

> **注意**：Agent 模式依赖 Claude Code CLI（`claude`）。如果 Claude Code 不可用，系统会自动 fallback 到 DeepSeek。SSE 流式输出，需要通过 `/api/agent/chat/<session_id>` 端点获取实时响应。

### 4.6 精读报告（Deep Read）

1. 在管理知识库 → 文档列表中，点击文档的"精读"按钮
2. 系统从 PDF 提取全文（最多 30 页），然后通过 Claude Code 生成精读报告
3. 报告涵盖 7 个方面：
   - 研究问题
   - 现有方法的局限性
   - 核心挑战与解决方案
   - 主要方法（技术路线、模型架构、关键算法）
   - 实验设计（数据集、baseline、评估指标）
   - 实验结果与结论
   - 不足与改进方向
4. 生成过程支持 SSE 实时流式输出和 status 轮询两种模式
5. 报告生成后持久化存储，可直接查看或通过 API 导出

> **Fallback 机制**：如果 Claude Code CLI 执行失败（退出码非 0），系统会自动切换到 DeepSeek API 作为后备，使用内联文本方式生成报告（最多 60000 字符输入）。

### 4.7 文档修改（DocMod）

1. 左侧导航 → **📝 文档修改**
2. 上传文档（支持 `md`/`pdf`/`doc`/`docx`）
3. 系统自动解析文档内容为 Markdown
4. 通过对话方式提出修改需求
5. AI（Claude Code）执行修改，将修改后文档放在 `<MODIFIED_DOC>` 标签中
6. 修改后的文档自动保存，支持继续迭代修改
7. 导出支持 `md` 和 `pdf` 格式

> **DocMod 内部机制**：文档修改通过 Claude Code 子进程实现，内部复用 Agent 的 SSE 流式输出通道。每次对话都会把当前文档内容（优先修改后版本）作为上下文传递给 Agent。

### 4.8 论文撰写（Paper Writing）

1. 左侧导航 → **✍️ 论文撰写**
2. 新建论文项目，填写标题和描述
3. **引导对话**：AI 会逐步提问收集研究信息（领域、贡献、目标会议、相关工作、实验设计）
4. 对话 ≥ 5 轮后 AI 会自动附带大纲建议（`<OUTLINE>` 标签）
5. 也可手动点击"生成大纲"
6. 大纲生成后可解析为章节列表
7. **章节生成**：前端已改用 Agent 模式进行章节撰写，旧的 `/api/papers/<paper_id>/generate-section` 接口标记为 DEPRECATED 但仍可用
8. 支持从 Agent 会话导入对话历史到论文项目

---

## 5. 管理员功能

### 5.1 管理仪表盘

- 管理员登录后可查看所有知识库
- 可创建、删除、重命名知识库
- 可查看用量统计（按用户、按模块分类）

### 5.2 用量统计

管理员可调用 `/api/admin/usage-stats` 查看所有用户的 API 调用情况，统计维度包括：

| 类别 | 包含端点 |
|------|----------|
| 查询 | `/api/query`, `/api/search`, `/api/ask`, `/api/chat`, `/api/v1/chat/completions` |
| 文档浏览 | `/api/knowledge-bases`, `/api/kb-documents`, `/api/kb-document-detail`, `/api/tags` |
| 知识库管理 | `/api/create`, `/api/delete-kb`, `/api/rename-kb` |
| 文档上传 | `/api/upload`, `/api/batch-upload` |
| 精读报告 | `/api/prefetch` |
| 论文撰写 | `/api/papers` |
| 文档修改 | `/api/docmod` |
| Agent | `/api/agent/chat`, `/api/agent/sessions` |

统计数据每 10 次请求自动持久化到 `usage_stats.json`，服务退出时也会保存。

---

## 6. 后端 API 参考

> 以下所有接口（除 `/`、`/api/register`、`/api/login` 外）均需携带 `Authorization: Bearer <JWT_TOKEN>` 请求头。
> 标注 `[admin]` 的接口仅管理员可访问。

### 6.1 认证与用户

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/register` | 无 | `username`, `password`, `security_code` | 注册新用户，需安全码 |
| POST | `/api/login` | 无 | `username`, `password` | 登录，返回 JWT token |
| GET | `/api/me` | 登录 | — | 获取当前用户信息（username, role, display_name） |
| PUT | `/api/change-password` | 登录 | `old_password`, `new_password` | 修改密码 |
| GET | `/api/manual` | 登录 | — | 获取完整 Markdown 使用手册，供前端渲染 |

### 6.2 知识库管理

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/knowledge-bases` | 登录 | — | 获取所有知识库列表 |
| POST | `/api/create` | admin | `name`, `desc`, `model` | 创建知识库（name 仅允许字母/数字/下划线/连字符） |
| POST | `/api/delete-kb` | admin | `name` | 删除知识库（不可恢复） |
| POST | `/api/rename-kb` | admin | `old_name`, `new_name` | 重命名知识库 |

### 6.3 文档上传

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/upload` | admin | form: `kb`, `file` | 单文件上传（pdf/txt/md/json/csv），后台处理 embedding |
| POST | `/api/batch-upload` | admin | form: `kb`, `files` | 批量上传（多文件或 ZIP），流式返回进度 |

### 6.4 文档浏览

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/kb-documents` | 登录 | `kb` | 获取知识库文档列表（含段落数、摘要状态、pdf_exists） |
| GET | `/api/kb-document-detail` | 登录 | `kb`, `source` | 获取文档详情（带缓存），含标题/作者/摘要/关键词 |
| GET | `/api/tags` | 登录 | `kb` | 获取知识库所有标签（从文档关键词聚合） |
| PUT | `/api/tags` | 登录 | `kb`, `source`, `keywords[]` | 更新文档关键词标签 |

### 6.5 摘要预取

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/prefetch` | admin | `kb` | 触发批量摘要预取 |
| GET | `/api/prefetch` | 登录 | `kb` | 查询预取进度 |

### 6.6 查询与对话

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/query` | 登录 | `kb`, `query`, `top_k` | 前端 UI 问答（旧接口，建议用 `/api/ask`） |
| POST | `/api/search` | 登录 | `kb`, `query`, `top_k`, `min_score`, `return_text`, `text_max_len` | 纯检索（不调用 LLM，最快） |
| POST | `/api/ask` | 登录 | `kb`, `query`, `top_k`, `system_prompt`, `temperature`, `max_tokens`, `return_sources`, `return_context` | RAG 问答（检索 + LLM 生成） |
| POST | `/api/chat` | 登录 | `kb`, `messages[]`, `top_k`, `model`, `base_url`, `api_key` | 多轮 Chat（RRF 双路检索 + DeepSeek/Ollama） |
| POST | `/api/v1/chat/completions` | 登录 | `messages[]`, `kb`, `rag`, `temperature`, `max_tokens`, `stream` | OpenAI 兼容接口 |

### 6.7 Chat 会话管理

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/chat-sessions` | 登录 | — | 列出当前用户的 Chat 会话 |
| GET | `/api/chat-sessions/<session_id>` | 登录 | — | 获取指定会话详情 |
| POST | `/api/chat-sessions` | 登录 | `title`, `messages` | 创建/更新会话 |
| DELETE | `/api/chat-sessions/<session_id>` | 登录 | — | 删除会话 |

### 6.8 Agent 模式

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/agent/sessions` | 登录 | — | 列出 Agent 会话 |
| POST | `/api/agent/sessions` | 登录 | `id`, `title`, `kb`, `messages` | 创建/更新 Agent 会话 |
| GET | `/api/agent/sessions/<session_id>` | 登录 | — | 获取 Agent 会话详情（含运行状态） |
| DELETE | `/api/agent/sessions/<session_id>` | 登录 | — | 删除 Agent 会话（会终止运行中的进程） |
| POST | `/api/agent/chat` | 登录 | `session_id`, `message`, `kb` | 发送消息给 Agent（自动创建会话，后台启动 Claude Code） |
| GET | `/api/agent/chat/<session_id>` | SSE | query: `token` 或 Header | Agent 输出 SSE 流（支持 JWT 和旧 auth_code 认证） |
| POST | `/api/agent/parse-result` | 登录 | `raw_events[]` | 解析累积的流式事件为最终结果 |

> **SSE 认证说明**：由于浏览器 `EventSource` API 不支持自定义 Header，Agent SSE 端点（`/api/agent/chat/<session_id>`）支持通过 URL query 参数 `?token=xxx` 传递认证信息。

### 6.9 精读报告（Deep Read）

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/deep-read` | 登录 | `source`, `kb` | 启动精读报告生成（需 PDF 存在于 reference/） |
| GET | `/api/deep-read/<report_id>/status` | 登录 | — | 查询生成状态（status/phase/progress/chars） |
| GET | `/api/deep-read/<report_id>/stream` | SSE | query: `token` 或 Header | SSE 实时流式输出 |
| GET | `/api/deep-read/<report_id>` | 登录 | — | 获取已完成的精读报告（Markdown 正文） |
| GET | `/api/deep-reads` | 登录 | — | 列出所有精读报告（元数据） |
| DELETE | `/api/deep-read/<report_id>` | 登录 | — | 删除精读报告 |
| GET | `/api/deep-read/<report_id>/export` | api_key | query: `api_key` | 对外导出接口（通过 api_key 认证） |
| GET | `/api/deep-reads/export` | api_key | query: `api_key` | 对外导出所有报告列表（不含正文） |

**report_id 生成规则**：取 `source` 文件名中第一个 `_` 之前的部分。例如 `074_VulHawk_...pdf` 的 report_id 为 `074`。

**状态说明**：
- `started`：任务已启动
- `running`：正在生成（phase 可能是 extracting/generating/fallback-generating）
- `done`：生成完成
- `not_found`：报告不存在
- `error`：生成失败

### 6.10 文档修改（DocMod）

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/docmod/upload` | 登录 | form: `file` | 上传文档（md/pdf/doc/docx） |
| GET | `/api/docmod/list` | 登录 | — | 列出当前用户的文档修改项目 |
| GET | `/api/docmod/<doc_id>` | 登录 | — | 获取文档详情（原始内容 + 修改后内容 + 对话历史） |
| DELETE | `/api/docmod/<doc_id>` | 登录 | — | 删除文档修改项目 |
| POST | `/api/docmod/<doc_id>/chat` | 登录 | `message`, `kb` | 发送修改指令（启动 Claude Code 子进程） |
| GET | `/api/docmod/<doc_id>/stream/<session_id>` | SSE | query: `token` 或 Header | 文档修改 SSE 流式输出 |
| GET | `/api/docmod/<doc_id>/export` | 登录 | query: `format`（`md`/`pdf`） | 导出修改后的文档 |

**`<MODIFIED_DOC>` 机制**：Agent 修改文档后，会将完整修改内容放在 `<MODIFIED_DOC>...</MODIFIED_DOC>` 标签中。SSE 流结束时服务端自动提取标签内容并保存为 `modified.md`。

### 6.11 论文撰写（Paper Writing）

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| POST | `/api/papers` | 登录 | `title`, `description`, `id`, `agent_session_id` | 创建论文项目 |
| GET | `/api/papers` | 登录 | — | 列出当前用户的论文项目 |
| GET | `/api/papers/<paper_id>` | 登录 | — | 获取论文项目详情 |
| PUT | `/api/papers/<paper_id>` | 登录 | `title`, `description`, `status`, `outline`, `sections` | 更新论文项目 |
| DELETE | `/api/papers/<paper_id>` | 登录 | — | 删除论文项目 |
| POST | `/api/papers/<paper_id>/outline` | 登录 | — | AI 生成论文大纲（基于引导对话内容） |
| POST | `/api/papers/<paper_id>/guide` | 登录 | `message` | 引导对话（AI 逐步收集论文信息） |
| POST | `/api/papers/<paper_id>/parse-outline` | 登录 | — | 解析大纲为章节列表（按 Markdown 标题层级） |
| POST | `/api/papers/<paper_id>/generate-section` | 登录 | `section_title`, `section_index` | **[DEPRECATED]** 生成章节（前端已改用 Agent） |

**引导对话自动大纲**：当用户发送 ≥ 5 条消息后，AI 会在回复中自动附带 `<OUTLINE>...</OUTLINE>` 标签中的大纲建议。

### 6.12 管理接口

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/admin/usage-stats` | admin | — | 获取所有用户的用量统计（含分类汇总） |
| POST | `/api/admin/usage-stats/reset` | admin | — | 重置所有统计数据 |
| GET | `/api/status` | 登录 | — | 健康检查（Ollama 状态等） |

---

## 7. 运维部署与故障排查

### 7.1 目录结构

```text
<release-dir>/
├── rag_web_server.py          # 主后端服务（Flask）
├── static/index.html          # 前端单页应用
├── agent_tools/               # Agent 工具脚本（6 个 .py）
├── knowledge_bases/           # 知识库数据（全局共享）
│   └── <kb>/
│       ├── metadata.json      # 知识库元数据
│       ├── segments.json      # 文本分段（JSONL）
│       ├── embeddings.json    # 向量数据（JSONL）
│       └── doc_details_cache.json  # 文档详情缓存
├── reference/                 # 原始文档归档
├── uploads/                   # 上传临时目录
├── user_data/                 # 用户数据隔离
│   └── <username>/
│       ├── chat_sessions/
│       ├── agent_sessions/
│       └── papers/
├── deep_reads/                # 精读报告存储
├── docmod/                    # 文档修改数据
│   └── <username>/
│       └── <doc_id>/
│           ├── meta.json
│           ├── content.md
│           ├── modified.md
│           └── messages.json
├── users.json                 # 用户账号数据
├── usage_stats.json           # 用量统计数据
├── docs/                      # 文档
└── scripts/                   # 运维脚本
```

### 7.2 服务启动

```bash
cd <release-dir>
python rag_web_server.py
```

默认监听：`0.0.0.0:10663`

**systemd 服务**（如果已配置）：

```bash
sudo systemctl start rag-server    # 启动
sudo systemctl status rag-server   # 状态
sudo systemctl restart rag-server  # 重启
journalctl -u rag-server -f        # 查看日志
```

### 7.3 运行依赖

| 组件 | 用途 | 说明 |
|------|------|------|
| Python 3 | 运行环境 | — |
| Flask + flask-cors | Web 框架 | — |
| requests | HTTP 客户端 | 调用 Ollama/DeepSeek |
| PyMuPDF (fitz) | PDF 解析 | DocMod 和文档上传 |
| pdftotext (poppler) | PDF 全文提取 | Deep Read 精读 |
| Ollama | 本地 LLM | `bge-m3`（embedding）、`mistral-nemo`（chat） |
| DeepSeek API | 云端 LLM | 摘要生成、Chat 默认模型 |
| Claude Code CLI | Agent 引擎 | Agent/Deep Read/DocMod 的核心执行器 |
| libreoffice | 文档转换 | DocMod 的 doc/docx 解析和 PDF 导出 |
| markdown (Python) | Markdown → HTML | DocMod PDF 导出 |

### 7.4 重要配置项

配置位于 `rag_web_server.py` 顶部的 `CONFIG` 字典：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `base_dir` | `RAG_BASE_DIR` 或当前 release 目录 | 系统工作根目录 |
| `ollama_url` | `http://localhost:11434` | Ollama 服务地址 |
| `embedding_model` | `bge-m3` | Embedding 模型 |
| `chat_model` | `mistral-nemo` | 本地 Chat 模型 |
| `deepseek_api_key` | — | DeepSeek API 密钥 |
| `deepseek_model` | `deepseek-chat` | DeepSeek 模型名 |
| `deepseek_base_url` | `https://api.deepseek.com/v1` | DeepSeek API 地址 |
| `auth_code` | — | 安全码（注册用），也作为旧版 Bearer Token |
| `export_api_key` | `None` | 精读报告对外导出的 API Key（None 时使用 auth_code） |

### 7.5 常见故障排查

#### 401 Unauthorized

- JWT token 过期（有效期 72 小时），重新登录获取新 token
- 请求头缺少 `Authorization: Bearer YOUR_TOKEN`
- Agent/Deep Read 的 SSE 端点：确认 `?token=` 参数正确

#### 知识库异常

- 检查 `segments.json` 与 `embeddings.json` 行数是否一致
- 查看 `metadata.json` 中的段落数是否与实际一致

#### 上传后段落数为 0

- 检查文件是否为空或加密 PDF
- 检查 Ollama 是否在线（embedding 依赖 `bge-m3`）
- 查看后台日志中是否有 batch embed 失败

#### PDF 缺失（pdf_exists: false）

- `reference/` 目录中对应的 PDF 文件不存在
- 原因可能是文件被手动清理或上传时归档失败
- 影响：无法执行精读报告生成

#### Ollama/GPU 问题

- 检查 `ollama list` 确认模型已拉取
- 检查 GPU 显存是否足够（`nvidia-smi`）
- 检查 `GET /api/status` 返回的 Ollama 状态

#### 摘要缓存/超时

- 摘要生成依赖 DeepSeek API，检查 API Key 是否有效
- 检查网络连接到 `api.deepseek.com`
- 查看日志中是否有 timeout 或 rate limit 错误

#### Claude Code session id UUID 问题

- Agent 内部使用 UUID 作为 session 文件名
- DocMod 会从 doc_id 派生一个符合 UUID 格式的 session id
- 如果手动调用 Agent API，确保 session_id 为合法 UUID v4 格式

#### SSE 流中断

- 检查 Nginx/代理是否配置了 `X-Accel-Buffering: no`
- 检查网络超时设置（SSE 默认 120 秒心跳）
- Agent 进程可能被 OOM Killer 终止

#### Deep Read 生成失败

- 确认 PDF 存在于 `reference/` 目录
- 确认 Claude Code CLI 可用（`which claude`）
- 检查 fallback 日志：Claude Code 失败后是否成功切换到 DeepSeek

---

## 8. 附录

### 8.1 OpenAI 兼容调用示例

**curl 示例：**

```bash
curl -X POST http://localhost:10663/api/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "什么是二进制代码相似性检测？"}],
    "kb": "RVD",
    "rag": true,
    "stream": false
  }'
```

**Python (openai SDK) 示例：**

```python
import openai

client = openai.OpenAI(
    api_key="YOUR_TOKEN",
    base_url="http://localhost:10663/api/v1"
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "什么是二进制代码相似性检测？"}]
)
print(response.choices[0].message.content)
```

### 8.2 注册/登录 curl 示例

```bash
# 注册
curl -X POST http://localhost:10663/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"mypassword","security_code":"change-me"}'

# 登录
curl -X POST http://localhost:10663/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"mypassword"}'

# 查看当前用户
curl http://localhost:10663/api/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 8.3 Agent 工具调用示例

Agent 工具位于 `agent_tools/` 目录，可独立于 Web 服务使用：

```bash
# 纯检索
python agent_tools/rag_search.py '{"query":"VulHawk","kb":"RVD","top_k":10}'

# RAG 问答
python agent_tools/rag_ask.py '{"query":"VulHawk用了什么方法？","kb":"RVD","top_k":8}'

# 列出知识库
python agent_tools/rag_list_kbs.py '{}'

# 列出知识库文档
python agent_tools/rag_list_docs.py '{"kb":"RVD"}'

# 文档详情
python agent_tools/rag_doc_detail.py '{"kb":"RVD","source":"074_VulHawk_...pdf"}'

# 精读报告
python agent_tools/rag_deep_read.py '{"source":"074_VulHawk_...pdf","kb":"RVD"}'
```

### 8.4 精读报告对外导出示例

```bash
# 导出单个报告
curl "http://localhost:10663/api/deep-read/074/export?api_key=YOUR_API_KEY"

# 导出报告列表
curl "http://localhost:10663/api/deep-reads/export?api_key=YOUR_API_KEY"
```

### 8.5 建议调用顺序

1. `POST /api/login` → 获取 JWT token
2. `GET /api/knowledge-bases` → 获取可用知识库列表
3. 按需选择：
   - `POST /api/search` — 只检索，最快
   - `POST /api/ask` — 程序化 RAG 问答
   - `POST /api/chat` — 多轮对话
   - `POST /api/v1/chat/completions` — OpenAI SDK 兼容
   - `POST /api/agent/chat` — Agent 自主研究
4. 如需兼容 OpenAI SDK，使用 `/api/v1/chat/completions`

### 8.6 响应时间参考

| 接口 | 首次 | 缓存命中 |
|------|------|----------|
| `/api/search` | ~7s | ~7s（无 LLM 缓存） |
| `/api/ask` | ~12s | — |
| `/api/v1/chat/completions` | ~24s | — |
| `/api/kb-document-detail` | ~10s | **~0.05s** |
| `/api/deep-read`（生成） | 2-5 min | 已存在时即时返回 |
| `/api/agent/chat` | 10s-5min | 取决于 Agent 行为 |

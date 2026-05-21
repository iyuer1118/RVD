# Academic RAG Backend API 文档

> 服务地址：`http://localhost:10663`  
> 认证方式：`Authorization: Bearer <RAG_TOKEN>`  
> 默认示例知识库：`papers`

---

## 一、纯检索 `/api/search`

**不调用 LLM**，只返回相关文档片段。适合快速查找论文、教材、技术报告中的证据片段。

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

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query | string | 必填 | 检索文本 |
| kb | string | `papers` | 知识库名称 |
| top_k | int | 8 | 返回最大结果数 |
| min_score | float | 0.0 | 最低相关度阈值（0-1） |
| return_text | bool | true | 是否返回文档片段文本 |
| text_max_len | int | 500 | 文本截断长度 |

**返回示例：**

```json
{
  "query": "transformer architecture survey",
  "rewritten_query": "transformer architecture survey",
  "kb": "papers",
  "total": 3,
  "results": [
    {"score": 0.691, "source": "attention-is-all-you-need.pdf", "text": "..."}
  ],
  "sources": ["attention-is-all-you-need.pdf"],
  "timestamp": "2026-05-11T..."
}
```

---

## 二、完整问答 `/api/ask`

检索 + LLM 生成答案。可自定义 system prompt 和温度等参数，适合论文问答、综述整理和研究资料分析。

```bash
curl -X POST http://localhost:10663/api/ask \
  -H "Authorization: Bearer $RAG_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "这组论文主要解决了什么研究问题？",
    "kb": "papers",
    "top_k": 8,
    "system_prompt": "你是一个专业的学术研究助手。请根据提供的参考资料准确回答问题，使用简体中文，并列出依据来源。",
    "temperature": 0.3,
    "max_tokens": 2048,
    "return_sources": true,
    "return_context": false
  }'
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query | string | 必填 | 问题文本 |
| kb | string | `papers` | 知识库名称 |
| top_k | int | 8 | 检索文档数 |
| system_prompt | string | 学术助手 | 自定义系统提示词 |
| temperature | float | 0.3 | LLM 温度 |
| max_tokens | int | 2048 | 最大生成 token 数 |
| return_sources | bool | true | 返回来源文档信息 |
| return_context | bool | false | 返回原始检索片段 |

**返回示例：**

```json
{
  "answer": "这些论文主要围绕长上下文建模、注意力效率和表示学习展开...",
  "query": "这组论文主要解决了什么研究问题？",
  "rewritten_query": "papers research problems methods summary",
  "kb": "papers",
  "sources": [
    {"source": "paper-a.pdf", "score": 0.691}
  ],
  "unique_sources": ["paper-a.pdf", "paper-b.pdf"],
  "timestamp": "2026-05-11T..."
}
```

---

## 三、OpenAI 兼容 `/api/v1/chat/completions`

兼容 OpenAI Chat Completions API 格式，可直接对接 LangChain、LlamaIndex、OpenAI SDK 等工具。

```bash
curl -X POST http://localhost:10663/api/v1/chat/completions \
  -H "Authorization: Bearer $RAG_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "你是一个学术研究助手"},
      {"role": "user", "content": "请比较这些论文的方法差异"}
    ],
    "kb": "papers",
    "top_k": 8,
    "temperature": 0.3,
    "max_tokens": 2048,
    "rag": true
  }'
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| messages | array | 必填 | OpenAI 格式消息列表 |
| kb | string | `papers` | 知识库名称 |
| top_k | int | 8 | 检索文档数 |
| temperature | float | 0.3 | LLM 温度 |
| max_tokens | int | 2048 | 最大生成 token 数 |
| rag | bool | true | 是否启用 RAG 检索增强（false=纯对话） |

**Python 对接示例：**

```python
import openai

client = openai.OpenAI(
    api_key="your-auth-code",
    base_url="http://localhost:10663/api/v1"
)

response = client.chat.completions.create(
    model="mistral-nemo",
    messages=[
        {"role": "user", "content": "请总结 knowledge base 中的主要研究主题"}
    ]
)
print(response.choices[0].message.content)
```

---

## 四、其他管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge-bases` | GET | 列出所有知识库 |
| `/api/query` | POST | 前端 UI 问答（旧接口） |
| `/api/upload` | POST | 上传文档 |
| `/api/batch-upload` | POST | 批量上传文档 |
| `/api/documents/<kb>` | GET | 列出知识库文档 |
| `/api/doc-detail/<kb>/<source>` | GET | 获取文档详情 |
| `/api/deep-read` | POST | 生成/读取论文精读报告 |

## 五、推荐学术使用方式

- 每个研究方向一个 KB，例如 `papers`、`biology`、`economics`、`course-notes`。
- 上传前确认文档版权和隐私边界。
- 对综述类问题开启 `return_sources=true`，便于检查引用依据。
- 对自动生成的回答进行人工核验，不要直接替代正式文献阅读。

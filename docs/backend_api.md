# RAG Backend API 文档

> 服务地址：`http://localhost:10663`
> 认证方式：`Authorization: Bearer change-me`

---

## 一、纯检索 `/api/search`

**不调用 LLM**，只返回相关文档片段。响应速度最快（~7秒，主要是 embedding 计算）。

```bash
curl -X POST http://localhost:10663/api/search \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "VulHawk binary similarity",
    "kb": "RVD",
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
| kb | string | "RVD" | 知识库名称 |
| top_k | int | 8 | 返回最大结果数 |
| min_score | float | 0.0 | 最低相关度阈值（0-1） |
| return_text | bool | true | 是否返回文档片段文本 |
| text_max_len | int | 500 | 文本截断长度 |

**返回示例：**
```json
{
  "query": "VulHawk binary similarity",
  "rewritten_query": "VulHawk binary similarity",
  "kb": "RVD",
  "total": 3,
  "results": [
    {"score": 0.691, "source": "074_VulHawk...NDSS_2023.pdf", "text": "..."},
    ...
  ],
  "sources": ["074_VulHawk...pdf"],
  "timestamp": "2026-05-11T..."
}
```

---

## 二、完整问答 `/api/ask`

检索 + LLM 生成答案。可自定义 system prompt 和温度等参数。

```bash
curl -X POST http://localhost:10663/api/ask \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "VulHawk用了什么方法做跨架构漏洞检测？",
    "kb": "RVD",
    "top_k": 8,
    "system_prompt": "你是一个专业的学术研究助手。请根据提供的参考资料准确回答问题，使用简体中文。",
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
| kb | string | "RVD" | 知识库名称 |
| top_k | int | 8 | 检索文档数 |
| system_prompt | string | (学术助手) | 自定义系统提示词 |
| temperature | float | 0.3 | LLM 温度 |
| max_tokens | int | 2048 | 最大生成 token 数 |
| return_sources | bool | true | 返回来源文档信息 |
| return_context | bool | false | 返回原始检索片段 |

**返回示例：**
```json
{
  "answer": "VulHawk使用基于熵的二进制代码搜索方法...",
  "query": "VulHawk用了什么方法做跨架构漏洞检测？",
  "rewritten_query": "VulHawk跨架构漏洞检测",
  "kb": "RVD",
  "sources": [
    {"source": "074_VulHawk...pdf", "score": 0.691},
    ...
  ],
  "unique_sources": ["074_VulHawk...pdf", "007_重现型...pdf"],
  "timestamp": "2026-05-11T..."
}
```

---

## 三、OpenAI 兼容 `/api/v1/chat/completions`

兼容 OpenAI Chat Completions API 格式，可直接对接 LangChain、LlamaIndex 等工具。

```bash
curl -X POST http://localhost:10663/api/v1/chat/completions \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "你是一个安全研究助手"},
      {"role": "user", "content": "BinDiff和VulHawk的区别是什么？"}
    ],
    "kb": "RVD",
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
| kb | string | "RVD" | 知识库名称 |
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
        {"role": "user", "content": "什么是二进制代码相似性检测？"}
    ]
)
print(response.choices[0].message.content)
```

**返回示例：**
```json
{
  "id": "chatcmpl-7242430aa635",
  "object": "chat.completion",
  "created": 1746980400,
  "model": "mistral-nemo",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "根据参考资料..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1}
}
```

---

## 四、其他管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge-bases` | GET | 列出所有知识库 |
| `/api/query` | POST | 前端 UI 问答（旧接口） |
| `/api/upload` | POST | 上传文档 |
| `/api/create` | POST | 创建知识库 |
| `/api/delete-kb` | POST | 删除知识库 |
| `/api/rename-kb` | POST | 重命名知识库 |
| `/api/kb-documents` | GET | 查看知识库文档列表 |
| `/api/kb-document-detail` | GET | 查看文档详情（带缓存） |
| `/api/status` | GET | 服务状态 |

---

## 五、响应时间参考

| 接口 | 首次 | 缓存命中 |
|------|------|----------|
| `/api/search` | ~7s | ~7s（无 LLM 缓存） |
| `/api/ask` | ~12s | — |
| `/api/v1/chat/completions` | ~24s | — |
| `/api/kb-document-detail` | ~10s | **~0.05s** |

# RecurringVul RAG 知识库技术指南

## 项目概述

RecurringVul RAG 是一个基于 LangChain4j + Ollama 的本地化检索增强生成（RAG）系统，专门用于重现型漏洞（Recurring Vulnerability）检测和分析。

### 核心特性

- **完全本地化**: 所有模型和数据都在本地运行，无需外部 API
- **GPU 加速**: 支持 NVIDIA CUDA 加速，大幅提升处理速度
- **增量索引**: 支持断点续传，自动保存和恢复进度
- **多格式支持**: 支持 PDF、TXT、Markdown 等多种文档格式

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    RecurringVul RAG 系统                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  文档加载器   │───▶│  文档分割器   │───▶│ Embedding模型│  │
│  │ (PDF/TXT/MD) │    │(1000字/200重叠)│   │  (bge-m3)    │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                  │           │
│                                                  ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  查询接口    │◀───│  向量存储     │◀───│  向量嵌入     │  │
│  │ (AI Services)│    │(InMemory+JSON)│    │  (1024维)    │  │
│  └──────┬───────┘    └──────────────┘    └──────────────┘  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐                                           │
│  │  Chat 模型   │                                           │
│  │ (mistral-nemo)│                                          │
│  └──────────────┘                                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │    Ollama 服务    │
                    │  (CUDA GPU 加速)  │
                    └──────────────────┘
```

### 技术栈

| 组件 | 技术 | 版本/配置 |
|------|------|----------|
| 语言 | Java | 17+ |
| 框架 | LangChain4j | 0.36.2 |
| 运行时 | Ollama | 0.18.1 |
| Chat 模型 | mistral-nemo | 本地部署 |
| Embedding 模型 | bge-m3 | 1024维, F16量化 |
| 向量存储 | InMemoryEmbeddingStore | JSON 持久化 |
| GPU 加速 | NVIDIA CUDA | 12.2 |
| 构建工具 | Maven | 3.x |

### 目录结构

```
recurringvul-rag-langchain4j/
├── src/main/java/rag/
│   ├── RecuringVulRAGOllama.java       # 主程序（Ollama版本）
│   ├── RecuringVulRAG.java             # 主程序（API版本）
│   ├── IncrementalIndexerOllama.java   # 增量索引工具（Ollama版本）⭐
│   └── IncrementalIndexer.java         # 增量索引工具（API版本）
├── knowledge_bases/
│   └── ollama_bge_m3/                  # 当前知识库存储
│       ├── embeddings.json             # 向量数据
│       ├── segments.json               # 文本段落数据
│       └── metadata.json               # 元数据
├── docs/                               # 文档目录
├── run_ollama_rag.sh                   # 前台运行脚本
├── run_rag_background.sh               # 后台运行脚本
├── run_incremental_index.sh            # 增量索引脚本 ⭐
└── pom.xml                             # Maven 配置
```

---

## 使用手册

### 环境要求

1. **Java 17+**
2. **Ollama 0.18.1+** (支持 CUDA GPU 加速)
3. **NVIDIA GPU** (推荐, 用于加速)
4. **8GB+ 内存**

### 安装步骤 （本机已完成安装）

#### 1. 安装 Ollama

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

# 拉取所需模型
ollama pull mistral-nemo    # Chat 模型
ollama pull bge-m3          # Embedding 模型
```

#### 2. 配置 GPU 加速（可选但推荐）

```bash
# 检查 CUDA 库权限
ls -la /usr/local/lib/ollama/cuda_v12/

# 如果权限不正确，修复权限
sudo chmod -R 755 /usr/local/lib/ollama/cuda_v12/

# 验证 GPU 检测
OLLAMA_DEBUG=1 ollama serve
# 应该看到: "inference compute" id=GPU... library=CUDA
```

#### 3. 编译项目

```bash
cd <project-dir>
mvn clean package -DskipTests
```

### 运行方式

#### 前台运行（推荐调试时使用）

```bash
./run_ollama_rag.sh
```

#### 后台运行（推荐生产环境）

```bash
./run_rag_background.sh

# 查看日志
tail -f rag_ollama_bge_m3_output.log

# 查看进度
grep '处理批次' rag_ollama_bge_m3_output.log | tail -10
```

### 监控命令

```bash
# 查看 GPU 使用情况
nvidia-smi

# 查看进程状态
ps aux | grep RecuringVulRAGOllama

# 查看索引进度
tail -50 rag_ollama_bge_m3_output.log

# 停止运行
pkill -f RecuringVulRAGOllama
```

### 增量索引（添加新文档）

当需要向现有知识库添加新的PDF或其他文档时，使用增量索引工具：

#### 使用方法

```bash
# 方式1: 使用脚本（推荐）
./run_incremental_index.sh /path/to/new_document.pdf

# 方式2: 直接运行Java
java -cp target/rag-langchain4j-1.0-SNAPSHOT.jar rag.IncrementalIndexerOllama /path/to/document.pdf

# 索引整个目录
./run_incremental_index.sh /path/to/new_documents/
```

#### 特性

| 特性 | 说明 |
|------|------|
| **自动去重** | 已存在的段落不会重复索引 |
| **断点续传** | 自动保存进度，支持中断恢复 |
| **GPU加速** | 使用Ollama本地GPU加速 |
| **批次优化** | 25段落/批次，充分利用GPU |

#### 示例输出

```
========================================
初始化增量索引工具 (Ollama版本)
========================================
Embedding模型: bge-m3 (本地)
批次大小: 25
========================================
加载已有知识库...
加载了 98993 个embeddings
加载了 98993 个segments
开始增量索引: /path/to/new_doc.pdf
分割后新增 150 个有效段落
处理批次 1/6 (段落 98993-99017)
  批次 1 完成，耗时 180 ms
...
增量索引完成 ✓
  新增段落: 150
  总段落数: 99143
========================================
```

#### 命令行帮助

```bash
java -cp target/rag-langchain4j-1.0-SNAPSHOT.jar rag.IncrementalIndexerOllama --help
```

---

## 当前状态

### 索引进度

| 指标 | 值 |
|------|------|
| 状态 | 正在索引中 |
| 数据源 | 85 个 PDF 文档 |
| 总段落数 | ~110,630 |
| 总批次数 | 22,126 |
| 当前批次 | 约 9,580 / 22,126 |
| 完成进度 | ~43% |
| 处理速度 | ~200ms/批次 (5段落/批次) |
| 预计剩余时间 | ~1.5 小时 |
| 向量存储大小 | ~583 MB |

### GPU 使用情况

| GPU | 使用率 | 显存 |
|-----|--------|------|
| RTX 3060 Laptop | 30-50% | 1035 MiB / 6144 MiB |

### 知识库配置

- **Chat 模型**: mistral-nemo (本地)
- **Embedding 模型**: bge-m3 (本地, 1024维)
- **文档分割**: 1000字符/段, 200字符重叠
- **批次大小**: 25段落/批次 (优化后，提升GPU利用率)
- **存储格式**: JSON 持久化

---

## Agent Skills 生成指南

本文档可作为其他 AI Agent 生成 Skills 的参考。以下是基于此知识库可能生成的 Skills 示例：

### Skill 1: 漏洞知识检索

```yaml
skill: vulnerability_search
description: 搜索重现型漏洞相关知识
trigger:
  - 用户询问漏洞检测方法
  - 用户询问二进制分析技术
  - 用户询问漏洞相似性分析
steps:
  1. 连接到本地 Ollama 服务 (http://localhost:11434)
  2. 加载知识库: knowledge_bases/ollama_bge_m3/
  3. 使用 bge-m3 模型生成查询向量
  4. 执行相似性搜索，返回 top-k 相关段落
  5. 使用 mistral-nemo 模型生成回答
```

### Skill 2: 文档索引更新

```yaml
skill: index_documents
description: 将新文档添加到知识库
trigger:
  - 用户添加新的漏洞研究文档
  - 定期知识库更新
steps:
  1. 扫描文档目录: <release-dir>/reference/
  2. 使用 DocumentSplitters 分割文档 (1000字/段, 200重叠)
  3. 使用 bge-m3 生成 embedding 向量
  4. 追加到现有向量存储
  5. 保存更新后的 JSON 文件
```

### Skill 3: RAG 查询接口

```java
// Java 代码示例 - 可用于生成 Skill
public interface VulnerabilityAssistant {

    @SystemMessage("""
        你是一个漏洞检测专家助手。
        基于提供的知识库内容回答用户问题。
        如果知识库中没有相关信息，请明确说明。
        """)
    String answer(@UserMessage String question);
}

// 使用方式
VulnerabilityAssistant assistant = AiServices.builder(VulnerabilityAssistant.class)
    .chatLanguageModel(chatModel)
    .contentRetriever(contentRetriever)
    .build();

String answer = assistant.answer("如何检测二进制中的缓冲区溢出漏洞？");
```

### 配置参数参考

```java
// Ollama 配置
OllamaChatModel chatModel = OllamaChatModel.builder()
    .baseUrl("http://localhost:11434")
    .modelName("mistral-nemo")
    .timeout(Duration.ofSeconds(300))
    .temperature(0.7)
    .build();

OllamaEmbeddingModel embeddingModel = OllamaEmbeddingModel.builder()
    .baseUrl("http://localhost:11434")
    .modelName("bge-m3")
    .timeout(Duration.ofSeconds(120))
    .build();

// 文档分割配置
DocumentSplitter splitter = DocumentSplitters.recursive(
    1000,  // maxSegmentSizeInChars
    200    // maxOverlapSizeInChars
);
```

---

## 常见问题

### Q: GPU 没有被使用怎么办？

检查以下几点：
1. CUDA 库权限: `ls -la /usr/local/lib/ollama/cuda_v12/`
2. 驱动版本: `nvidia-smi`
3. Ollama 日志: 查看 `OLLAMA_DEBUG=1 ollama serve` 输出

### Q: 索引速度太慢怎么办？

1. 确认 GPU 加速已启用
2. 检查 Ollama 模型是否正确加载到 GPU
3. 考虑增加批处理大小

### Q: 如何恢复中断的索引？

系统会自动保存进度，重新运行程序时会从上次保存的位置继续。

---

## 更新日志

- **2026-03-18**: 优化批次大小(5→25)，提升GPU利用率
- **2026-03-18**: 新增IncrementalIndexerOllama增量索引工具
- **2026-03-18**: 完成 GPU 加速配置，启用 CUDA 支持
- **2026-03-18**: 清理项目目录，归档旧文件
- **2026-03-18**: 创建技术文档

---

## 联系方式

如有问题，请在项目仓库提交 Issue。

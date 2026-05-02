# AI 论文前沿洞察系统

基于 [Langchain-Chatchat](https://github.com/chatchat-space/Langchain-Chatchat) v0.3.1.3 二次开发。每日自动抓取 arXiv 最新论文（标题 + 摘要），存入 FAISS 向量知识库，通过 RAG 问答检索，支持时间范围过滤和 Cross-Encoder 重排序。

## 快速开始

### 环境要求

- Windows 11，Python 3.11.9
- DeepSeek API Key（LLM）
- SiliconFlow API Key（Embedding）

### 安装

```powershell
cd Langchain-Chatchat\libs\chatchat-server
.venv\Scripts\python -m pip install -r requirements.txt
```

### 配置文件

在 `chatchat_data\` 下创建 `model_settings.yaml`，填写 API 密钥：

```yaml
MODEL_PLATFORMS:
  - platform_name: deepseek
    platform_type: openai
    api_base_url: https://api.deepseek.com/v1
    api_key: <your-deepseek-api-key>
    llm_models:
      - deepseek-chat
  - platform_name: siliconflow
    platform_type: openai
    api_base_url: https://api.siliconflow.cn/v1
    api_key: <your-siliconflow-api-key>
    embed_models:
      - BAAI/bge-m3
```

其余配置文件（`kb_settings.yaml`、`basic_settings.yaml`、`prompt_settings.yaml`）使用项目中已有的即可。

### 启动

**Terminal 1 — API 服务（端口 7861）：**

```powershell
$env:CHATCHAT_ROOT = "D:\MyProject\chatchat_data"
cd D:\MyProject\Langchain-Chatchat\libs\chatchat-server
.venv\Scripts\python chatchat\startup.py --api
```

**Terminal 2 — WebUI（端口 8501），等 API 显示 "Uvicorn running" 后：**

```powershell
$env:CHATCHAT_ROOT = "D:\MyProject\chatchat_data"
cd D:\MyProject\Langchain-Chatchat\libs\chatchat-server
.venv\Scripts\python chatchat\startup.py --webui
```

浏览器打开 `http://127.0.0.1:8501`，选择 "RAG 对话" 页面。

### 抓取论文

- **WebUI 手动触发**：侧边栏输入起始日期（YYYYMMDD），点击触发按钮
- **命令行**：
  ```powershell
  cd Langchain-Chatchat\libs\chatchat-server
  .venv\Scripts\python -m chatchat.crawlers.pipeline --since 20260101
  ```
- **每日自动**：Windows 计划任务 `ArXivDailyCrawl`，每日 8:00 执行

## 数据流

```
arXiv API → crawlers/pipeline.py → FAISS 向量库 → RAG 问答
                │                        │
                ▼                        ▼
          data/papers/raw/          chatchat_data/
          (原始 XML)                (向量索引 + metadata)
```

## 核心特性

- **智能时间过滤**：支持"最近三个月"、"2025年"等自然语言时间范围
- **Cross-Encoder 重排序**：可选启用 `BAAI/bge-reranker-base`，提升检索精度
- **跨语言检索**：中文查询自动翻译为英文，解决中英跨语言匹配问题
- **增量抓取**：按 arXiv 分类记录最后抓取日期，支持断点续传
- **数据去重**：O(1) 去重索引，防止重复入库

## 项目结构

```
D:\MyProject\
├── Langchain-Chatchat\          # 原项目（二次开发基底）
│   └── libs\chatchat-server\chatchat\
│       ├── crawlers\            # 论文爬虫（arXiv API → FAISS）
│       ├── server\
│       │   ├── chat\kb_chat.py  # RAG 对话核心逻辑
│       │   ├── knowledge_base\  # FAISS 向量检索引擎
│       │   └── reranker\        # Cross-Encoder 重排序
│       └── settings.py          # 追加 arXiv/Reranker 配置
├── chatchat_data\               # 知识库数据 + YAML 配置
└── scripts\daily_crawl.bat      # 计划任务入口
```

## 配置项说明

`kb_settings.yaml` 中可调整的关键参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_SEARCH_TOP_K` | 10 | 检索粗排候选数 |
| `USE_RERANKER` | True | 启用 Cross-Encoder 重排序 |
| `RERANKER_TOP_N` | 5 | 重排序后送入 LLM 的论文数 |
| `ARXIV_CATEGORIES` | cs.AI/CL/CV/IR/LG | 抓取分类 |

## License

本项目基于 Langchain-Chatchat（Apache 2.0）二次开发。

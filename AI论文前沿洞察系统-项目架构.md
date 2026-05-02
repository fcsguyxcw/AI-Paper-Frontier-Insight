# AI 论文前沿洞察系统

> 基于 Langchain-Chatchat v0.3.1.3 二次开发
> 数据源：arXiv API | 存储：FAISS 向量库 | 框架：LangChain + FastAPI

---

## 项目目标

每日自动抓取 arXiv 最新论文（标题 + 摘要 + 元数据），存入向量知识库。用户通过 RAG 问答方式检索论文，支持按时间范围过滤（如"最近三个月"），解决手动翻阅海量文献的痛点。

---

## 数据流

```
arXiv API ──▶ crawlers/pipeline.py ──▶ FAISS 向量库 ──▶ RAG 问答
                 │                          │
                 ▼                          ▼
           data/papers/raw/           chatchat_data/
           (原始 XML)                  (向量索引 + metadata)
```

## 核心 RAG 链路

加载论文 → 向量化 → 存储 metadata → 用户提问 → LLM 解析时间范围 → metadata 预过滤 → 语义检索 → 拼装 Prompt → LLM 生成

---

## 目录结构

```
D:\MyProject\
│
├── Langchain-Chatchat\                    # 原项目（二次开发基底）
│   └── libs\chatchat-server\chatchat\
│       ├── crawlers\                      # 【新增】论文爬虫
│       │   ├── __init__.py
│       │   ├── base.py                    # BaseCrawler 基类（缓存、限速、日志）
│       │   ├── arxiv_crawler.py           # arXiv API 查询 + Atom XML 解析
│       │   └── pipeline.py               # ETL 编排 → 去重 → 清洗 → 入库
│       │
│       ├── server\
│       │   ├── knowledge_base\
│       │   │   ├── kb_service\
│       │   │   │   ├── base.py            # 【改造】KBService.do_search +filter 参数
│       │   │   │   └── faiss_kb_service.py # 【改造】透传 filter 到 FAISS 检索
│       │   │   └── kb_doc_api.py          # 【改造】search_docs 透传 metadata
│       │   │
│       │   ├── chat\
│       │   │   └── kb_chat.py             # 【改造】LLM 解析时间 → 构建 filter
│       │   │
│       │   └── reranker\
│       │       └── reranker.py            # 【已集成】Cross-Encoder 重排序
│       │
│       └── settings.py                   # 【改造】追加 arXiv 配置
│
├── chatchat_data\                         # 知识库数据目录
│
├── scripts\
│   └── daily_crawl.bat                   # 计划任务入口
│
└── 2026-04-26项目架构.txt                 # 前期分析文档（保留参考）
```

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 数据源 | 仅 arXiv API | PapersWithCode 无官方 API，arXiv 覆盖绝大多数 CS/AI 论文 |
| 论文内容 | 标题 + 摘要，不提取 Conclusion | arXiv API 不暴露结论，PDF 解析太重 |
| 向量库 | FAISS（复用项目默认） | 轻量、无需额外部署、支持 metadata 过滤 |
| 时间过滤 | metadata 预过滤 + 向量检索 | FAISS 支持 filter 参数，比 post-filter 准确 |
| 检索增强 | Cross-Encoder Reranker 已集成，Settings 控制 | 安装 sentence-transformers 即可启用 |
| 前端 | 复用原项目 Streamlit 对话页 + 侧边栏抓取按钮 | 不新增前端代码，仅加功能按钮 |
| 增量策略 | 按 arXiv 分类记录最后抓取日期 + O(1) 去重索引 | 断点续传、原子写入、损坏自愈 |
| 调度 | Windows 计划任务 + WebUI 手动触发 | 用户环境为 Windows 11 |

---

## 改造文件清单

### 新增文件（4 个）

| 文件 | 说明 |
|------|------|
| `crawlers/__init__.py` | 包声明 |
| `crawlers/base.py` | BaseCrawler 基类（请求、缓存、限速） |
| `crawlers/arxiv_crawler.py` | arXiv API 查询、响应解析、论文提取 |
| `crawlers/pipeline.py` | ETL 编排：抓取 → 去重 → 清洗 → 入库 |

### 改造文件（10 个）

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `settings.py` | +15 行 | arXiv 配置（4项）+ Reranker 配置（4项） |
| `kb_service/base.py` | 1 行 | `do_search` 签名加 `filter` 参数 |
| `faiss_kb_service.py` | +20 行 | `do_search` + `_build_filter_fn` |
| `kb_doc_api.py` | 8 行 | `search_docs` 透传 metadata + 元组兼容 |
| `kb_chat.py` | +50 行 | `parse_time_filter`（中文数字）+ Reranker 集成 + JSON 修复 |
| `server/utils.py` | +30 行 | `embedding_device()` + `get_httpx_client` IPv6 修复 |
| `server/api_server/kb_routes.py` | +15 行 | `trigger_crawl` 端点 |
| `webui.py` | +8 行 | 侧边栏抓取按钮 |
| `webui_pages/utils.py` | +15 行 | `trigger_crawl()` API 方法 + None 安全 |
| `webui_pages/kb_chat.py` | 2 行 | `e.body` 安全访问 |

### 不动但需要了解的已有文件

| 文件 | 用途 |
|------|------|
| `reranker/reranker.py` | Cross-Encoder 重排序，已集成到 kb_chat，通过 `USE_RERANKER` 开关控制 |
| `knowledge_base/utils.py` | `KnowledgeFile` 等工具类，ETL 入库时使用 |
| `server/utils.py` | `get_ChatOpenAI`、`get_default_llm` 等 |

---

## 爬虫设计

### arXiv API

- 端点：`https://export.arxiv.org/api/query`
- 格式：Atom XML（`feed.entry` 列表）
- 分类范围：`cs.AI`, `cs.CL`, `cs.CV`, `cs.IR`, `cs.LG`（可在 settings 配置）
- 限速：每 3 秒 1 次（arXiv 硬性要求）
- 分页：`PAGE_SIZE=100`，通过 `start` 参数循环获取全部结果
- 重试：`base.py` 指数退避（最多 3 次，等待 2^n * delay 秒）
- 断点续传：每分类完成后立即落盘 `state.json`，中断后从断点继续

### 数据模型

每篇论文结构化后：

```python
{
    "arxiv_id": "2305.12345",       # 唯一标识，用于去重
    "title": "Paper Title",
    "abstract": "全文摘要...",
    "authors": ["Alice", "Bob"],
    "categories": ["cs.IR", "cs.CL"],
    "published": "2026-01-15",      # 时间过滤字段
    "updated": "2026-02-10",
    "pdf_url": "http://arxiv.org/pdf/2305.12345",
    "arxiv_url": "http://arxiv.org/abs/2305.12345"
}
```

向量库中 `page_content = title + "\n\n" + abstract`，其余字段存入 `metadata`。

### 增量策略

1. `state.json` 记录每个分类的最后成功抓取日期（原子写入，损坏自动恢复）
2. 每次抓取查询 `submittedDate` 从上次日期到当前日期（支持 `--since YYYYMMDD` 自定义起始日期）
3. 已入库论文通过 `ingested_ids.json` O(1) 查重（损坏自动从 FAISS docstore 重建）

---

## RAG 时间过滤机制

```
用户提问: "最近三个月提升 RAG 召回率的论文"
       │
       ▼
  LLM 解析 → 提取时间范围 → { published: { $gte: "2026-01-29" } }
       │
       ▼
  kb_chat.py → search_docs(metadata=filter_dict)
       │
       ▼
  kb_doc_api.py → KBService.search_docs(query, top_k, filter)
       │
       ▼
  FaissKBService.do_search(query, top_k, filter)
       │
       ▼
  vs.similarity_search_with_score(query, k, filter=filter_fn)
       │
       ▼
  结果送入 LLM → 生成问答
```

---

## 实施步骤

1. **改造基础链**：settings.py → base.py → faiss_kb_service.py → kb_doc_api.py（使 metadata 过滤可达 FAISS）
2. **新增爬虫**：base.py → arxiv_crawler.py → pipeline.py
3. **改造搜索**：kb_chat.py（时间解析 + 中文数字 → 构建 filter）
4. **集成 Reranker**：kb_chat.py reranker 代码块 + server/utils.py `embedding_device()`
5. **WebUI 触发**：kb_routes.py 端点 + webui.py 侧边栏按钮
6. **验证**：手动触发抓取（329 篇），测试"最近三个月"查询（端到端通过）
7. **部署**：daily_crawl.bat + Windows 计划任务

---

## 注意事项

- FAISS metadata 过滤在 `similarity_search_with_score` 层实现，调用链已完整透传
- arXiv API 首次全量抓取耗时较长（限速 3s/req），可通过 WebUI 按钮或命令行触发
- `--since YYYYMMDD` 参数支持回溯任意时间段，不指定则增量抓取
- 启动服务必须先 API（`--api`）后 WebUI（`--webui`），两个终端都要设 `CHATCHAT_ROOT`
- 代理用户需注意 httpx 代理绕过已修复（IPv4 localhost + IPv6 `::1`）
- Reranker 默认关闭，需 `sentence-transformers` 库 + `USE_RERANKER=True`
- Python 版本要求 >=3.10, <3.12
- 依赖管理使用 Poetry

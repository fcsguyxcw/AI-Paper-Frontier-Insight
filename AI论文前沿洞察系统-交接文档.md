# AI 论文前沿洞察系统 — 交接文档

> 更新日期：2026-05-01
> 项目状态：**全功能可用（端到端验证通过）**
> 基底项目：Langchain-Chatchat v0.3.1.3

---

## 一、已完成工作

### Phase 0：环境搭建（✅ 完成）

| 项目 | 说明 |
|------|------|
| Python 版本 | 安装 **Python 3.11.9**，与系统原有 3.13 共存 |
| 依赖安装 | Poetry 安装全部 191 个依赖包 |
| 虚拟环境路径 | `Langchain-Chatchat\libs\chatchat-server\.venv\` |
| 配置文件 | `chatchat_data\` 下的 YAML（model/kb/basic settings） |

**注意：** 原始 `pandas ~1.3.0` 无 Python 3.11 wheel，已修改为 `>=1.3.0,<2.0.0`（pyproject.toml L50）。

### Phase 1：爬虫系统（✅ 已验证，2026-04-30 全流程测试通过）

| 文件 | 说明 | 状态 |
|------|------|------|
| `chatchat/crawlers/base.py` | BaseCrawler 基类：HTTP 会话管理、请求缓存、限速、状态持久化 | 已验证 |
| `chatchat/crawlers/arxiv_crawler.py` | arXiv API 爬虫：按分类+时间范围查询、Atom XML 解析、增量/全量模式 | 已验证 |
| `chatchat/crawlers/pipeline.py` | ETL 管线：自动创建知识库、抓取→去重→`do_add_doc` 入库、增量状态追踪 | 已验证（含 bugfix） |
| `chatchat/crawlers/__init__.py` | 包声明 | 已验证 |

**已验证的能力：**
- ✅ arXiv API 直连/代理均可达
- ✅ 5 个分类（cs.AI/CL/CV/IR/LG）数据抓取成功
- ✅ XML 原始数据缓存正常
- ✅ 跨分类去重
- ✅ Embedding 通过 SiliconFlow API（`BAAI/bge-m3`）入库
- ✅ 分批入库（SiliconFlow 限制 64 条/批）
- ✅ FAISS 向量库保存（`index.faiss` + `index.pkl`）
- ✅ `state.json` 增量状态记录

**Bugfix 记录：**

| Bug | 原因 | 修复 |
|-----|------|------|
| `add_kb_to_db() missing 1 required positional argument: 'embed_model'` | 调用签名缺 `kb_info` 参数 | pipeline.py 改为关键字传参 |
| `UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'` | Windows GBK 终端不支持 ✓ | 替换为 `[OK]` |
| `input batch size 100 > maximum allowed batch size 64` | SiliconFlow API 批量限制 | pipeline.py 拆 64 条/批 |
| `'tuple' object has no attribute 'metadata'` | FAISS filter 路径返回 `(doc, score)` 元组 | `kb_doc_api.py` 加 `isinstance(x, tuple)` 判断 |
| 非流式响应 JSON 双重编码 | FastAPI 包装已序列化的 JSON 字符串 | `return json.loads(result)` |
| `sqlite3.OperationalError: unable to open database file` | SQLite URI 用了 Windows 反斜杠 | `basic_settings.yaml` 路径改为正斜杠 |
| `TypeError: 'NoneType' object is not iterable` (WebUI) | `::1` IPv6 导致 httpx 代理解析失败 | `get_httpx_client` IPv6 括号处理 + scheme 级代理绕过 |
| `APIConnectionError` → 二次 AttributeError | `e.body` 属性不存在 | 改为 `getattr(e, "body", str(e))` |
| `kb_routes.py: NameError: Body` | 触发抓取端点缺少导入 | 添加 `Body` 到 imports |
| `embedding_device` 未定义 | Reranker 集成代码引用不存在的函数 | 在 `server/utils.py` 新增 `embedding_device()` |

### Phase 2：Settings 配置（✅ 已编码 + 审计修复）

KBSettings 追加了 10 个配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ARXIV_CATEGORIES` | `["cs.AI","cs.CL","cs.CV","cs.IR","cs.LG"]` | 抓取分类列表 |
| `ARXIV_MAX_RESULTS_PER_CATEGORY` | `1000` | 每分类单次最大结果数（从 100 提高） |
| `ARXIV_CRAWL_INTERVAL` | `3.0` | API 请求间隔（秒） |
| `ARXIV_PAPER_KB_NAME` | `"arxiv_papers"` | 论文知识库名称 |
| `USE_RERANKER` | `False` | 是否启用 Cross-Encoder 重排序 |
| `RERANKER_MODEL` | `"BAAI/bge-reranker-base"` | Reranker 模型名称 |
| `RERANKER_MAX_LENGTH` | `1024` | 重排序最大 token 数 |
| `RERANKER_TOP_N` | `3` | 重排序后保留 Top N |

### Phase 3：检索链 metadata 过滤（✅ 已编码）

**改动链路（3 个核心文件 + 7 个兼容性修改）：**

```
kb_chat.py  →  kb_doc_api.py  →  KBService.search_docs()  →  KBService.do_search()
                                                                       ↓
                                                          FaissKBService.do_search()
                                                                       ↓
                                              vs.similarity_search_with_score(filter=fn)
```

- `kb_chat.py`：新增 `parse_time_filter()` 函数，支持 "最近N个月/年"（含中文数字：三→3、十二→12）、"YYYY年" 三种格式。`NUMERAL_MAP` + `_to_int()` 转换中文数字
- `kb_doc_api.py`：将 `metadata` 参数透传到 `KBService.search_docs(filter=metadata)`
- `base.py`：`search_docs` 和 `do_search` 签名加 `filter` 参数
- `faiss_kb_service.py`：实现 `_build_filter_fn()`，支持 `$gte`/`$lte`/`$gt`/`$lt` 操作符
- 其余 7 个 KBService 子类：`do_search` 加 `**kwargs` 兼容

### Phase 4：Reranker（✅ 已集成，通过 Settings 控制）

`LangchainReranker`（基于 sentence-transformers CrossEncoder）已完整集成到 RAG 链路。安装 `sentence-transformers` 后，在 `kb_settings.yaml` 或 `settings.py` 中设置 `USE_RERANKER: True` 即可启用。重排序在语义检索后、LLM 生成前执行，将 Top-K 结果精排为 Top-N。

集成链路：`kb_chat.py` → `LangchainReranker.compress_documents()` → 结果回写 docs dict → 构建 context。

添加了 `embedding_device()` 工具函数（`server/utils.py`）自动检测 CUDA/CPU。

---

## 二、项目架构

```
D:\MyProject\
│
├── AI论文前沿洞察系统-项目架构.md       # 架构设计文档
│
├── Langchain-Chatchat\                   # 基底项目
│   ├── libs\chatchat-server\chatchat\
│   │   ├── crawlers\                     # 【新增】论文爬虫
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── arxiv_crawler.py
│   │   │   ├── pipeline.py
│   │   │   └── parsers\                  # 其他解析器
│   │   │
│   │   ├── server\
│   │   │   ├── chat\kb_chat.py           # 【改造】时间解析 + metadata 过滤
│   │   │   ├── knowledge_base\
│   │   │   │   ├── kb_doc_api.py         # 【改造】透传 metadata
│   │   │   │   └── kb_service\
│   │   │   │       ├── base.py           # 【改造】do_search +filter
│   │   │   │       └── faiss_kb_service.py # 【改造】_build_filter_fn
│   │   │   └── reranker\reranker.py      # 已有，未启用
│   │   │
│   │   └── settings.py                   # 【改造】追加 arXiv 配置
│   │
│   ├── libs\data\papers\                 # 爬虫缓存与状态（实际位置）
│   │   ├── raw\                          # arXiv 原始 XML 缓存
│   │   └── state.json                    # 增量抓取状态
│   │
│   └── scripts\daily_crawl.bat           # 计划任务入口
│
├── chatchat_data\                        # 知识库数据目录（CHATCHAT_ROOT）
│   ├── *.yaml                            # 各项配置
│   └── data\knowledge_base\
│       └── arxiv_papers\                 # arXiv 论文知识库
│           └── vector_store\BAAI\bge-m3\
│               ├── index.faiss
│               └── index.pkl
│
└── .claude\                              # Claude Code 配置与记忆
```

### 数据流

```
arXiv API  →  arxiv_crawler.py  →  pipeline.py  →  SiliconFlow Embedding  →  FAISS 向量库
                  │                              │
                  ▼                              ▼
            libs/data/papers/raw/          libs/data/papers/
            (XML 缓存)                      state.json (增量状态)
```

### 环境变量

- `CHATCHAT_ROOT` — 必须设为 `D:\MyProject\chatchat_data`（读取 YAML 配置和知识库路径）

---

## 三、TODO 列表

### 优先级 P0：验证已编码功能（✅ 全部完成）

- [x] 安装依赖：Python 3.11 + Poetry 全部 191 个包
- [x] 创建知识库：pipeline 自动创建 `arxiv_papers` 知识库
- [x] 测试全量抓取：5 个分类共 329 篇论文入库（2026-05-01）
- [x] 测试时间过滤查询：
  - [x] 输入 "找一下最近三个月关于数据胶囊的论文"
  - [x] `parse_time_filter` 正确返回 `{"published": {"$gte": "2026-02-01"}}`
  - [x] search_docs 带 metadata filter 调用
  - [x] FAISS 过滤函数生效（`_build_filter_fn`）

### 优先级 P1：完善爬虫（✅ 全部完成）

- [x] arXiv API 分页：`PAGE_SIZE=100`，通过 `start` 参数循环获取所有结果
- [x] 错误重试：`base.py` 指数退避重试（最多 3 次），断点续传（每分类完成后立即落盘）
- [x] 去重优化：`ingested_ids.json` 本地索引 O(1) 查重，FAISS 重建为降级方案
- [x] 增加 `--since YYYYMMDD` 参数，支持回溯任意时间段

### 优先级 P2：检索增强（✅ 完成）

- [x] 启用 Reranker：完整集成到 `kb_chat.py`，通过 `Settings.kb_settings.USE_RERANKER` 控制
- [x] 添加 `embedding_device()` 函数自动检测 CUDA/CPU

### 优先级 P3：部署（✅ 完成）

- [x] `daily_crawl.bat`：stderr 重定向、日志目录自动创建、时间戳日志
  - `schtasks /create /tn "ArxivPaperCrawl" /tr "D:\MyProject\Langchain-Chatchat\scripts\daily_crawl.bat" /sc daily /st 09:00`
- [x] WebUI 集成：侧边栏「触发抓取」按钮 + API 端点 `POST /knowledge_base/trigger_crawl`
- [x] LLM 模型配置：deepseek-chat 已验证可用

### 审计修复（2026-05-01）

- [x] `kb_routes.py` 缺少 `Body` 导入 → API 启动崩溃
- [x] `embedding_device()` 函数缺失 → Reranker 静默失败
- [x] Proxy IPv6 `::1` 导致 httpx 连接崩溃 → WebUI 无法访问 API
- [x] `e.body` 在 APIConnectionError 上触发二次崩溃 → WebUI 白屏
- [x] `list_knowledge_bases()` 返回 None 导致页面 TypeError
- [x] Pipeline 状态文件损坏无容错、非原子写入
- [x] `full_crawl` 后不保存去重 ID

### 清理工作（可选）

- [ ] 删除 `chatchat/server/agent/` 等无关模块（精简项目体积）
- [ ] 删除原项目 Streamlit 前端中不需要的页面

---

## 四、关键文件索引

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `crawlers/base.py` | ~95 | BaseCrawler 基类（含指数退避重试） |
| `crawlers/arxiv_crawler.py` | ~170 | arXiv API 爬虫（含分页） |
| `crawlers/pipeline.py` | ~200 | ETL 管线（含分批入库、去重优化、断点续传、--since 参数） |
| `scripts/daily_crawl.bat` | ~18 | Windows 计划任务（含日志） |
| `AI论文前沿洞察系统-项目架构.md` | ~195 | 架构设计文档 |

### 改造文件

| 文件 | 关键行 |
|------|--------|
| `settings.py` | `KBSettings`：`ARXIV_*` (4项) + `RERANKER_*` (4项) |
| `server/api_server/kb_routes.py` | 新增 `POST /knowledge_base/trigger_crawl` 端点 |
| `server/utils.py` | 新增 `embedding_device()`；修复 `get_httpx_client` IPv6 代理绕过 |
| `kb_service/base.py` | `search_docs`、`do_search` 加 `filter` 参数 |
| `faiss_kb_service.py` | `do_search` (L66), `_build_filter_fn` (L87) |
| `kb_doc_api.py` | `search_docs` 透传 metadata；元组兼容处理 |
| `kb_chat.py` | `parse_time_filter` (中文数字)、reranker 集成、JSON 双重编码修复 |
| `webui.py` | 侧边栏 arXiv 抓取按钮 |
| `webui_pages/utils.py` | `trigger_crawl()`、`list_knowledge_bases()` None 安全 |
| `webui_pages/kb_chat.py` | `e.body` 安全访问 |
| `webui_pages/dialogue/dialogue.py` | `e.body` 安全访问 |
| `pyproject.toml` (chatchat-server) | `pandas` 放宽为 `>=1.3.0,<2.0.0` |

---

## 五、注意事项

1. **Python 环境**：项目使用 **Python 3.11.9**（`.venv` 在 `libs\chatchat-server\.venv\`），系统全局为 3.13，互不影响
2. **CHATCHAT_ROOT**：运行前必须设环境变量 `CHATCHAT_ROOT=D:\MyProject\chatchat_data`
3. **arXiv API 限速**：每 3 秒 1 次，首次全量抓取可能需要数分钟。使用 `--since` 参数可回溯任意时间段
4. **代理配置**：用户环境有代理 `http://127.0.0.1:7890`，已修复 httpx 对本地地址（127.0.0.1/localhost）的代理绕过，包括 IPv6 `::1` 处理
5. **时间过滤**：规则式实现，支持中文 "最近N个月/年"（N 含中文数字零~十）和 "YYYY年" 格式
6. **知识库创建**：pipeline.py 会在首次运行时自动创建 `arxiv_papers` 知识库，embedding 通过 SiliconFlow API（`BAAI/bge-m3`）。`samples` 知识库需手动初始化 vector_store
7. **Embedding 批量限制**：SiliconFlow API 每批最多 64 条，pipeline.py 中已做分批处理。FAISS 索引在每批次后保存（非增量保存），大抓取可考虑传 `not_refresh_vs_cache=True`
8. **Reranker**：代码已集成，需安装 `sentence-transformers` 并设置 `USE_RERANKER=True` 启用
9. **WebUI 抓取按钮**：API + WebUI 必须同时运行才能使用侧边栏按钮。抓取在后台线程执行，不阻塞界面
10. **启动顺序**：必须先启动 API（`--api`），看到 "Uvicorn running" 后再启动 WebUI（`--webui`）
11. **Windows 终端编码**：避免在 print 中使用 Unicode 字符，否则 GBK 编码会报错
12. **Poetry Windows 兼容**：WindowsApps 路径下的 Python 存根会干扰 Poetry，需要 PATH 中优先使用 Python 3.11 的目录

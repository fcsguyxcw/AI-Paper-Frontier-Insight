# AI Paper Frontier Insight System

Based on Langchain-Chatchat v0.3.1.3. ArXiv paper crawler + FAISS RAG + Streamlit WebUI.

## Environment

- OS: Windows 11, Python 3.11.9 in `.venv` at `Langchain-Chatchat/libs/chatchat-server/.venv/`
- `CHATCHAT_ROOT` must be `D:\MyProject\chatchat_data` before any command
- Proxy: `http://127.0.0.1:7890` (httpx localhost bypass fixed — works)

## Startup

```powershell
# Terminal 1 — API (port 7861)
$env:CHATCHAT_ROOT = "D:\MyProject\chatchat_data"
cd D:\MyProject\Langchain-Chatchat\libs\chatchat-server
.venv\Scripts\python chatchat\startup.py --api

# Terminal 2 — WebUI (port 8501), only after API shows "Uvicorn running"
$env:CHATCHAT_ROOT = "D:\MyProject\chatchat_data"
cd D:\MyProject\Langchain-Chatchat\libs\chatchat-server
.venv\Scripts\python chatchat\startup.py --webui
```

## Key paths

| What | Where |
|------|-------|
| Project root | `D:\MyProject\` |
| Source code | `D:\MyProject\Langchain-Chatchat\libs\chatchat-server\chatchat\` |
| Config/data | `D:\MyProject\chatchat_data\` |
| FAISS index | `D:\MyProject\chatchat_data\data\knowledge_base\arxiv_papers\vector_store\` |
| Crawler state | `D:\MyProject\Langchain-Chatchat\data\papers\state.json` |
| Logs | `D:\MyProject\Langchain-Chatchat\logs\` |
| Docs | `D:\MyProject\AI论文前沿洞察系统-交接文档.md` (handover), `D:\MyProject\AI论文前沿洞察系统-项目架构.md` (architecture) |

## Core subsystems

- **Crawler**: `chatchat/crawlers/pipeline.py` — arXiv ETL, supports `--since YYYYMMDD` and `--full`
- **RAG chat**: `chatchat/server/chat/kb_chat.py` — time filter + reranker + LLM generation
- **FAISS search**: `chatchat/server/knowledge_base/kb_service/faiss_kb_service.py` — metadata filter with `$gte/$lte`
- **WebUI**: `chatchat/webui.py` — sidebar has crawl trigger button
- **API routes**: `chatchat/server/api_server/kb_routes.py` — `/knowledge_base/trigger_crawl` endpoint

## Model platforms

- **LLM**: DeepSeek (`deepseek-chat`) via `https://api.deepseek.com/v1`
- **Embedding**: SiliconFlow (`BAAI/bge-m3`) via `https://api.siliconflow.cn/v1`
- **Reranker**: `BAAI/bge-reranker-base` (off by default, needs `sentence-transformers`)

## Important

- `API_SERVER.host` is `127.0.0.1` — WebUI connects locally via httpx to API
- Start API first, WebUI second. Both terminals need `$env:CHATCHAT_ROOT`.
- Crawler writes atomically to `state.json` and `ingested_ids.json` — corruption auto-recovers.
- FAISS `normalize_L2=True` — vectors are unit-length, IP metric used.
- `score_threshold` semantics differ between filtered (raw distance) and non-filtered (ensemble retriever) paths.

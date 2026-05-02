import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from langchain.docstore.document import Document

from chatchat.crawlers.arxiv_crawler import ArxivCrawler
from chatchat.settings import Settings
from chatchat.server.knowledge_base.kb_service.base import (
    KBServiceFactory,
    SupportedVSType,
)
from chatchat.server.db.repository.knowledge_base_repository import add_kb_to_db
from chatchat.server.utils import get_default_embedding


DATA_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "papers"
STATE_FILE = DATA_ROOT / "state.json"
RAW_DIR = DATA_ROOT / "raw"
IDS_FILE = DATA_ROOT / "ingested_ids.json"


class ArxivPipeline:
    """arXiv 论文 ETL 管线：抓取 → 去重 → 清洗 → 入库"""

    def __init__(self):
        self.kb_name = Settings.kb_settings.ARXIV_PAPER_KB_NAME
        self.categories = Settings.kb_settings.ARXIV_CATEGORIES
        self.max_results = Settings.kb_settings.ARXIV_MAX_RESULTS_PER_CATEGORY
        self.delay = Settings.kb_settings.ARXIV_CRAWL_INTERVAL

        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        RAW_DIR.mkdir(parents=True, exist_ok=True)

    def _ensure_kb(self):
        """确保知识库存在，不存在则创建"""
        kb = KBServiceFactory.get_service_by_name(self.kb_name)
        if kb is not None:
            return kb

        embed_model = get_default_embedding()
        add_kb_to_db(kb_name=self.kb_name, kb_info="", vs_type=SupportedVSType.FAISS, embed_model=embed_model)
        kb = KBServiceFactory.get_service(
            self.kb_name, SupportedVSType.FAISS, embed_model,
        )
        kb.create_kb()
        print(f"  [OK] 知识库 '{self.kb_name}' 创建完成")
        return kb

    def _load_state(self) -> Dict[str, str]:
        """加载增量状态：{ category: last_date }"""
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                print(f"  [WARN] state.json 损坏，使用默认日期")
        # 默认抓取最近 3 天
        default_date = (datetime.today() - timedelta(days=3)).strftime("%Y%m%d")
        return {cat: default_date for cat in self.categories}

    def _save_state(self, state: Dict[str, str]):
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(STATE_FILE)  # 原子替换

    def _load_ids(self) -> set:
        """从本地索引加载已入库的 arxiv_id（O(1) 读盘，不遍历 FAISS）"""
        if IDS_FILE.exists():
            try:
                return set(json.loads(IDS_FILE.read_text(encoding="utf-8")))
            except Exception:
                print("  [WARN] ingested_ids.json 损坏，从 FAISS 重建...")
                return self._rebuild_ids()
        return self._rebuild_ids()

    def _save_ids(self, ids: set):
        tmp = IDS_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(sorted(ids), ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(IDS_FILE)  # 原子替换

    def _rebuild_ids(self) -> set:
        """从 FAISS docstore 重建 arxiv_id 索引（仅首次/异常时调用）"""
        kb = KBServiceFactory.get_service_by_name(self.kb_name)
        if kb is None:
            print("  [WARN] 知识库不存在，无法重建 ID 索引")
            return set()
        try:
            with kb.load_vector_store().acquire() as vs:
                ids = {doc.metadata.get("arxiv_id") for doc in vs.docstore._dict.values()
                       if doc.metadata.get("arxiv_id")}
                self._save_ids(ids)
                print(f"  [OK] 从 FAISS 重建 {len(ids)} 个 ID")
                return ids
        except Exception as e:
            print(f"  [ERROR] 从 FAISS 重建 ID 失败: {e}")
            return set()

    def _papers_to_documents(self, papers: List[Dict]) -> List[Document]:
        """将论文结构化数据转为 LangChain Document"""
        docs = []
        for p in papers:
            doc = Document(
                page_content=f"{p['title']}\n\n{p['abstract']}",
                metadata={
                    "arxiv_id": p["arxiv_id"],
                    "title": p["title"],
                    "authors": ",".join(p.get("authors", [])),
                    "categories": ",".join(p.get("categories", [])),
                    "published": p.get("published", ""),
                    "updated": p.get("updated", ""),
                    "pdf_url": p.get("pdf_url", ""),
                    "arxiv_url": p.get("arxiv_url", ""),
                    "source": "arxiv",
                },
            )
            docs.append(doc)
        return docs

    def run(self, full_crawl: bool = False, since: str = None):
        """执行完整 ETL 管线

        Args:
            full_crawl: True=全量抓取（忽略增量状态）
            since:      YYYYMMDD 格式的起始日期，覆盖 state 中的日期
        """
        print("=" * 60)
        print(f"arXiv 论文 ETL 管线 — {datetime.today().strftime('%Y-%m-%d')}")
        print("=" * 60)

        # 1. 确保知识库就绪
        print("\n[1/4] 检查知识库...")
        kb = self._ensure_kb()

        # 2. 加载增量状态
        print("[2/4] 加载抓取状态...")
        state = {} if full_crawl else self._load_state()
        today = datetime.today().strftime("%Y%m%d")
        print(f"     状态: {len(state)} 个分类")

        # 3. 抓取 + 入库
        print("[3/4] 抓取 arXiv 论文...")
        crawler = ArxivCrawler(
            cache_dir=str(RAW_DIR),
            delay=self.delay,
        )
        existing_ids = set() if full_crawl else self._load_ids()
        all_new = []

        for cat in self.categories:
            since_cat = since if since else state.get(
                cat, (datetime.today() - timedelta(days=7)).strftime("%Y%m%d")
            )
            print(f"  [{cat}] since={since_cat}...", end=" ", flush=True)

            papers = crawler.fetch_papers(cat, since_cat, today, self.max_results)
            print(f"{len(papers)} papers", end="", flush=True)

            # 去重
            new_papers = []
            for p in papers:
                if p and p["arxiv_id"] not in existing_ids:
                    existing_ids.add(p["arxiv_id"])
                    new_papers.append(p)

            if new_papers:
                docs = self._papers_to_documents(new_papers)
                # SiliconFlow API 限制每批最多 64 条
                batch_size = 64
                for i in range(0, len(docs), batch_size):
                    batch = docs[i:i + batch_size]
                    kb.do_add_doc(batch)
                all_new.extend(new_papers)
                print(f", {len(new_papers)} new")
            else:
                print(", 0 new")

            state[cat] = today
            # 断点续传：每个分类完成后立即落盘，避免中断丢失进度
            self._save_state(state)

        print(f"\n  总计新增: {len(all_new)} 篇论文")
        self._save_ids(existing_ids)

        # 4. 保存向量索引
        print("[4/4] 保存...")
        kb.save_vector_store()
        print("  索引已保存 [OK]")
        print(f"\n完成！知识库 '{self.kb_name}' 共 {len(all_new)} 篇新增论文")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="arXiv 论文 ETL 管线")
    parser.add_argument("--full", action="store_true", help="全量抓取（忽略增量状态）")
    parser.add_argument("--since", type=str, default=None, help="起始日期 YYYYMMDD，如 20250301")
    args = parser.parse_args()

    pipeline = ArxivPipeline()
    pipeline.run(full_crawl=args.full, since=args.since)

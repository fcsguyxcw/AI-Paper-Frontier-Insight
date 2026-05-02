import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from xml.etree import ElementTree

from chatchat.crawlers.base import BaseCrawler


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
PAGE_SIZE = 100  # arXiv 单次最大返回数


class ArxivCrawler(BaseCrawler):
    """arXiv API 爬虫：按分类和时间范围抓取论文元数据"""

    def __init__(self, cache_dir: str = "", delay: float = 3.0):
        super().__init__(cache_dir=cache_dir, delay=delay)

    def build_query(
        self,
        category: str,
        start_date: str,
        end_date: str,
    ) -> str:
        cat_query = f"cat:{category}"
        date_query = f"submittedDate:[{start_date}0000 TO {end_date}2359]"
        return f"({cat_query})+AND+({date_query})"

    def _parse_total_results(self, xml_text: str) -> int:
        root = ElementTree.fromstring(xml_text)
        total = root.findtext(f"{{{OPENSEARCH_NS}}}totalResults", "0")
        return int(total)

    def fetch_papers(
        self,
        category: str,
        start_date: str,
        end_date: str,
        max_results: int = 1000,
    ) -> List[Dict]:
        """抓取指定分类和时间范围的论文列表（自动分页）"""
        query = self.build_query(category, start_date, end_date)
        all_papers = []

        for start in range(0, max_results, PAGE_SIZE):
            page_size = min(PAGE_SIZE, max_results - start)
            url = f"{ARXIV_API_URL}?search_query={query}&start={start}&max_results={page_size}"
            cache_key = f"arxiv_{category}_{start_date}_{end_date}_p{start}"
            raw = self.fetch(url, cache_key=cache_key)

            if start == 0:
                total = self._parse_total_results(raw)
                if total > PAGE_SIZE:
                    print(f"  [{category}] total={total}, fetching pages... ", end="", flush=True)

            papers = self._parse_response(raw, category)
            all_papers.extend(papers)

            if len(papers) < page_size:
                break

        return all_papers

    def _parse_response(self, xml_text: str, category: str) -> List[Dict]:
        """解析 Atom XML 响应，提取论文信息"""
        root = ElementTree.fromstring(xml_text)
        papers = []

        for entry in root.findall(f"{{{ARXIV_ATOM_NS}}}entry"):
            paper = self._parse_entry(entry)
            if paper:
                papers.append(paper)

        return papers

    def _parse_entry(self, entry) -> Optional[Dict]:
        """解析单篇论文的 Atom Entry"""
        try:
            arxiv_url = entry.findtext(f"{{{ARXIV_ATOM_NS}}}id", "")
            arxiv_id = arxiv_url.strip().split("/")[-1]
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # 去掉版本号

            title = entry.findtext(f"{{{ARXIV_ATOM_NS}}}title", "").strip()
            # arXiv API 的 title 可能包含换行
            title = re.sub(r"\s+", " ", title)

            abstract = entry.findtext(f"{{{ARXIV_ATOM_NS}}}summary", "").strip()
            abstract = re.sub(r"\s+", " ", abstract)

            published = entry.findtext(f"{{{ARXIV_ATOM_NS}}}published", "")[:10]
            updated = entry.findtext(f"{{{ARXIV_ATOM_NS}}}updated", "")[:10]

            # 作者
            authors = []
            for author_elem in entry.findall(f"{{{ARXIV_ATOM_NS}}}author"):
                name = author_elem.findtext(f"{{{ARXIV_ATOM_NS}}}name", "")
                if name:
                    authors.append(name.strip())

            # 分类
            categories = []
            for cat_elem in entry.findall(f"{{{ARXIV_ATOM_NS}}}category"):
                term = cat_elem.get("term", "")
                if term:
                    categories.append(term)

            # PDF 链接
            pdf_url = ""
            for link in entry.findall(f"{{{ARXIV_ATOM_NS}}}link"):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href", "")
                    break

            return {
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "categories": categories,
                "published": published,
                "updated": updated,
                "pdf_url": pdf_url,
                "arxiv_url": arxiv_url,
            }
        except Exception:
            return None

    def crawl(self, categories: List[str], end_date: Optional[str] = None,
              max_results: int = 100) -> List[Dict]:
        """全量抓取入口（兼容基类接口）"""
        end = end_date or datetime.today().strftime("%Y%m%d")
        start = (datetime.today() - timedelta(days=7)).strftime("%Y%m%d")
        all_papers = []
        for cat in categories:
            papers = self.fetch_papers(cat, start, end, max_results)
            all_papers.extend(papers)
        return all_papers

    def crawl_incremental(
        self,
        categories: List[str],
        since_date: str,
        end_date: str,
        max_results: int = 100,
    ) -> List[Dict]:
        """增量抓取：只抓取 since_date 之后的论文"""
        all_papers = []
        seen_ids = set()

        for cat in categories:
            papers = self.fetch_papers(cat, since_date, end_date, max_results)
            for p in papers:
                if p and p["arxiv_id"] not in seen_ids:
                    seen_ids.add(p["arxiv_id"])
                    p["category"] = cat
                    all_papers.append(p)

        return all_papers

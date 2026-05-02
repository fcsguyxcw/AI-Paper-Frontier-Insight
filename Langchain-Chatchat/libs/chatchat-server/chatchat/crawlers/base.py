import hashlib
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

import requests


class BaseCrawler(ABC):
    """爬虫基类：统一的请求管理、缓存、限速"""

    def __init__(self, cache_dir: str = "", delay: float = 1.0):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })
        self.delay = delay
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, url: str, cache_key: str = "", max_retries: int = 3, **kwargs) -> str:
        """带缓存的 HTTP GET，相同 URL 不会重复请求。失败自动指数退避重试。"""
        if not cache_key:
            cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.xml" if self.cache_dir else None

        if cache_path and cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = self.session.get(url, timeout=60, **kwargs)
                resp.raise_for_status()
                resp.encoding = "utf-8"

                if cache_path:
                    cache_path.write_text(resp.text, encoding="utf-8")

                time.sleep(self.delay)
                return resp.text
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = 2 ** attempt * self.delay
                    time.sleep(wait)

        raise last_error

    def save_state(self, path: str, state: Dict):
        Path(path).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_state(self, path: str) -> Dict:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    @abstractmethod
    def crawl(self) -> List[Dict]:
        ...

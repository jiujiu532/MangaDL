"""
漫画源适配器基类
"""
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from abc import ABC, abstractmethod

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def _make_session() -> requests.Session:
    """创建高性能 Session: 连接池 + keep-alive + 自动重试"""
    s = requests.Session()
    s.headers.update(HEADERS)
    # 连接池: pool_connections=每host连接池, pool_maxsize=最大连接数
    # 重试: 3次, 指数退避, 对 500/502/503/504 重试
    retry = Retry(total=3, backoff_factor=0.1,
                  status_forcelist=[500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(
        pool_connections=80,   # 80个host连接池
        pool_maxsize=150,      # 每个host最多150个并发连接
        max_retries=retry,
        pool_block=False,
    )
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


class MangaSource(ABC):
    """漫画源适配器抽象基类"""

    name: str = "Unknown"
    base_url: str = ""
    icon: str = "📖"

    def __init__(self):
        self.session = _make_session()
        if self.base_url:
            self.session.headers["Referer"] = self.base_url

    @abstractmethod
    def search(self, keyword: str) -> list[dict]:
        """搜索漫画 -> [{title, url, cover, genres}]"""
        ...

    @abstractmethod
    def get_manga_info(self, manga_url: str) -> dict:
        """获取漫画详情 -> {title, manga_id, url, cover, description, genres}"""
        ...

    @abstractmethod
    def get_chapters(self, manga_url: str, manga_id: str = None) -> list[dict]:
        """获取章节列表 -> [{title, url, date}]  (正序)"""
        ...

    @abstractmethod
    def get_chapter_images(self, chapter_url: str) -> list[str]:
        """获取章节图片URL列表"""
        ...

    def get_popular(self, page: int = 1) -> list[dict]:
        """获取热门漫画列表 -> [{title, url, cover, genres}]"""
        return []

    def get_latest(self, page: int = 1) -> list[dict]:
        """获取最新漫画列表 -> [{title, url, cover, genres}]"""
        return []

    def download_image(self, url: str, timeout: int = 10) -> bytes | None:
        """直接下载图片数据 (使用连接池, keep-alive)"""
        try:
            resp = self.session.get(url, timeout=(2, timeout))
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

    def download_image_to_file(self, url: str, path: str, timeout: int = 10) -> int:
        """流式下载图片直写磁盘，返回字节数。失败抛异常。"""
        resp = self.session.get(url, timeout=(2, timeout), stream=True)
        resp.raise_for_status()
        size = 0
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(32768):
                f.write(chunk)
                size += len(chunk)
        if size < 50:
            os.remove(tmp)
            raise ValueError("Image too small")
        os.replace(tmp, path)
        return size

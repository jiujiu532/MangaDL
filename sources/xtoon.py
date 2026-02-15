"""
t2.xtoon2.com 适配器 (韩国漫画站)
使用 MCCMS 系统, CDN: xtoon2.b-cdn.net
"""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
from .base import MangaSource


class XToonSource(MangaSource):
    name = "XToon"
    base_url = "https://t2.xtoon2.com"
    icon = "🇰🇷"

    # ---------- 工具方法 ----------
    def _parse_katoon_boxes(self, soup) -> list[dict]:
        """解析 .katoon-box 列表项 (用于首页 / 搜索 / 分类页)"""
        results = []
        seen = set()
        for box in soup.select(".katoon-box"):
            a = box.select_one("a.img-box[href*='/comic/']")
            if not a:
                continue
            href = a.get("href", "")
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if full in seen:
                continue
            seen.add(full)

            # 标题: 优先取 <h6> 兄弟, 次取 <img alt>
            title = ""
            h6 = box.select_one("h6")
            if h6:
                # 去掉 <span class="up">UP</span> 和 <span class="ad">AD</span>
                for span in h6.select("span"):
                    span.decompose()
                title = h6.text.strip()
            if not title:
                img = a.select_one("img")
                if img:
                    title = (img.get("alt") or "").strip()
            if not title or len(title) < 2:
                continue

            # 封面: <img data-original="...">
            cover = None
            img = a.select_one("img")
            if img:
                cover = img.get("data-original") or img.get("data-src") or ""
                if cover and not cover.startswith("http"):
                    cover = urljoin(self.base_url, cover)
                if cover and ("bg_loadimg" in cover or "bg_detail" in cover):
                    cover = None

            results.append({
                "title": title, "url": full, "cover": cover, "genres": "",
            })
        return results

    # ---------- 搜索 ----------
    def search(self, keyword: str) -> list[dict]:
        # 使用 /category/search 端点
        url = f"{self.base_url}/category/search?keyword={quote(keyword)}"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_katoon_boxes(soup)

    # ---------- 首页 / 热门 / 最新 ----------
    def _parse_homepage(self) -> list[dict]:
        resp = self.session.get(self.base_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_katoon_boxes(soup)[:24]

    def get_popular(self, page: int = 1) -> list[dict]:
        if page > 1: return []  # 只有首页数据
        return self._parse_homepage()

    def get_latest(self, page: int = 1) -> list[dict]:
        if page > 1: return []
        return self._parse_homepage()

    # ---------- 漫画信息 ----------
    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 标题: <title>무선 연결 오나홀 - Xtoon</title> 或 <h4>
        title = ""
        title_tag = soup.select_one("title")
        if title_tag:
            title = re.sub(r'\s*-\s*[Xx][Tt]oon\s*$', '', title_tag.text.strip())
        if not title:
            h4 = soup.select_one("h4.fw-bold")
            if h4:
                # 去掉 <span class="up">19</span>
                for span in h4.select("span"):
                    span.decompose()
                title = h4.text.strip()

        # 封面: .toon-img img
        cover = None
        cover_el = soup.select_one(".toon-img img, .katoon-info img")
        if cover_el:
            cover = cover_el.get("data-original") or cover_el.get("src") or ""
            if cover and not cover.startswith("http"):
                cover = urljoin(self.base_url, cover)

        # 描述
        desc = ""
        info_div = soup.select_one(".katoon-info")
        if info_div:
            small = info_div.select_one("small")
            if small:
                desc = small.text.strip()

        return {
            "title": title, "manga_id": None, "url": manga_url,
            "cover": cover, "description": desc, "genres": "",
        }

    # ---------- 章节列表 ----------
    def get_chapters(self, manga_url: str, manga_id: str = None) -> list[dict]:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        chapters = []
        seen = set()
        for a in soup.select(".chapter-list-item"):
            href = a.get("href", "")
            if not href:
                continue
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if full in seen:
                continue
            seen.add(full)

            # 标题: <strong> 里面提取纯文字 (如 "75화")
            strong = a.select_one("strong")
            title = ""
            if strong:
                for child in strong.children:
                    if isinstance(child, str):
                        title += child.strip()
                    elif child.name == "i":
                        continue
                    elif hasattr(child, 'get') and "pnum" in (child.get("class") or []):
                        continue
                    elif hasattr(child, 'get') and "pup" in (child.get("class") or []):
                        continue
            title = title.strip() or full.split("/")[-1]

            # 日期
            date_el = a.select_one("small.text-secondary")
            date = date_el.text.strip() if date_el else ""

            chapters.append({"title": title, "url": full, "date": date})

        # 排除 "첫 화 보기" (第一话快捷链接)
        chapters = [c for c in chapters if "첫 화" not in c["title"] and "첫화" not in c["title"]]

        # 默认倒序 → 翻转成正序
        chapters.reverse()
        return chapters

    # ---------- 章节图片 ----------
    def get_chapter_images(self, chapter_url: str) -> list[str]:
        resp = self.session.get(chapter_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        images = []
        for div in soup.select(".rd-article__pic"):
            img = div.select_one("img.lazy-read") or div.select_one("img")
            if not img:
                continue
            src = (img.get("data-original") or img.get("data-src") or img.get("src") or "").strip()
            if src and src.startswith("http") and "bg_detail" not in src and "bg_loadimg" not in src:
                images.append(src)
        return images

    # ---------- 图片下载 ----------
    def download_image(self, url: str, timeout: int = 15) -> bytes | None:
        """下载图片, 设置 Referer"""
        try:
            headers = {"Referer": self.base_url + "/"}
            resp = self.session.get(url, timeout=(5, timeout), headers=headers)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None

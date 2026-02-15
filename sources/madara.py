"""
WordPress Madara / WP-Manga 通用适配器
适用于: mangaforfree.net, manhwaclub.net, mangaread.org
"""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import MangaSource


class MadaraSource(MangaSource):
    """WordPress Madara/WP-Manga 主题通用适配器"""

    def __init__(self, base_url: str, name: str = "", icon: str = "📖"):
        self.base_url = base_url.rstrip("/")
        self.name = name or self.base_url.split("//")[-1].split("/")[0]
        self.icon = icon
        super().__init__()

    @property
    def ajax_url(self):
        return f"{self.base_url}/wp-admin/admin-ajax.php"

    def search(self, keyword: str) -> list[dict]:
        url = f"{self.base_url}/?s={keyword}&post_type=wp-manga"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".c-tabs-item__content"):
            title_el = item.select_one(".post-title a")
            if not title_el:
                continue
            cover_el = item.select_one("img")
            genres_el = item.select(".mg_genres .summary-content a")
            results.append({
                "title": title_el.text.strip(),
                "url": title_el["href"],
                "cover": (cover_el.get("data-src") or cover_el.get("src"))
                         if cover_el else None,
                "genres": ", ".join(g.text.strip() for g in genres_el),
            })
        return results

    def _parse_listing_page(self, url: str) -> list[dict]:
        """解析 Madara 漫画列表页 (热门/最新)"""
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".page-item-detail, .manga"):
            title_el = item.select_one(".post-title a, h3 a, h5 a")
            if not title_el:
                continue
            cover_el = item.select_one("img")
            genres_el = item.select(".mg_genres a, .manga-genres a")
            cover = None
            if cover_el:
                cover = cover_el.get("data-src") or cover_el.get("src")
            results.append({
                "title": title_el.text.strip(),
                "url": title_el["href"],
                "cover": cover,
                "genres": ", ".join(g.text.strip() for g in genres_el),
            })
        return results

    def get_popular(self, page: int = 1) -> list[dict]:
        url = f"{self.base_url}/manga/?m_orderby=views" + (f"&page={page}" if page > 1 else "")
        return self._parse_listing_page(url)

    def get_latest(self, page: int = 1) -> list[dict]:
        url = f"{self.base_url}/manga/?m_orderby=latest" + (f"&page={page}" if page > 1 else "")
        return self._parse_listing_page(url)

    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one(".post-title h1")
        if title_el:
            for badge in title_el.select(".manga-title-badges"):
                badge.decompose()
        title = title_el.text.strip() if title_el else "Unknown"

        manga_id = None
        data_id_el = soup.select_one("[data-id]")
        if data_id_el:
            manga_id = data_id_el["data-id"]
        else:
            m = re.search(r'"manga_id"\s*:\s*"(\d+)"', resp.text)
            if m:
                manga_id = m.group(1)

        cover_el = soup.select_one(".summary_image img")
        cover = (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None

        desc_el = soup.select_one(".summary__content p")
        description = desc_el.text.strip() if desc_el else ""

        genres = ", ".join(a.text.strip() for a in soup.select(".genres-content a"))

        return {
            "title": title, "manga_id": manga_id, "url": manga_url,
            "cover": cover, "description": description, "genres": genres,
        }

    def get_chapters(self, manga_url: str, manga_id: str = None) -> list[dict]:
        if manga_id is None:
            info = self.get_manga_info(manga_url)
            manga_id = info.get("manga_id")

        chapters = []
        # AJAX API
        if manga_id:
            try:
                resp = self.session.post(
                    self.ajax_url,
                    data={"action": "manga_get_chapters", "manga": manga_id},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    timeout=15,
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                for li in soup.select("li.wp-manga-chapter"):
                    a = li.select_one("a")
                    date_el = li.select_one(".chapter-release-date i")
                    if a:
                        chapters.append({
                            "title": a.text.strip(),
                            "url": a["href"],
                            "date": date_el.text.strip() if date_el else "",
                        })
            except Exception:
                pass

        # 回退: 页面解析
        if not chapters:
            resp = self.session.get(manga_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for li in soup.select("li.wp-manga-chapter"):
                a = li.select_one("a")
                date_el = li.select_one(".chapter-release-date i")
                if a:
                    chapters.append({
                        "title": a.text.strip(),
                        "url": a["href"],
                        "date": date_el.text.strip() if date_el else "",
                    })

        chapters.reverse()
        return chapters

    def get_chapter_images(self, chapter_url: str) -> list[str]:
        resp = self.session.get(chapter_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        for img in soup.select("img.wp-manga-chapter-img, .page-break img, .reading-content img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and not src.endswith(".gif") and "logo" not in src:
                images.append(src if src.startswith("http") else urljoin(self.base_url, src))
        # 去重
        seen = set()
        unique = []
        for u in images:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique

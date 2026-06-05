"""
manga18.club 适配器
自定义CMS, 图片选择器: img.image-chapter
CDN: s1.manga18.club
URL: /manhwa/{slug}/chapter-{N}
"""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import MangaSource


class Manga18Source(MangaSource):
    name = "Manga18"
    base_url = "https://manga18.club"
    icon = "🔞"

    def __init__(self):
        super().__init__()
        # manga18.club 可能需要特定的 headers
        self.session.headers.update({
            "Referer": self.base_url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def search(self, keyword: str) -> list[dict]:
        url = f"{self.base_url}/search?q={keyword}"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".story_item, .list-story-item, .search-story-item, .story-item"):
            title_el = item.select_one("a[title], h3 a, a")
            if not title_el:
                continue
            cover_el = item.select_one("img")
            href = title_el.get("href", "")
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if "/manhwa/" not in full and "/manga/" not in full:
                continue
            results.append({
                "title": (title_el.get("title") or title_el.text).strip(),
                "url": full,
                "cover": (cover_el.get("data-src") or cover_el.get("src"))
                         if cover_el else None,
                "genres": "",
            })
        # Fallback
        if not results:
            for a in soup.select("a"):
                href = a.get("href", "")
                if ("/manhwa/" in href or "/manga/" in href) and "/chapter" not in href:
                    txt = (a.get("title") or a.text).strip()
                    if txt and len(txt) > 2:
                        full = href if href.startswith("http") else urljoin(self.base_url, href)
                        if not any(r["url"] == full for r in results):
                            results.append({"title": txt, "url": full, "cover": None, "genres": ""})
        return results

    def _parse_homepage(self) -> list[dict]:
        resp = self.session.get(self.base_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".story_item, .list-story-item, .search-story-item, .story-item"):
            title_el = item.select_one("a[title], h3 a, a")
            if not title_el:
                continue
            href = title_el.get("href", "")
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if ("/manhwa/" not in full and "/manga/" not in full) or "/chapter" in full:
                continue
            cover_el = item.select_one("img")
            title = (title_el.get("title") or title_el.text).strip()
            if title and len(title) > 2 and not any(r["url"] == full for r in results):
                results.append({
                    "title": title, "url": full,
                    "cover": (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None,
                    "genres": "",
                })
        return results[:24]

    def get_popular(self, page: int = 1) -> list[dict]:
        if page > 1: return []
        return self._parse_homepage()

    def get_latest(self, page: int = 1) -> list[dict]:
        if page > 1: return []
        return self._parse_homepage()

    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one("h1, h2.manga-title, .manga-info h1")
        title = title_el.text.strip() if title_el else "Unknown"

        cover_el = soup.select_one(".manga-info img, .info-image img, img.manga-thumb")
        cover = (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None

        desc_el = soup.select_one(".manga-description, .description-summary, .story-info p")
        description = desc_el.text.strip()[:300] if desc_el else ""

        return {
            "title": title, "manga_id": None, "url": manga_url,
            "cover": cover, "description": description, "genres": "",
        }

    def get_chapters(self, manga_url: str, manga_id: str = None) -> list[dict]:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        chapters = []
        seen = set()
        for a in soup.select("a"):
            href = a.get("href", "")
            if "/chapter-" in href or "/chapter/" in href:
                full = href if href.startswith("http") else urljoin(self.base_url, href)
                if full not in seen:
                    seen.add(full)
                    text = a.text.strip()
                    if text and len(text) < 60:
                        chapters.append({"title": text, "url": full, "date": ""})

        chapters.reverse()
        return chapters

    def get_chapter_images(self, chapter_url: str) -> list[str]:
        resp = self.session.get(chapter_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        # 主选择器: img.image-chapter
        for img in soup.select("img.image-chapter"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and src.startswith("http") and "logo" not in src:
                images.append(src)
        # Fallback: 所有 s1.manga18.club 图片
        if not images:
            for img in soup.select("img"):
                src = (img.get("data-src") or img.get("src") or "").strip()
                if "manga18.club" in src and "logo" not in src and src.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    images.append(src)
        seen = set()
        return [u for u in images if u not in seen and not seen.add(u)]

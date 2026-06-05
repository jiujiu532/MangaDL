"""
mangadna.com 适配器
自定义CMS, 图片选择器: img.myx01 于 .read-content
CDN: img001.mangadna.com
搜索: /search?q=
"""
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import MangaSource


class MangaDNASource(MangaSource):
    name = "MangaDNA"
    base_url = "https://mangadna.com"
    icon = "🧬"

    def search(self, keyword: str) -> list[dict]:
        url = f"{self.base_url}/search?q={keyword}"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # 主选择器: .hthumb 包含封面链接, .htitle 包含标题
        for thumb in soup.select(".hthumb"):
            a = thumb.select_one("a[href*='/manga/']")
            if not a:
                continue
            href = a.get("href", "")
            full_url = href if href.startswith("http") else urljoin(self.base_url, href)
            if "/chapter" in full_url:
                continue
            img = a.select_one("img")
            cover = None
            if img:
                cover = img.get("data-src") or img.get("src")
            # 标题: 优先从同级 .htitle 获取
            title = ""
            parent = thumb.parent
            if parent:
                title_el = parent.select_one(".htitle a, h3 a")
                if title_el:
                    title = (title_el.get("title") or title_el.text).strip()
            if not title:
                title = (a.get("title") or a.text).strip()
            if not title or "/chapter" in full_url:
                continue
            if not any(r["url"] == full_url for r in results):
                results.append({
                    "title": title, "url": full_url,
                    "cover": cover, "genres": "",
                })

        # Fallback: 从所有 /manga/ 链接提取
        if not results:
            for a in soup.select("a[href*='/manga/']"):
                href = a.get("href", "")
                if "/chapter" in href:
                    continue
                full = href if href.startswith("http") else urljoin(self.base_url, href)
                txt = (a.get("title") or a.text).strip()
                img = a.select_one("img")
                cover = (img.get("data-src") or img.get("src")) if img else None
                if txt and len(txt) > 2 and not any(r["url"] == full for r in results):
                    results.append({"title": txt, "url": full, "cover": cover, "genres": ""})
        return results

    def _parse_homepage_section(self, section_id: str = None) -> list[dict]:
        """解析首页的漫画列表区块"""
        resp = self.session.get(self.base_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # 主选择器: .slider__thumb (当前站点结构)
        items = soup.select(".slider__thumb, .story_item, .content-homepage-item, .list-story-item, .manga-item")
        for item in items:
            title_el = item.select_one("a[title], h3 a, a")
            if not title_el:
                continue
            href = title_el.get("href", "")
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if "/manga/" not in full or "/chapter" in full:
                continue
            cover_el = item.select_one("img")
            title = (title_el.get("title") or title_el.text).strip()
            if title and len(title) > 2 and not any(r["url"] == full for r in results):
                results.append({
                    "title": title,
                    "url": full,
                    "cover": (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None,
                    "genres": "",
                })

        # Fallback: 直接找所有 /manga/ 链接
        if not results:
            for a in soup.select("a[href*='/manga/']"):
                href = a.get("href", "")
                if "/chapter" in href:
                    continue
                full = href if href.startswith("http") else urljoin(self.base_url, href)
                txt = (a.get("title") or a.text).strip()
                if txt and len(txt) > 2 and not any(r["url"] == full for r in results):
                    img = a.select_one("img")
                    results.append({
                        "title": txt, "url": full,
                        "cover": (img.get("data-src") or img.get("src")) if img else None,
                        "genres": "",
                    })
        return results[:24]

    def get_popular(self, page: int = 1) -> list[dict]:
        if page > 1: return []
        return self._parse_homepage_section("popular")

    def get_latest(self, page: int = 1) -> list[dict]:
        if page > 1: return []
        return self._parse_homepage_section("latest")

    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one("h1, .manga-title, .story-info-right h1")
        title = title_el.text.strip() if title_el else "Unknown"

        cover_el = soup.select_one(".manga-info img, .info-image img, img.manga-thumb, .story-info-left img")
        cover = (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None

        desc_el = soup.select_one(".manga-description, .description-summary, #panel-story-info-description")
        description = desc_el.text.strip()[:300] if desc_el else ""

        return {
            "title": title, "manga_id": None, "url": manga_url,
            "cover": cover, "description": description, "genres": "",
        }

    def get_chapters(self, manga_url: str, manga_id: str = None) -> list[dict]:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 提取当前漫画的 slug, 用于过滤其他漫画的章节链接
        manga_slug = manga_url.rstrip("/").split("/manga/")[-1].split("/")[0]

        chapters = []
        seen = set()
        # 精确选择器: li.a-h 内的链接才是本漫画的章节列表
        for li in soup.select("li.a-h"):
            a = li.select_one("a")
            if not a:
                continue
            href = a.get("href", "")
            if not href:
                continue
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            # 只保留属于当前漫画的章节
            if manga_slug and manga_slug not in full:
                continue
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
        # 主选择器: .read-content img.myx01
        for img in soup.select(".read-content img, img.myx01"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and src.startswith("http") and "logo" not in src and "mangadna.png" not in src:
                images.append(src)
        # Fallback: 所有带 mangadna CDN 的图片
        if not images:
            for img in soup.select("img"):
                src = (img.get("data-src") or img.get("src") or "").strip()
                if "img001.mangadna.com" in src:
                    images.append(src)
        seen = set()
        return [u for u in images if u not in seen and not seen.add(u)]

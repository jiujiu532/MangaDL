"""
manhwahub.net 适配器
WordPress Madara变体，使用 .page-break img 选择器
CDN: cdn.manhwahub.net
"""
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import MangaSource


class ManhwaHubSource(MangaSource):
    name = "ManhwaHub"
    base_url = "https://manhwahub.net"
    icon = "🌐"

    def search(self, keyword: str) -> list[dict]:
        results = []

        # 方法1: 直接猜测 slug URL (最快)
        slug = re.sub(r'[^a-z0-9]+', '-', keyword.lower()).strip('-')
        slug_variants = [slug]
        # 添加常见变体: 去掉尾部数字、去掉连字符等
        if '-' in slug:
            slug_variants.append(slug.replace('-', '-'))
        try:
            for sv in slug_variants:
                url = f"{self.base_url}/webtoon/{sv}"
                resp = self.session.get(url, timeout=8, allow_redirects=True)
                if resp.status_code == 200 and '/webtoon/' in resp.url:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    h1 = soup.select_one("h1")
                    if h1:
                        title = h1.text.strip()
                        cover_el = soup.select_one(".summary_image img, .info-image img, img.manga-thumb")
                        cover = (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None
                        results.append({
                            "title": title, "url": resp.url, "cover": cover, "genres": "",
                        })
                        break
        except Exception:
            pass

        # 方法2: 抓取首页，过滤匹配关键词的漫画
        if not results:
            try:
                resp = self.session.get(self.base_url, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                kw_lower = keyword.lower()
                for item in soup.select(".manga_list-sbs .manga-poster, .page-item-detail, .story_item, .list-story-item"):
                    title_el = item.select_one("a[title], h3 a, .item-title a")
                    if not title_el:
                        a_el = item.select_one("a")
                        if a_el and a_el.get("href") and "/webtoon/" in a_el.get("href", ""):
                            title_el = a_el
                    if not title_el:
                        continue
                    title = (title_el.get("title") or title_el.text).strip()
                    if kw_lower in title.lower() or title.lower() in kw_lower:
                        cover_el = item.select_one("img")
                        href = title_el["href"]
                        full = href if href.startswith("http") else urljoin(self.base_url, href)
                        if not any(r["url"] == full for r in results):
                            results.append({
                                "title": title, "url": full,
                                "cover": (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None,
                                "genres": "",
                            })
            except Exception:
                pass

        # 方法3: 尝试原始搜索端点 (可能恢复)
        if not results:
            try:
                resp = self.session.get(f"{self.base_url}/search?s={keyword}", timeout=8)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for item in soup.select(".manga_list-sbs .manga-poster, .page-item-detail"):
                        title_el = item.select_one("a[title], h3 a")
                        if not title_el:
                            continue
                        cover_el = item.select_one("img")
                        href = title_el["href"]
                        full = href if href.startswith("http") else urljoin(self.base_url, href)
                        if not any(r["url"] == full for r in results):
                            results.append({
                                "title": (title_el.get("title") or title_el.text).strip(),
                                "url": full,
                                "cover": (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None,
                                "genres": "",
                            })
            except Exception:
                pass

        return results

    def _parse_homepage(self) -> list[dict]:
        resp = self.session.get(self.base_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".manga_list-sbs .manga-poster, .page-item-detail, .story_item, .list-story-item"):
            title_el = item.select_one("a[title], h3 a, a")
            if not title_el:
                continue
            href = title_el.get("href", "")
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if "/webtoon/" not in full or "/chapter" in full:
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
        if page > 1:
            return []
        return self._parse_homepage()

    def get_latest(self, page: int = 1) -> list[dict]:
        if page > 1:
            return []
        return self._parse_homepage()

    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.session.get(manga_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = (soup.select_one("h1") or soup.select_one(".post-title")).text.strip()
        cover_el = soup.select_one(".summary_image img, .info-image img, img.manga-thumb")
        cover = (cover_el.get("data-src") or cover_el.get("src")) if cover_el else None
        desc_el = soup.select_one(".summary__content p, .manga-description, .description-summary")
        description = desc_el.text.strip() if desc_el else ""

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
        # 使用精确选择器: li.wp-manga-chapter 内的链接才是真正的章节
        for li in soup.select("li.wp-manga-chapter"):
            a = li.select_one("a")
            if not a:
                continue
            href = a.get("href", "")
            if not href:
                continue
            full = href if href.startswith("http") else urljoin(self.base_url, href)
            if full not in seen:
                seen.add(full)
                title = a.text.strip()
                if title and title not in ("Read First", "Read Last"):
                    chapters.append({
                        "title": title,
                        "url": full,
                        "date": "",
                    })
        chapters.reverse()
        return chapters

    def get_chapter_images(self, chapter_url: str) -> list[str]:
        resp = self.session.get(chapter_url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        for img in soup.select(".reading-content img, .page-break img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and not src.endswith(".gif") and "logo" not in src:
                images.append(src if src.startswith("http") else urljoin(self.base_url, src))
        seen = set()
        return [u for u in images if u not in seen and not seen.add(u)]

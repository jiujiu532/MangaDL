"""
收藏夹管理模块
本地 JSON 存储，支持分组/标签 + 下载历史追踪
"""
import os
import json
import re
import time

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".manga_downloader")
FAVORITES_FILE = os.path.join(CONFIG_DIR, "favorites.json")

DEFAULT_GROUPS = ["追更中", "待看", "已看完"]


class FavoritesManager:
    def __init__(self):
        self._data = {"groups": list(DEFAULT_GROUPS), "items": [], "update_log": [], "download_log": []}
        self.load()

    def load(self):
        if os.path.exists(FAVORITES_FILE):
            try:
                with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if "groups" not in saved:
                    saved["groups"] = list(DEFAULT_GROUPS)
                if "items" not in saved:
                    saved["items"] = []
                if "update_log" not in saved:
                    saved["update_log"] = []
                if "download_log" not in saved:
                    saved["download_log"] = []
                self._data = saved
            except Exception:
                pass

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --- 分组 ---
    def get_groups(self) -> list[str]:
        return self._data["groups"]

    def add_group(self, name: str):
        if name not in self._data["groups"]:
            self._data["groups"].append(name)
            self.save()

    def remove_group(self, name: str):
        if name in self._data["groups"] and name not in DEFAULT_GROUPS:
            self._data["groups"].remove(name)
            for item in self._data["items"]:
                if item.get("group") == name:
                    item["group"] = DEFAULT_GROUPS[0]
            self.save()

    # --- 收藏 ---
    def get_all(self) -> list[dict]:
        return self._data["items"]

    def get_by_group(self, group: str) -> list[dict]:
        return [i for i in self._data["items"] if i.get("group") == group]

    def is_favorited(self, url: str) -> bool:
        return any(i["url"] == url for i in self._data["items"])

    def add(self, title: str, url: str, cover: str, source_name: str,
            group: str = None):
        if self.is_favorited(url):
            return
        self._data["items"].append({
            "title": title,
            "url": url,
            "cover": cover or "",
            "source": source_name,
            "group": group or DEFAULT_GROUPS[0],
            "added_at": time.strftime("%Y-%m-%d %H:%M"),
        })
        self.save()

    def remove(self, url: str):
        self._data["items"] = [i for i in self._data["items"] if i["url"] != url]
        self.save()

    def update_group(self, url: str, new_group: str):
        for item in self._data["items"]:
            if item["url"] == url:
                item["group"] = new_group
                break
        self.save()

    # --- 下载历史 ---
    def update_download_history(self, url: str, chapter_num: str, is_raw: bool = None):
        """下载完成时记录章节号及版本(raw/translated)"""
        for item in self._data["items"]:
            if item["url"] == url:
                hist = item.setdefault("download_history", {
                    "last_chapter": "", "chapters": [],
                    "last_updated": "", "last_version": "raw",
                })
                if chapter_num not in hist["chapters"]:
                    hist["chapters"].append(chapter_num)
                # 更新 last_chapter 为数值最大的
                try:
                    nums = [(float(c), c) for c in hist["chapters"]
                            if re.match(r'^[\d.]+$', c)]
                    if nums:
                        hist["last_chapter"] = max(nums, key=lambda x: x[0])[1]
                except Exception:
                    hist["last_chapter"] = chapter_num
                # 记录最后下载的版本
                if is_raw is not None:
                    hist["last_version"] = "raw" if is_raw else "translated"
                elif "last_version" not in hist:
                    hist["last_version"] = "raw"
                hist["last_updated"] = time.strftime("%Y-%m-%d %H:%M")
                self.save()
                return
        # 漫画未收藏则不记录

    def get_updatable(self) -> list[dict]:
        """获取所有收藏 (可追更)"""
        return list(self._data["items"])

    def scan_download_dir(self, download_dir: str) -> int:
        """扫描下载目录, 回填收藏夹中已下载但无记录的漫画。返回回填数量。"""
        if not os.path.isdir(download_dir):
            return 0

        # 收集所有收藏标题 → item 映射 (归一化)
        fav_map = {}
        for item in self._data["items"]:
            norm = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', item["title"].lower())
            fav_map[norm] = item

        count = 0
        for manga_dir in os.listdir(download_dir):
            manga_path = os.path.join(download_dir, manga_dir)
            if not os.path.isdir(manga_path):
                continue

            # 匹配收藏
            norm_dir = re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', manga_dir.lower())
            item = fav_map.get(norm_dir)
            if not item:
                # 尝试模糊匹配
                for norm_title, fav_item in fav_map.items():
                    if norm_dir in norm_title or norm_title in norm_dir:
                        item = fav_item
                        break

            if not item:
                continue
            if item.get("download_history") and item["download_history"].get("chapters"):
                continue  # 已有记录, 跳过

            # 扫描章节文件夹
            chapters = []
            for ch_folder in os.listdir(manga_path):
                ch_path = os.path.join(manga_path, ch_folder)
                if not os.path.isdir(ch_path):
                    continue
                # 从 "第XX话" 或 "第XX话_raw" 提取章节号
                m = re.search(r'第(\d+(?:\.\d+)?)话', ch_folder)
                if m:
                    chapters.append(m.group(1))

            if chapters:
                try:
                    nums = [(float(c), c) for c in chapters]
                    last = max(nums, key=lambda x: x[0])[1]
                except Exception:
                    last = chapters[-1]
                # 检测版本: 最新章节文件夹是否含 _raw
                has_raw = any("_raw" in f.lower() for f in os.listdir(manga_path)
                             if os.path.isdir(os.path.join(manga_path, f)))
                has_trans = any("_raw" not in f.lower() and re.search(r'第[\d.]+话', f)
                               for f in os.listdir(manga_path)
                               if os.path.isdir(os.path.join(manga_path, f)))
                if has_raw and not has_trans:
                    version = "raw"
                elif has_trans and not has_raw:
                    version = "translated"
                else:
                    version = "raw"  # 混合或无法判断时默认 raw
                item["download_history"] = {
                    "last_chapter": last,
                    "chapters": chapters,
                    "last_updated": time.strftime("%Y-%m-%d %H:%M"),
                    "last_version": version,
                }
                count += 1

        if count > 0:
            self.save()
        return count

    # --- 追更日志 ---
    def add_update_log(self, entry: dict):
        """添加追更记录, 最多保留 20 条"""
        log = self._data.setdefault("update_log", [])
        entry["time"] = time.strftime("%Y-%m-%d %H:%M")
        log.insert(0, entry)
        self._data["update_log"] = log[:20]
        self.save()

    def get_update_log(self) -> list[dict]:
        return self._data.get("update_log", [])

    # --- 下载日志 (所有下载行为) ---
    def add_download_log(self, entry: dict):
        """添加下载记录, 最多保留 50 条"""
        log = self._data.setdefault("download_log", [])
        entry["time"] = time.strftime("%Y-%m-%d %H:%M")
        log.insert(0, entry)
        self._data["download_log"] = log[:50]
        self.save()

    def get_download_log(self) -> list[dict]:
        return self._data.get("download_log", [])

    def backfill_from_download_log(self):
        """从下载日志回填收藏的 download_history (修复浏览器下载未记录的情况)"""
        logs = self._data.get("download_log", [])
        if not logs:
            return 0

        changed = 0
        for item in self._data["items"]:
            if item.get("download_history") and item["download_history"].get("chapters"):
                continue  # 已有记录，跳过

            # 在下载日志中查找匹配的记录
            best_ch = None
            for log_entry in logs:
                if log_entry.get("manga_title", "") == item.get("title", ""):
                    # 使用 to_chapter 作为最新章节
                    to_ch = log_entry.get("to_chapter", "")
                    if to_ch:
                        try:
                            to_num = float(to_ch)
                            if best_ch is None or to_num > float(best_ch):
                                best_ch = to_ch
                        except (ValueError, TypeError):
                            pass

            if best_ch:
                item["download_history"] = {
                    "last_chapter": best_ch,
                    "chapters": [best_ch],
                    "last_updated": time.strftime("%Y-%m-%d %H:%M"),
                }
                changed += 1

        if changed > 0:
            self.save()
        return changed

    def clear_download_log(self):
        self._data["download_log"] = []
        self.save()

    # --- 导入导出 ---
    def export_to(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def import_from(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            imported = json.load(f)
        existing_urls = {i["url"] for i in self._data["items"]}
        for item in imported.get("items", []):
            if item["url"] not in existing_urls:
                self._data["items"].append(item)
                existing_urls.add(item["url"])
        for g in imported.get("groups", []):
            if g not in self._data["groups"]:
                self._data["groups"].append(g)
        self.save()


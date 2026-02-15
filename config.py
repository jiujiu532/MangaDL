"""
配置管理模块
持久化保存用户设置到 config.json
"""
import os
import json

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".manga_downloader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "download_dir": os.path.join(os.path.expanduser("~"), "MangaDownloads"),
    "chapter_concurrency": 50,
    "image_concurrency": 300,
    "proxy_mode": "none",        # none / http / socks5
    "proxy_host": "127.0.0.1",
    "proxy_port": 7890,
    "theme": "dark",             # dark / light
    "window_x": 100,
    "window_y": 100,
    "window_w": 1300,
    "window_h": 850,
    "search_history": [],        # 最近搜索关键词, 最多 20 条
    "app_version": "1.0.0",
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 合并: 保留新增的默认字段
                for k, v in DEFAULTS.items():
                    if k not in saved:
                        saved[k] = v
                # Auto-upgrade low concurrency from older versions
                if saved.get("chapter_concurrency", 0) < 50:
                    saved["chapter_concurrency"] = 50
                if saved.get("image_concurrency", 0) < 300:
                    saved["image_concurrency"] = 300
                self._data = saved
            except Exception:
                pass

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    # --- 搜索历史 ---
    def add_search_history(self, keyword: str):
        h = self._data.get("search_history", [])
        if keyword in h:
            h.remove(keyword)
        h.insert(0, keyword)
        self._data["search_history"] = h[:20]

    def get_search_history(self) -> list:
        return self._data.get("search_history", [])

    # --- 代理 ---
    def get_proxy_dict(self) -> dict | None:
        mode = self._data.get("proxy_mode", "none")
        if mode == "none":
            return None
        host = self._data.get("proxy_host", "127.0.0.1")
        port = self._data.get("proxy_port", 7890)
        if mode == "http":
            proxy = f"http://{host}:{port}"
        elif mode == "socks5":
            proxy = f"socks5://{host}:{port}"
        else:
            return None
        return {"http": proxy, "https": proxy}

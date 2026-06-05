import threading
import time

from config import Config
from download_manager import DownloadManager, extract_chapter_number
from favorites import FavoritesManager
from sources import get_all_sources


class WebState:
    """Web 侧共享状态与单例容器。"""

    def __init__(self):
        self.config = Config()
        self.favorites = FavoritesManager()
        self.sources = get_all_sources()
        self.dl_manager = DownloadManager(
            self.config["chapter_concurrency"],
            self.config["image_concurrency"],
        )

        self.log_buffer = []
        self.log_lock = threading.Lock()

        self.source_health = {}
        self.health_ttl = 120

        self.listing_pool = {}
        self.cache_ttl = 300
        self.page_size = 30
        self.initial_src_pages = 5
        self.expand_src_pages = 2
        self.expand_lock = threading.Lock()
        self.expanding = set()
        self.bg_loop_running = set()

        self.img_cache = {}
        self.img_cache_lock = threading.Lock()
        self.img_downloading = {}
        self.img_downloading_lock = threading.Lock()
        self.img_cache_max = 2000
        self.img_cache_ttl = 7200
        self.proxy_session = None
        self.proxy_session_lock = threading.Lock()

        self._wire_callbacks()

    def _wire_callbacks(self):
        self.dl_manager.task_log.connect(self.add_log)
        self.dl_manager.task_updated.connect(self.on_task_updated)

    def add_log(self, msg):
        with self.log_lock:
            self.log_buffer.append(msg)
            if len(self.log_buffer) > 200:
                self.log_buffer.pop(0)

    def clear_logs(self):
        with self.log_lock:
            self.log_buffer.clear()

    def on_task_updated(self, idx):
        try:
            task = self.dl_manager.tasks[idx]
            if task.status.value == "Completed":
                ch_num = extract_chapter_number(task.chapter_title)
                is_raw = "raw" in task.chapter_title.lower()
                for item in self.favorites.get_all():
                    if normalize_title(item["title"]) == normalize_title(task.manga_title):
                        self.favorites.update_download_history(item["url"], ch_num, is_raw=is_raw)
                        break
        except Exception:
            pass

    def preload_listings(self, fetch_listing):
        """后台预热热门/最新缓存。"""

        def _preload():
            time.sleep(0.5)
            try:
                fetch_listing("get_popular", "")
                fetch_listing("get_latest", "")
                print("[PRELOAD] Popular/Latest cached")
            except Exception as exc:
                print(f"[PRELOAD] Warning: {exc}")

        threading.Thread(target=_preload, daemon=True).start()


def normalize_title(title: str) -> str:
    import re

    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", title.lower())

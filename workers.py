"""Worker 线程"""
import requests
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage
from sources.base import MangaSource


class SearchWorker(QThread):
    """单源搜索"""
    finished = pyqtSignal(str, list)  # source_name, results
    error = pyqtSignal(str, str)      # source_name, error

    def __init__(self, source: MangaSource, keyword: str):
        super().__init__()
        self.source = source
        self.keyword = keyword

    def run(self):
        try:
            results = self.source.search(self.keyword)
            for r in results:
                r["_source_name"] = self.source.name
                r["_source_icon"] = self.source.icon
            self.finished.emit(self.source.name, results)
        except Exception as e:
            self.error.emit(self.source.name, str(e))


class MultiSearchWorker(QThread):
    """多源并发搜索"""
    source_done = pyqtSignal(str, list)   # source_name, results
    source_error = pyqtSignal(str, str)
    all_done = pyqtSignal()

    def __init__(self, sources: list, keyword: str):
        super().__init__()
        self.sources = sources
        self.keyword = keyword

    def run(self):
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futs = {}
            for src in self.sources:
                futs[pool.submit(self._search_one, src)] = src

            for fut in concurrent.futures.as_completed(futs):
                src = futs[fut]
                try:
                    results = fut.result()
                    self.source_done.emit(src.name, results)
                except Exception as e:
                    self.source_error.emit(src.name, str(e))

        self.all_done.emit()

    def _search_one(self, source):
        results = source.search(self.keyword)
        for r in results:
            r["_source_name"] = source.name
            r["_source_icon"] = source.icon
            r["_source_obj"] = source
        return results


class InfoWorker(QThread):
    finished = pyqtSignal(dict, list)  # info, chapters
    error = pyqtSignal(str)

    def __init__(self, source: MangaSource, url: str):
        super().__init__()
        self.source = source
        self.url = url

    def run(self):
        try:
            info = self.source.get_manga_info(self.url)
            chapters = self.source.get_chapters(self.url, info.get("manga_id"))
            self.finished.emit(info, chapters)
        except Exception as e:
            self.error.emit(str(e))


class CoverWorker(QThread):
    finished = pyqtSignal(QPixmap)

    def __init__(self, source: MangaSource, url: str):
        super().__init__()
        self.source = source
        self.url = url

    def run(self):
        try:
            data = self.source.download_image(self.url)
            if data:
                img = QImage()
                img.loadFromData(data)
                self.finished.emit(QPixmap.fromImage(img))
            else:
                self.finished.emit(QPixmap())
        except Exception:
            self.finished.emit(QPixmap())


class HealthCheckWorker(QThread):
    """源健康检测"""
    result = pyqtSignal(str, bool, int)  # name, ok, ms

    def __init__(self, sources: list):
        super().__init__()
        self.sources = sources

    def run(self):
        for src in self.sources:
            try:
                import time
                t0 = time.time()
                resp = requests.get(src.base_url, timeout=10,
                                    headers={"User-Agent": "Mozilla/5.0"})
                ms = int((time.time() - t0) * 1000)
                self.result.emit(src.name, resp.status_code < 400, ms)
            except Exception:
                self.result.emit(src.name, False, -1)

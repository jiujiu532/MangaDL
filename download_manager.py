"""
下载任务管理器 (Flask 版, 不依赖 PyQt5)
逐章任务队列，支持暂停/恢复/取消，速度统计，失败重试

创新架构:
  1. 流水线预取 (Pipeline Pre-fetch): 下载开始前，异步预取所有章节图片URL
  2. 全局图片池 (Global Image Pool): 所有章节的图片统一放进一个大线程池下载
  3. 自适应并发 (Adaptive Concurrency): 根据实时吞吐量动态调整并发数
"""
import os
import re
import time
import threading
import difflib
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque


class TaskStatus(Enum):
    WAITING = "Waiting"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class SimpleSignal:
    """简易信号/回调系统"""
    def __init__(self):
        self._callbacks = []

    def connect(self, fn):
        self._callbacks.append(fn)

    def emit(self, *args):
        for fn in self._callbacks:
            try:
                fn(*args)
            except Exception:
                pass


class ChapterTask:
    """单章节下载任务"""
    __slots__ = (
        "chapter_title", "chapter_url", "manga_title", "source",
        "save_dir", "status", "progress", "total", "speed",
        "error", "is_raw", "chapter_num",
    )

    def __init__(self, chapter_title, chapter_url, manga_title, source,
                 save_dir, is_raw=False, chapter_num=""):
        self.chapter_title = chapter_title
        self.chapter_url = chapter_url
        self.manga_title = manga_title
        self.source = source
        self.save_dir = save_dir
        self.status = TaskStatus.WAITING
        self.progress = 0
        self.total = 0
        self.speed = 0.0
        self.error = ""
        self.is_raw = is_raw
        self.chapter_num = chapter_num


def extract_chapter_number(title: str) -> str:
    m = re.search(r'(\d+(?:\.\d+)?)', title)
    return m.group(1) if m else title


def format_chapter_dir(chapter_num: str, is_raw: bool) -> str:
    try:
        num = float(chapter_num)
        if num == int(num):
            formatted = f"{int(num):02d}"
        else:
            formatted = chapter_num
    except (ValueError, TypeError):
        formatted = re.sub(r'[<>:"/\\|?*]', '_', str(chapter_num))
    name = f"第{formatted}话"
    if is_raw:
        name += "_raw"
    return name


class DownloadManager:
    """
    下载管理器 — 创新流水线架构

    流程:
      阶段0: add_tasks()                     → 注册章节列表
      阶段1: _prefetch_pipeline()            → 并行预取所有章节图片URL
      阶段2: _global_image_download()        → 全局图片池统一下载
      背景:  _adaptive_concurrency_loop()    → 每2秒自适应调节并发数
    """

    def __init__(self, chapter_concurrency=50, image_concurrency=300):
        self.tasks: list[ChapterTask] = []
        self.chapter_concurrency = chapter_concurrency
        self.image_concurrency = image_concurrency
        self._stop_event = threading.Event()
        self._pause_events: dict[int, threading.Event] = {}
        self._thread = None
        self._lock = threading.Lock()
        self._running = False

        # ── 预取缓存: idx -> [url1, url2, ...] ──
        self._prefetch_cache: dict[int, list[str]] = {}
        self._prefetch_ready: dict[int, threading.Event] = {}

        # ── 自适应并发 ──
        self._current_workers = image_concurrency
        self._speed_history: deque[float] = deque(maxlen=10)
        self._global_bytes = 0
        self._global_start = 0.0
        self._bytes_lock = threading.Lock()

        # ── 全局图片线程池 ──
        self._image_pool: ThreadPoolExecutor | None = None

        # 回调信号
        self.task_updated = SimpleSignal()
        self.task_log = SimpleSignal()
        self.all_done = SimpleSignal()
        self.speed_updated = SimpleSignal()
        self.fallback_sources = []

    def clear(self):
        with self._lock:
            self.tasks.clear()
            self._pause_events.clear()
            self._prefetch_cache.clear()
            self._prefetch_ready.clear()
            self._global_bytes = 0

    def set_fallback_sources(self, sources):
        self.fallback_sources = sources or []

    def add_tasks(self, chapters: list[dict], manga_title: str, source,
                  save_dir: str):
        with self._lock:
            for ch in chapters:
                title = ch["title"]
                is_raw = "raw" in title.lower()
                ch_num = extract_chapter_number(title)
                task = ChapterTask(
                    chapter_title=title, chapter_url=ch["url"],
                    manga_title=manga_title, source=source,
                    save_dir=save_dir, is_raw=is_raw, chapter_num=ch_num,
                )
                idx = len(self.tasks)
                self.tasks.append(task)
                self._pause_events[idx] = threading.Event()
                self._pause_events[idx].set()
                self._prefetch_ready[idx] = threading.Event()

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._global_start = time.time()
        self._global_bytes = 0
        self._current_workers = self.image_concurrency
        # 创建全局图片线程池
        self._image_pool = ThreadPoolExecutor(max_workers=self._current_workers)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop_all(self):
        self._stop_event.set()
        for ev in self._pause_events.values():
            ev.set()
        for ev in self._prefetch_ready.values():
            ev.set()
        self._running = False

    def pause_task(self, idx: int):
        if 0 <= idx < len(self.tasks):
            self._pause_events[idx].clear()
            self.tasks[idx].status = TaskStatus.PAUSED
            self.task_updated.emit(idx)

    def resume_task(self, idx: int):
        if 0 <= idx < len(self.tasks):
            self._pause_events[idx].set()
            if self.tasks[idx].status == TaskStatus.PAUSED:
                self.tasks[idx].status = TaskStatus.WAITING
                self.task_updated.emit(idx)

    def cancel_task(self, idx: int):
        if 0 <= idx < len(self.tasks):
            self.tasks[idx].status = TaskStatus.CANCELLED
            self._pause_events[idx].set()
            self._prefetch_ready[idx].set()
            self.task_updated.emit(idx)

    # ================================================================
    #  阶段 0: 主入口 — 启动预取 + 下载 + 自适应三线程
    # ================================================================
    def _run(self):
        # 启动自适应并发调节器
        adaptive_thread = threading.Thread(target=self._adaptive_loop, daemon=True)
        adaptive_thread.start()

        # 启动预取流水线 (后台线程)
        prefetch_thread = threading.Thread(target=self._prefetch_pipeline, daemon=True)
        prefetch_thread.start()

        # 主下载循环
        sem = threading.Semaphore(self.chapter_concurrency)
        threads = []

        for idx, task in enumerate(self.tasks):
            if self._stop_event.is_set():
                break
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                continue

            sem.acquire()
            if self._stop_event.is_set():
                sem.release()
                break

            t = threading.Thread(target=self._download_chapter,
                                 args=(idx, sem), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        # 关闭全局图片池
        if self._image_pool:
            self._image_pool.shutdown(wait=False)
            self._image_pool = None

        self._running = False
        self._stop_event.set()  # 通知自适应和预取线程退出
        self.all_done.emit()

    # ================================================================
    #  阶段 1: 流水线预取 — 并行获取所有章节的图片URL列表
    # ================================================================
    def _prefetch_pipeline(self):
        """在下载开始前/同时，并行预取所有章节的图片URL"""
        self.task_log.emit("[PREFETCH] 开始预取图片URL...")

        def _fetch_one(idx: int):
            task = self.tasks[idx]
            if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                self._prefetch_ready[idx].set()
                return
            try:
                images = task.source.get_chapter_images(task.chapter_url)
                self._prefetch_cache[idx] = images or []
            except Exception as e:
                self._prefetch_cache[idx] = []
                self.task_log.emit(f"[PREFETCH] {task.chapter_title} 预取失败: {e}")
            finally:
                self._prefetch_ready[idx].set()

        # 用较高并发预取 (HTML解析很轻量，主要是网络IO)
        prefetch_workers = min(len(self.tasks), 60)
        with ThreadPoolExecutor(max_workers=prefetch_workers) as pool:
            futs = []
            for idx in range(len(self.tasks)):
                if self._stop_event.is_set():
                    break
                task = self.tasks[idx]
                if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                    self._prefetch_ready[idx].set()
                    continue
                futs.append(pool.submit(_fetch_one, idx))
            for f in as_completed(futs):
                pass  # 等待全部完成

        done_count = sum(1 for v in self._prefetch_cache.values() if v)
        self.task_log.emit(f"[PREFETCH] 预取完成: {done_count}/{len(self.tasks)} 章节")

    # ================================================================
    #  阶段 2: 章节下载 — 从预取缓存读取URL，跳过HTML解析
    # ================================================================
    def _download_chapter(self, idx: int, sem: threading.Semaphore):
        task = self.tasks[idx]
        max_retries = 3

        try:
            self._pause_events[idx].wait()
            if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                return

            task.status = TaskStatus.DOWNLOADING
            self.task_updated.emit(idx)
            self.task_log.emit(f"[START] {task.chapter_title}")

            # ── 从预取缓存获取图片URL (等预取完成) ──
            self._prefetch_ready[idx].wait(timeout=60)
            images = self._prefetch_cache.get(idx)

            # 预取失败时同步获取 (降级)
            if not images:
                self.task_log.emit(f"[FALLBACK] {task.chapter_title} 预取缓存为空, 同步获取...")
                images = task.source.get_chapter_images(task.chapter_url)

            if not images:
                task.status = TaskStatus.FAILED
                task.error = "No images found"
                self.task_updated.emit(idx)
                self.task_log.emit(f"[FAIL] {task.chapter_title}: no images")
                return

            task.total = len(images)

            safe_manga = re.sub(r'[<>:"/\\|?*]', '_', task.manga_title)
            ch_dir_name = format_chapter_dir(task.chapter_num, task.is_raw)
            ch_dir = os.path.join(task.save_dir, safe_manga, ch_dir_name)
            os.makedirs(ch_dir, exist_ok=True)

            success = 0
            start_time = time.time()
            ch_bytes = 0

            def _dl_image(args):
                nonlocal ch_bytes
                img_idx, url = args
                ext = os.path.splitext(url.split("?")[0])[-1] or ".jpg"
                path = os.path.join(ch_dir, f"{img_idx + 1:04d}{ext}")

                if os.path.exists(path) and os.path.getsize(path) > 0:
                    return True

                for attempt in range(max_retries):
                    if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                        return False
                    self._pause_events[idx].wait()

                    try:
                        nbytes = task.source.download_image_to_file(url, path)
                        with self._bytes_lock:
                            ch_bytes += nbytes
                            self._global_bytes += nbytes
                        return True
                    except Exception:
                        if attempt < max_retries - 1:
                            time.sleep(0.02 * (attempt + 1))  # 20ms, 40ms
                return False

            # 使用全局图片线程池
            pool = self._image_pool
            if not pool:
                return
            futs = {pool.submit(_dl_image, (j, u)): j
                    for j, u in enumerate(images)}
            for fut in as_completed(futs):
                if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                    break
                if fut.result():
                    success += 1
                task.progress = success
                elapsed = time.time() - start_time
                if elapsed > 0.3:
                    task.speed = (ch_bytes / 1024) / elapsed
                self.task_updated.emit(idx)

            if task.status == TaskStatus.CANCELLED:
                return

            if success == len(images):
                task.status = TaskStatus.COMPLETED
                self.task_log.emit(f"[OK] {task.chapter_title}: {success}/{len(images)}")
            elif success > 0:
                task.status = TaskStatus.COMPLETED
                self.task_log.emit(f"[PARTIAL] {task.chapter_title}: {success}/{len(images)}")
            else:
                fallback_ok = False
                if self.fallback_sources:
                    self.task_log.emit(f"[FAILOVER] {task.chapter_title}: 主源全部失败, 尝试备用源...")
                    fallback_ok = self._try_fallback(idx, task, ch_dir, images)
                if not fallback_ok:
                    task.status = TaskStatus.FAILED
                    task.error = "All images failed"
                    self.task_log.emit(f"[FAIL] {task.chapter_title}: all failed")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self.task_log.emit(f"[ERROR] {task.chapter_title}: {e}")
        finally:
            task.speed = 0
            self.task_updated.emit(idx)
            sem.release()

    # ================================================================
    #  背景: 自适应并发调节器
    # ================================================================
    def _adaptive_loop(self):
        """每1.5秒采样吞吐量，动态调整并发数"""
        MIN_WORKERS = 100
        MAX_WORKERS = 500
        prev_bytes = 0

        while not self._stop_event.is_set():
            time.sleep(1.5)
            if self._stop_event.is_set():
                break

            with self._bytes_lock:
                current_bytes = self._global_bytes

            delta = current_bytes - prev_bytes
            prev_bytes = current_bytes
            speed_kbps = delta / 1024 / 1.5  # KB/s over 1.5 seconds

            self._speed_history.append(speed_kbps)

            if len(self._speed_history) < 3:
                continue

            recent = list(self._speed_history)[-3:]
            avg = sum(recent) / len(recent)
            trend = recent[-1] - recent[0]

            old = self._current_workers
            if trend > 20 and avg > 50:
                # 速度在上升且较快 → 加并发 (aggressive +40)
                self._current_workers = min(MAX_WORKERS, old + 80)
            elif trend < -100 or avg < 10:
                # 速度大幅下降或很慢 → 减并发
                self._current_workers = max(MIN_WORKERS, old - 20)

            if self._current_workers != old:
                self.task_log.emit(
                    f"[ADAPTIVE] 并发 {old} → {self._current_workers} "
                    f"(速度 {avg:.0f} KB/s, 趋势 {trend:+.0f})"
                )

    # ================================================================
    #  故障转移 (并行下载)
    # ================================================================
    @staticmethod
    def _normalize_title(t: str) -> str:
        return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', t.lower())

    def _try_fallback(self, idx: int, task: ChapterTask, ch_dir: str,
                      original_images: list) -> bool:
        for alt in self.fallback_sources:
            if alt.name == task.source.name:
                continue
            if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                return False
            try:
                hits = alt.search(task.manga_title)
                best, best_score = None, 0
                nq = self._normalize_title(task.manga_title)
                for h in hits:
                    nc = self._normalize_title(h.get("title", ""))
                    if nq == nc:
                        score = 1.0
                    elif nq in nc or nc in nq:
                        score = 0.9
                    else:
                        score = difflib.SequenceMatcher(None, nq, nc).ratio()
                    if score > best_score:
                        best_score, best = score, h
                if not best or best_score < 0.75:
                    continue

                info = alt.get_manga_info(best["url"])
                chs = alt.get_chapters(best["url"], info.get("manga_id"))
                target_num = extract_chapter_number(task.chapter_title)
                match_ch = None
                for c in chs:
                    if extract_chapter_number(c["title"]) == target_num:
                        match_ch = c
                        break
                if not match_ch:
                    continue

                alt_images = alt.get_chapter_images(match_ch["url"])
                if not alt_images:
                    continue

                self.task_log.emit(f"[FAILOVER] → 切换到 {alt.name} 下载 {task.chapter_title}")
                task.total = len(alt_images)
                fb_success = 0
                fb_lock = threading.Lock()

                def _dl_fb(args):
                    nonlocal fb_success
                    j, url = args
                    if self._stop_event.is_set() or task.status == TaskStatus.CANCELLED:
                        return False
                    ext = os.path.splitext(url.split("?")[0])[-1] or ".jpg"
                    path = os.path.join(ch_dir, f"{j + 1:04d}{ext}")
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        with fb_lock:
                            fb_success += 1
                        return True
                    try:
                        data = alt.download_image(url)
                        if data and len(data) > 50:
                            tmp = path + ".tmp"
                            with open(tmp, "wb") as f:
                                f.write(data)
                            os.replace(tmp, path)
                            with fb_lock:
                                fb_success += 1
                                self._global_bytes += len(data)
                            return True
                    except:
                        pass
                    return False

                workers = min(self._current_workers, len(alt_images))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [pool.submit(_dl_fb, (j, u)) for j, u in enumerate(alt_images)]
                    for fut in as_completed(futs):
                        task.progress = fb_success
                        self.task_updated.emit(idx)

                if fb_success > 0:
                    task.status = TaskStatus.COMPLETED
                    self.task_log.emit(
                        f"[FAILOVER OK] {task.chapter_title}: {fb_success}/{len(alt_images)} via {alt.name}")
                    return True
            except:
                continue
        return False

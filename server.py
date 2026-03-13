"""
漫画下载器 Web Server — Flask 后端
复用现有 sources/config/favorites/download_manager 模块
"""
import os, sys, re, json, time, threading, difflib, hashlib, zipfile, struct
from functools import lru_cache
from flask import Flask, render_template, jsonify, request, Response, send_file, stream_with_context
from io import BytesIO
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import get_all_sources
from config import Config
from favorites import FavoritesManager
from download_manager import (DownloadManager, TaskStatus,
                               extract_chapter_number, format_chapter_dir)
import concurrent.futures

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
config = Config()
favorites = FavoritesManager()
sources = get_all_sources()
dl_manager = DownloadManager(config["chapter_concurrency"], config["image_concurrency"])

# SSE log buffer
_log_buffer = []
_log_lock = threading.Lock()

# Source health cache — skip offline sources in listings
_source_health = {}   # source_name -> {"status": "online"|"offline", "ts": time}
_HEALTH_TTL = 120     # 2 min

def _add_log(msg):
    with _log_lock:
        _log_buffer.append(msg)
        if len(_log_buffer) > 200:
            _log_buffer.pop(0)

dl_manager.task_log.connect(_add_log)

# Record download history to favorites
def _on_task_updated(idx):
    try:
        task = dl_manager.tasks[idx]
        if task.status.value == "Completed":
            from download_manager import extract_chapter_number
            ch_num = extract_chapter_number(task.chapter_title)
            is_raw = "raw" in task.chapter_title.lower()
            # Find the manga URL from favorites that matches this manga title
            for item in favorites.get_all():
                # Match by title (normalized)
                if _normalize(item["title"]) == _normalize(task.manga_title):
                    favorites.update_download_history(item["url"], ch_num, is_raw=is_raw)
                    break
    except Exception:
        pass

dl_manager.task_updated.connect(_on_task_updated)

# Background preload popular/latest on startup
def _preload():
    import time
    time.sleep(0.5)  # 快速启动缓存
    try:
        from server import _fetch_listing
        _fetch_listing("get_popular", "")
        _fetch_listing("get_latest", "")
        print("[PRELOAD] Popular/Latest cached")
    except Exception as e:
        print(f"[PRELOAD] Warning: {e}")

threading.Thread(target=_preload, daemon=True).start()

# ─── Pages ───
@app.route("/")
def index():
    return render_template("index.html")

# ─── API: Sources ───
@app.route("/api/sources")
def api_sources():
    return jsonify([{"name": s.name, "icon": s.icon, "url": s.base_url}
                    for s in sources])

# ─── API: Search ───
@app.route("/api/search")
def api_search():
    kw = request.args.get("q", "").strip()
    src_name = request.args.get("source", "")
    if not kw:
        return jsonify([])

    config.add_search_history(kw)
    config.save()

    target_sources = sources
    if src_name:
        target_sources = [s for s in sources if s.name == src_name]

    all_results = []
    def _search_one(s):
        try:
            results = s.search(kw)
            for r in results:
                r["_source"] = s.name
            return results
        except:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_search_one, s): s for s in target_sources}
        for fut in concurrent.futures.as_completed(futs):
            all_results.extend(fut.result())

    # ── 搜索相关性过滤 (方案B: 动态阈值) ──
    kw_lower = kw.lower()
    kw_words = [w for w in kw_lower.split() if len(w) > 0]
    # 动态阈值: 短查询严格, 长查询宽松
    if len(kw_words) <= 3:
        min_ratio = 1.0   # 1-3词: 全部必须命中
    else:
        min_ratio = 0.6   # 4+词: 60%命中即可

    scored = []
    for r in all_results:
        t = r.get("title", "").lower()
        # 精确包含完整短语
        if kw_lower in t:
            scored.append((0, r))
            continue
        # 整词匹配: "class" 不匹配 "classroom"
        if kw_words:
            matched = 0
            for w in kw_words:
                # \b 单词边界, 确保完整单词匹配
                if re.search(r'(?:^|[\s\-_,.()\[\]])' + re.escape(w) + r'(?:$|[\s\-_,.()\[\]])', t):
                    matched += 1
            ratio = matched / len(kw_words)
            if ratio >= min_ratio:
                scored.append((1 - ratio, r))
                continue
        # 模糊匹配 (CJK 等非拉丁语系)
        sim = difflib.SequenceMatcher(None, kw_lower, t).ratio()
        if sim >= 0.65:
            scored.append((1 - sim, r))
    scored.sort(key=lambda x: x[0])
    filtered = [r for _, r in scored]

    return jsonify(filtered)

# ─── API: Popular / Latest ───
# pool_key -> {ts, items, next_src_page, exhausted, target}
_listing_pool = {}
_listing_cache = {}
_cache_ttl = 300
_PAGE_SIZE = 30
_INITIAL_SRC_PAGES = 5   # 初始抓源页数
_EXPAND_SRC_PAGES = 2    # 每次扩展2个源页 (快速完成, 频繁触发)

def _fetch_source_page(method_name, target_sources, src_page):
    """从所有源抓取第 src_page 页, 返回 (items, any_has_more)"""
    per_source = []
    any_has_more = False

    def _fetch(s):
        try:
            items = getattr(s, method_name)(src_page)
            for r in items:
                r["_source"] = s.name
            _source_health[s.name] = {"status": "online", "ts": time.time()}
            return items
        except:
            _source_health[s.name] = {"status": "offline", "ts": time.time()}
            return []

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
    futs = {pool.submit(_fetch, s): s for s in target_sources}
    try:
        for fut in concurrent.futures.as_completed(futs, timeout=10):
            try:
                result = fut.result(timeout=0.1)
                if result:
                    per_source.append(result)
                    if len(result) >= 5:
                        any_has_more = True
            except:
                pass
    except (TimeoutError, concurrent.futures.TimeoutError):
        for f, s in futs.items():
            if not f.done():
                _source_health[s.name] = {"status": "offline", "ts": time.time()}
    pool.shutdown(wait=False)

    # Interleave round-robin
    all_items = []
    if per_source:
        max_len = max(len(g) for g in per_source)
        for i in range(max_len):
            for group in per_source:
                if i < len(group):
                    all_items.append(group[i])
    return all_items, any_has_more


def _dedup(items):
    seen = set()
    unique = []
    for r in items:
        u = r.get("url", "")
        if u not in seen:
            seen.add(u)
            unique.append(r)
    return unique


def _resolve_targets(src_name):
    if src_name:
        return [s for s in sources if s.name == src_name]
    active = []
    now = time.time()
    for s in sources:
        h = _source_health.get(s.name)
        if h and h["status"] == "offline" and now - h["ts"] < _HEALTH_TTL:
            continue
        active.append(s)
    return active if active else sources


def _get_or_create_pool(method_name, src_name=""):
    """获取或首次构建结果池"""
    pool_key = f"{method_name}:{src_name}"
    now = time.time()
    if pool_key in _listing_pool:
        p = _listing_pool[pool_key]
        if now - p["ts"] < _cache_ttl:
            return p

    target = _resolve_targets(src_name)

    # 初始抓取 1-N 源页
    all_items = []
    exhausted = False
    next_src = 1
    for src_page in range(1, _INITIAL_SRC_PAGES + 1):
        items, has_more = _fetch_source_page(method_name, target, src_page)
        all_items.extend(items)
        next_src = src_page + 1
        if not has_more:
            exhausted = True
            break

    unique = _dedup(all_items)
    pool_data = {
        "ts": now,
        "items": unique,
        "next_src_page": next_src,
        "exhausted": exhausted,
        "target": target,
        "method": method_name,
    }
    _listing_pool[pool_key] = pool_data
    _prefetch_covers(unique)
    return pool_data

_expand_lock = threading.Lock()
_expanding = set()  # pool_keys currently being expanded

def _expand_pool(pool_key, pool_data, count=None):
    """扩展池：继续抓取更多源页 (线程安全)"""
    if pool_data["exhausted"]:
        return
    with _expand_lock:
        if pool_key in _expanding:
            return  # 已有线程在扩展
        _expanding.add(pool_key)
    try:
        target = pool_data["target"]
        method = pool_data["method"]
        rounds = count or _EXPAND_SRC_PAGES

        start = pool_data["next_src_page"]
        end = start + rounds

        new_items = []
        exhausted = False
        next_src = start
        for src_page in range(start, end):
            items, has_more = _fetch_source_page(method, target, src_page)
            new_items.extend(items)
            next_src = src_page + 1
            if not has_more:
                exhausted = True
                break

        if new_items:
            existing_urls = {r.get("url", "") for r in pool_data["items"]}
            for r in new_items:
                u = r.get("url", "")
                if u and u not in existing_urls:
                    existing_urls.add(u)
                    pool_data["items"].append(r)
            _prefetch_covers(new_items)

        pool_data["next_src_page"] = next_src
        pool_data["exhausted"] = exhausted
    finally:
        with _expand_lock:
            _expanding.discard(pool_key)


_bg_loop_running = set()  # pool_keys with active background loop

def _ensure_bg_expand(pool_key, pool_data):
    """触发后台连续扩展 — 一批完自动开下一批, 直到穷尽"""
    if pool_data["exhausted"] or pool_key in _bg_loop_running:
        return
    _bg_loop_running.add(pool_key)
    def _bg_loop():
        try:
            while not pool_data["exhausted"]:
                _expand_pool(pool_key, pool_data)
                time.sleep(0.5)
        finally:
            _bg_loop_running.discard(pool_key)
    threading.Thread(target=_bg_loop, daemon=True).start()


def _fetch_listing(method_name: str, src_name: str = "", page: int = 1):
    pool_data = _get_or_create_pool(method_name, src_name)
    pool_key = f"{method_name}:{src_name}"

    total = len(pool_data["items"])
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    # 超出池子: 等后台完成 + 同步兜底
    if page > total_pages and not pool_data["exhausted"]:
        # 等后台(最多5秒)
        for _ in range(25):
            if pool_key not in _expanding:
                break
            time.sleep(0.2)
        # 后台可能已添加新数据, 重新计算
        total = len(pool_data["items"])
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        # 还不够则同步扩展
        if page > total_pages:
            items_before = len(pool_data["items"])
            needed = page * _PAGE_SIZE
            extra = min(max(2, (needed - items_before) // 20 + 1), 10)
            _expand_pool(pool_key, pool_data, extra)
            items_after = len(pool_data["items"])
            total = items_after
            total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
            # 如果扩展后完全没增长 → 源站没更多了
            if items_after == items_before:
                pool_data["exhausted"] = True

    # 从第1页开始就持续后台扩展
    if page >= 1 and not pool_data["exhausted"]:
        _ensure_bg_expand(pool_key, pool_data)

    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    items = pool_data["items"][start:end]

    # has_next: 有更多数据 或 还有后续页
    exhausted = pool_data["exhausted"]
    has_next = (not exhausted and page <= total_pages) or page < total_pages

    return {
        "items": items,
        "page": page,
        "total_pages": total_pages,
        "has_next": has_next,
    }

@app.route("/api/popular")
def api_popular():
    src = request.args.get("source", "")
    page = int(request.args.get("page", 1))
    return jsonify(_fetch_listing("get_popular", src, page))

@app.route("/api/latest")
def api_latest():
    src = request.args.get("source", "")
    page = int(request.args.get("page", 1))
    return jsonify(_fetch_listing("get_latest", src, page))

# ─── Helper: title normalization for fuzzy match ───
def _normalize(title: str) -> str:
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', title.lower())

def _fuzzy_match(query: str, candidate: str) -> float:
    nq, nc = _normalize(query), _normalize(candidate)
    if nq == nc:
        return 1.0
    if nq in nc or nc in nq:
        return 0.9
    # 字符级相似度
    char_ratio = difflib.SequenceMatcher(None, nq, nc).ratio()
    # 单词级检查: 查询的每个单词是否出现在候选中
    q_words = set(re.findall(r'[a-z0-9\u4e00-\u9fff]+', query.lower()))
    c_words = set(re.findall(r'[a-z0-9\u4e00-\u9fff]+', candidate.lower()))
    if q_words:
        word_overlap = len(q_words & c_words) / len(q_words)
    else:
        word_overlap = 0
    # 两个条件都要满足: 字符相似 + 单词重合
    if word_overlap < 0.5:
        return min(char_ratio, 0.5)  # 关键词不匹配时封顶0.5
    return char_ratio

# ─── API: Cross-Source Discovery ───
@app.route("/api/cross-source")
def api_cross_source():
    title = request.args.get("title", "").strip()
    current = request.args.get("current_source", "")
    if not title:
        return jsonify([])

    results = []
    def _probe(s):
        t0 = time.time()
        try:
            # 快速连通性检查 (3s)
            try:
                s.session.head(s.base_url, timeout=3)
            except:
                latency = int((time.time() - t0) * 1000)
                return {"source": s.name, "icon": s.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "offline"}

            hits = s.search(title)
            latency = int((time.time() - t0) * 1000)
            best, best_score = None, 0
            for h in hits:
                score = _fuzzy_match(title, h.get("title", ""))
                if score > best_score:
                    best_score, best = score, h
            if best and best_score >= 0.75:
                ch_count = 0
                try:
                    info = s.get_manga_info(best["url"])
                    chs = s.get_chapters(best["url"], info.get("manga_id"))
                    # 去重: 同一章号的RAW和翻译版只算一次
                    seen_nums = set()
                    for ch in chs:
                        num = re.search(r'#?([\d]+(?:\.[\d]+)?)', ch.get("title", ""))
                        seen_nums.add(num.group(1) if num else ch.get("title", ""))
                    ch_count = len(seen_nums)
                except:
                    pass
                total_ms = int((time.time() - t0) * 1000)
                return {
                    "source": s.name, "icon": s.icon, "latency_ms": total_ms,
                    "match": {"title": best.get("title",""), "url": best.get("url",""), "cover": best.get("cover","")},
                    "chapter_count": ch_count, "status": "found"
                }
            else:
                return {"source": s.name, "icon": s.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "not_found"}
        except:
            latency = int((time.time() - t0) * 1000)
            return {"source": s.name, "icon": s.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "error"}

    other_sources = [s for s in sources if s.name != current]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_probe, s): s for s in other_sources}
        for fut in concurrent.futures.as_completed(futs, timeout=20):
            try:
                results.append(fut.result())
            except:
                pass

    results.sort(key=lambda r: (0 if r.get("match") else 1, r["latency_ms"]))
    return jsonify({"current_source": current, "results": results})

# ─── API: Source Health ───
@app.route("/api/source-health")
def api_source_health():
    results = []
    def _ping(s):
        t0 = time.time()
        try:
            resp = s.session.get(s.base_url, timeout=8)
            latency = int((time.time() - t0) * 1000)
            # 延迟分级
            if latency < 500:
                grade = "fast"
            elif latency < 1500:
                grade = "medium"
            else:
                grade = "slow"
            return {"source": s.name, "icon": s.icon, "status": "online",
                    "latency_ms": latency, "code": resp.status_code, "grade": grade}
        except:
            latency = int((time.time() - t0) * 1000)
            return {"source": s.name, "icon": s.icon, "status": "offline",
                    "latency_ms": latency, "code": 0, "grade": "offline"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for r in pool.map(_ping, sources):
            results.append(r)
    results.sort(key=lambda r: (0 if r["status"]=="online" else 1, r["latency_ms"]))
    return jsonify(results)

# ─── Image Cache & Pre-fetch ───
_img_cache = {}  # url -> (bytes, content_type, timestamp)
_img_cache_lock = threading.Lock()
_img_downloading = {}  # url -> threading.Event (in-flight download dedup)
_img_downloading_lock = threading.Lock()
_IMG_CACHE_MAX = 2000
_IMG_CACHE_TTL = 7200  # 2 hours

# 复用的高并发 session (带连接池)
_proxy_session = None
_proxy_session_lock = threading.Lock()

def _get_proxy_session():
    global _proxy_session
    if _proxy_session is None:
        with _proxy_session_lock:
            if _proxy_session is None:
                import requests as req
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry
                s = req.Session()
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })
                adapter = HTTPAdapter(
                    pool_connections=80,
                    pool_maxsize=150,
                    max_retries=Retry(total=2, backoff_factor=0.1),
                    pool_block=False,
                )
                s.mount("http://", adapter)
                s.mount("https://", adapter)
                _proxy_session = s
    return _proxy_session

def _find_session_for_url(url):
    """找到匹配 URL 的源 session (带连接池)"""
    for s in sources:
        if s.base_url and s.base_url in url:
            return s.session
        if s.base_url:
            domain = s.base_url.split('//')[1].split('/')[0]
            if domain in url:
                return s.session
    # 通用高性能 session (复用连接池)
    return _get_proxy_session()

def _download_cover_to_cache(url):
    """下载图片到缓存 (带去重)"""
    if not url or url.startswith('data:'):
        return False
    now = time.time()
    with _img_cache_lock:
        if url in _img_cache:
            _, _, ts = _img_cache[url]
            if now - ts < _IMG_CACHE_TTL:
                return True

    # 去重: 如果已有线程在下载同一 URL, 等待其完成
    with _img_downloading_lock:
        if url in _img_downloading:
            evt = _img_downloading[url]
            evt.wait(timeout=15)
            with _img_cache_lock:
                return url in _img_cache
        evt = threading.Event()
        _img_downloading[url] = evt

    try:
        session = _find_session_for_url(url)
        referer = url.rsplit('/', 1)[0] + '/'
        resp = session.get(url, timeout=(3, 10),
                           headers={"Referer": referer})
        resp.raise_for_status()
        data = resp.content
        ct = resp.headers.get("Content-Type", "image/jpeg")
        with _img_cache_lock:
            if len(_img_cache) >= _IMG_CACHE_MAX:
                # 批量清理最旧的 10%
                to_evict = _IMG_CACHE_MAX // 10
                oldest_keys = sorted(_img_cache, key=lambda k: _img_cache[k][2])[:to_evict]
                for k in oldest_keys:
                    del _img_cache[k]
            _img_cache[url] = (data, ct, time.time())
        return True
    except:
        return False
    finally:
        evt.set()
        with _img_downloading_lock:
            _img_downloading.pop(url, None)

def _prefetch_covers(results):
    """后台批量预下载封面到缓存"""
    urls = [r.get("cover") for r in results if r.get("cover") and not r["cover"].startswith("data:")]
    urls = [u for u in urls if u not in _img_cache]
    if not urls:
        return
    def _do():
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            done = sum(pool.map(_download_cover_to_cache, urls))
        print(f"[PREFETCH] {done}/{len(urls)} covers cached")
    threading.Thread(target=_do, daemon=True).start()

# ─── API: Batch Image Prefetch (reader speed boost) ───
@app.route("/api/img-prefetch", methods=["POST"])
def api_img_prefetch():
    """批量预取图片到缓存 — 立即返回, 后台并行下载"""
    data = request.json or {}
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"status": "empty"})
    # 过滤已缓存的
    with _img_cache_lock:
        urls = [u for u in urls if u not in _img_cache
                or time.time() - _img_cache[u][2] > _IMG_CACHE_TTL]
    if not urls:
        return jsonify({"status": "all_cached"})
    # ★ 关键: 先注册所有 Event, 让 proxy 请求能找到并等待
    events = {}
    with _img_downloading_lock:
        for u in urls:
            if u not in _img_downloading:
                evt = threading.Event()
                _img_downloading[u] = evt
                events[u] = evt

    def _bg_prefetch(url_list, evts):
        def _dl_one(url):
            """下载单张图到缓存, 完成后通知 Event"""
            if not url or url.startswith('data:'):
                return False
            # 已缓存?
            with _img_cache_lock:
                if url in _img_cache:
                    _, _, ts = _img_cache[url]
                    if time.time() - ts < _IMG_CACHE_TTL:
                        return True
            try:
                session = _find_session_for_url(url)
                referer = url.rsplit('/', 1)[0] + '/'
                resp = session.get(url, timeout=(3, 10),
                                   headers={"Referer": referer})
                resp.raise_for_status()
                data = resp.content
                ct = resp.headers.get("Content-Type", "image/jpeg")
                with _img_cache_lock:
                    if len(_img_cache) >= _IMG_CACHE_MAX:
                        to_evict = _IMG_CACHE_MAX // 10
                        oldest_keys = sorted(_img_cache, key=lambda k: _img_cache[k][2])[:to_evict]
                        for k in oldest_keys:
                            del _img_cache[k]
                    _img_cache[url] = (data, ct, time.time())
                return True
            except:
                return False
            finally:
                evt = evts.get(url)
                if evt:
                    evt.set()
                with _img_downloading_lock:
                    _img_downloading.pop(url, None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            done = sum(pool.map(_dl_one, url_list))
        print(f"[READER PREFETCH] {done}/{len(url_list)} images cached")

    threading.Thread(target=_bg_prefetch, args=(urls, events), daemon=True).start()
    return jsonify({"status": "started", "count": len(urls)})

# ─── API: Image Proxy ───
@app.route("/api/img-proxy")
def api_img_proxy():
    url = request.args.get("url", "")
    if not url:
        return Response("Missing url", status=400)

    # 检查缓存
    now = time.time()
    with _img_cache_lock:
        if url in _img_cache:
            data, ct, ts = _img_cache[url]
            if now - ts < _IMG_CACHE_TTL:
                return Response(data, mimetype=ct or "image/jpeg",
                                headers={"Cache-Control": "public, max-age=3600"})

    # 如果 prefetch 正在下载这个 URL, 等它完成而不是重复下载
    with _img_downloading_lock:
        evt = _img_downloading.get(url)
    if evt:
        evt.wait(timeout=12)
        with _img_cache_lock:
            if url in _img_cache:
                data, ct, _ = _img_cache[url]
                return Response(data, mimetype=ct,
                                headers={"Cache-Control": "public, max-age=3600"})

    # 缓存未命中 → 自己下载
    if _download_cover_to_cache(url):
        with _img_cache_lock:
            data, ct, _ = _img_cache[url]
        return Response(data, mimetype=ct,
                        headers={"Cache-Control": "public, max-age=3600"})
    return Response("Failed to fetch image", status=502)

# ─── API: Speed Test (real image download) ───
@app.route("/api/speed-test")
def api_speed_test():
    src_name = request.args.get("source", "")
    manga_url = request.args.get("url", "")
    source = None
    for s in sources:
        if s.name == src_name:
            source = s; break
    if not source or not manga_url:
        return jsonify({"error": "bad params"}), 400
    try:
        info = source.get_manga_info(manga_url)
        chs = source.get_chapters(manga_url, info.get("manga_id"))
        if not chs:
            return jsonify({"speed_kbs": 0})
        # 取第一章的第一张图片测速
        imgs = source.get_chapter_images(chs[0]["url"])
        if not imgs:
            return jsonify({"speed_kbs": 0})
        t0 = time.time()
        data = source.download_image(imgs[0])
        elapsed = time.time() - t0
        if data and elapsed > 0:
            speed = len(data) / 1024 / elapsed
            return jsonify({"speed_kbs": round(speed, 1), "size_bytes": len(data), "elapsed_ms": int(elapsed*1000)})
        return jsonify({"speed_kbs": 0})
    except Exception as e:
        return jsonify({"speed_kbs": 0, "error": str(e)})

# ─── API: Manga Detail ───
@app.route("/api/detail")
def api_detail():
    url = request.args.get("url", "")
    src_name = request.args.get("source", "")
    if not url:
        return jsonify({"error": "no url"}), 400

    source = sources[0]
    for s in sources:
        if s.name == src_name or s.base_url in url:
            source = s
            break

    try:
        info = source.get_manga_info(url)
        chapters = source.get_chapters(url, info.get("manga_id"))
        return jsonify({"info": info, "chapters": chapters, "source": source.name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chapter-images")
def api_chapter_images():
    url = request.args.get("url", "")
    src_name = request.args.get("source", "")
    if not url:
        return jsonify({"error": "no url"}), 400
    source = sources[0]
    for s in sources:
        if s.name == src_name or s.base_url in url:
            source = s
            break
    try:
        images = source.get_chapter_images(url)
        # 后台并行预下载所有图片到缓存
        if images:
            def _prefetch_chapter_images(img_urls):
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=32) as pool:
                    pool.map(_download_cover_to_cache, img_urls)
            threading.Thread(target=_prefetch_chapter_images, args=(images,), daemon=True).start()
        return jsonify({"images": images, "source": source.name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── API: Download ───
@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.json
    chapters = data.get("chapters", [])
    manga_title = data.get("title", "Unknown")
    src_name = data.get("source", "")

    source = sources[0]
    for s in sources:
        if s.name == src_name:
            source = s
            break

    dl_manager.clear()
    dl_manager.chapter_concurrency = config["chapter_concurrency"]
    dl_manager.image_concurrency = config["image_concurrency"]
    dl_manager.set_fallback_sources(sources)
    dl_manager.add_tasks(chapters, manga_title, source, config["download_dir"])

    with _log_lock:
        _log_buffer.clear()
    _add_log(f"[START] {manga_title} - {len(chapters)} chapters")

    dl_manager.start()

    # 记录下载日志
    ch_nums = [extract_chapter_number(c.get("title", "")) for c in chapters]
    ch_nums_float = []
    for n in ch_nums:
        try: ch_nums_float.append((float(n), n))
        except: pass
    if ch_nums_float:
        ch_nums_float.sort()
        from_ch = ch_nums_float[0][1]
        to_ch = ch_nums_float[-1][1]
    else:
        from_ch = to_ch = ""
    favorites.add_download_log({
        "manga_title": manga_title,
        "source": src_name,
        "from_chapter": from_ch,
        "to_chapter": to_ch,
        "count": len(chapters),
        "type": "manual",
    })

    return jsonify({"ok": True, "count": len(chapters)})

@app.route("/api/download/status")
def api_download_status():
    tasks = []
    for t in dl_manager.tasks:
        tasks.append({
            "title": t.chapter_title,
            "status": t.status.value,
            "progress": t.progress,
            "total": t.total,
            "speed": round(t.speed, 1),
        })
    done = sum(1 for t in dl_manager.tasks
               if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED))
    return jsonify({"tasks": tasks, "done": done, "total": len(dl_manager.tasks)})

@app.route("/api/download/pause/<int:idx>", methods=["POST"])
def api_pause(idx):
    dl_manager.pause_task(idx)
    return jsonify({"ok": True})

@app.route("/api/download/resume/<int:idx>", methods=["POST"])
def api_resume(idx):
    dl_manager.resume_task(idx)
    return jsonify({"ok": True})

@app.route("/api/download/cancel/<int:idx>", methods=["POST"])
def api_cancel(idx):
    dl_manager.cancel_task(idx)
    return jsonify({"ok": True})

@app.route("/api/download/cancel_all", methods=["POST"])
def api_cancel_all():
    dl_manager.stop_all()
    return jsonify({"ok": True})

# ─── API: Browser Download (Streaming ZIP) ───
@app.route("/api/download/zip", methods=["POST"])
def api_download_zip():
    """流式打包下载 — 边下载图片边写入ZIP流式返回给浏览器，零磁盘占用"""
    data = request.json
    chapters = data.get("chapters", [])
    manga_title = data.get("title", "Unknown")
    src_name = data.get("source", "")
    manga_url = data.get("manga_url", "")

    if not chapters:
        return jsonify({"error": "no chapters"}), 400

    source = sources[0]
    for s in sources:
        if s.name == src_name:
            source = s
            break

    # 清洗文件名
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', manga_title).strip()

    def generate():
        """Generator: 逐章下载图片 → 写入内存ZIP → yield 增量字节 (高速并行版)"""
        from concurrent.futures import ThreadPoolExecutor, as_completed, Future

        buf = BytesIO()
        zf = zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED)
        written = 0  # 已yield的字节位置

        def _flush():
            nonlocal written
            buf.seek(0, 2)
            new_pos = buf.tell()
            if new_pos > written:
                buf.seek(written)
                data = buf.read(new_pos - written)
                written = new_pos
                return data
            return b''

        def _dl_img(img_url):
            for attempt in range(3):
                data = source.download_image(img_url, timeout=20)
                if data:
                    return data
                time.sleep(0.2 * attempt)
            return None

        def _prefetch_images(ch_url):
            try:
                return source.get_chapter_images(ch_url)
            except Exception:
                return []

        # 单个大线程池: 复用连接, 减少创建/销毁开销
        with ThreadPoolExecutor(max_workers=128) as pool:
            # 预取第一章的图片列表
            next_images_future = None
            if chapters:
                next_images_future = pool.submit(
                    _prefetch_images, chapters[0].get("url", ""))

            for ch_idx, ch in enumerate(chapters):
                ch_url = ch.get("url", "")
                ch_title = ch.get("title", f"Chapter_{ch_idx+1}")
                ch_num = extract_chapter_number(ch_title)
                is_raw = "raw" in ch_title.lower()
                safe_ch = format_chapter_dir(ch_num, is_raw)

                # 获取当前章节图片列表 (已预取)
                images = next_images_future.result() if next_images_future else []
                next_images_future = None

                # 提前预取下一章的图片列表
                if ch_idx + 1 < len(chapters):
                    next_images_future = pool.submit(
                        _prefetch_images,
                        chapters[ch_idx + 1].get("url", ""))

                if not images:
                    continue

                # 并行下载当前章节所有图片
                futs = {pool.submit(_dl_img, url): i
                        for i, url in enumerate(images)}
                img_data = {}

                for fut in as_completed(futs):
                    idx = futs[fut]
                    raw = fut.result()
                    if raw:
                        img_data[idx] = raw

                # 按序写入ZIP
                for i in range(len(images)):
                    if i not in img_data:
                        continue
                    raw = img_data[i]
                    ext = '.jpg'
                    if raw[:4] == b'\x89PNG':
                        ext = '.png'
                    elif raw[:4] == b'RIFF':
                        ext = '.webp'
                    elif raw[:3] == b'GIF':
                        ext = '.gif'
                    fname = f"{safe_title}/{safe_ch}/{str(i+1).zfill(3)}{ext}"
                    zf.writestr(fname, raw)
                    del img_data[i]  # 立即释放内存

                    chunk = _flush()
                    if chunk:
                        yield chunk

        # 关闭ZIP (写入 central directory)
        zf.close()
        chunk = _flush()
        if chunk:
            yield chunk

    # 记录下载日志
    ch_nums = [extract_chapter_number(c.get("title", "")) for c in chapters]
    ch_nums_float = []
    for n in ch_nums:
        try: ch_nums_float.append((float(n), n))
        except: pass
    if ch_nums_float:
        ch_nums_float.sort()
        from_ch, to_ch = ch_nums_float[0][1], ch_nums_float[-1][1]
    else:
        from_ch = to_ch = ""
    favorites.add_download_log({
        "manga_title": manga_title,
        "source": src_name,
        "from_chapter": from_ch,
        "to_chapter": to_ch,
        "count": len(chapters),
        "type": "manual",
    })

    # 更新收藏的下载记录 (供追更检测使用)
    if manga_url:
        for c in chapters:
            ch_title = c.get("title", "")
            ch_num = extract_chapter_number(ch_title)
            if ch_num:
                is_raw = "raw" in ch_title.lower()
                favorites.update_download_history(manga_url, ch_num, is_raw=is_raw)

    safe_filename = re.sub(r'[\\/:*?"<>|]', '_', manga_title).strip() + '.zip'
    return Response(
        stream_with_context(generate()),
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename*=UTF-8\'\'{__import__("urllib.parse", fromlist=["quote"]).quote(safe_filename)}',
            'X-Accel-Buffering': 'no',
            'Cache-Control': 'no-cache',
        }
    )

@app.route("/api/download/logs")
def api_logs():
    with _log_lock:
        return jsonify(_log_buffer[:])

# ─── API: Favorites ───
@app.route("/api/favorites")
def api_favorites():
    group = request.args.get("group", "")
    if group and group != "All":
        items = favorites.get_by_group(group)
    else:
        items = favorites.get_all()
    return jsonify({"groups": favorites.get_groups(), "items": items})

@app.route("/api/favorites/add", methods=["POST"])
def api_fav_add():
    d = request.json
    favorites.add(d["title"], d["url"], d.get("cover", ""), d.get("source", ""),
                  d.get("group"))
    return jsonify({"ok": True})

@app.route("/api/favorites/remove", methods=["POST"])
def api_fav_remove():
    favorites.remove(request.json["url"])
    return jsonify({"ok": True})

@app.route("/api/favorites/update_group", methods=["POST"])
def api_fav_group():
    d = request.json
    favorites.update_group(d["url"], d["group"])
    return jsonify({"ok": True})

@app.route("/api/favorites/check")
def api_fav_check():
    url = request.args.get("url", "")
    return jsonify({"favorited": favorites.is_favorited(url)})

@app.route("/api/favorites/batch-update", methods=["POST"])
def api_batch_update():
    """一键追更: 检测新章节并下载"""
    data = request.json or {}
    urls = data.get("urls", [])  # 空=全部
    prefer_raw = data.get("prefer_raw", True)  # True/False/"auto"

    # 自动从下载日志回填缺失的 download_history
    favorites.backfill_from_download_log()

    # 确定追更范围
    if urls:
        targets = [i for i in favorites.get_all()
                    if i["url"] in urls]
    else:
        targets = favorites.get_updatable()

    if not targets:
        return jsonify({"results": [], "summary": "没有可追更的漫画"})

    results = []
    total_new = 0

    def _check_one(item):
        """检查单部漫画的新章节"""
        hist = item.get("download_history") or {}
        last_ch = hist.get("last_chapter", "0")
        try:
            last_num = float(last_ch)
        except (ValueError, TypeError):
            last_num = 0

        # 自动模式: 根据每部漫画的历史版本决定
        if prefer_raw == "auto":
            item_version = hist.get("last_version", "raw")
            item_prefer_raw = (item_version == "raw")
        else:
            item_prefer_raw = prefer_raw

        # 找到对应的源
        source = None
        for s in sources:
            if s.name == item.get("source"):
                source = s
                break
        if not source:
            return {"title": item["title"], "url": item["url"],
                    "source": item.get("source", ""),
                    "status": "error", "message": "源不可用",
                    "new_chapters": []}

        try:
            info = source.get_manga_info(item["url"])
            chapters = source.get_chapters(item["url"], info.get("manga_id"))
        except Exception as e:
            return {"title": item["title"], "url": item["url"],
                    "source": item.get("source", ""),
                    "status": "error", "message": str(e),
                    "new_chapters": []}

        # 过滤新章节
        new_chs = []
        for ch in chapters:
            ch_num_str = re.search(r'(\d+(?:\.\d+)?)', ch.get("title", ""))
            if not ch_num_str:
                continue
            ch_num = float(ch_num_str.group(1))
            if ch_num <= last_num:
                continue
            # 已下载过的跳过
            if ch_num_str.group(1) in hist.get("chapters", []):
                continue

            title_lower = ch.get("title", "").lower()
            is_raw = "raw" in title_lower

            # 自动模式: 不做 raw/翻译 过滤, 接受所有新章节
            if prefer_raw != "auto":
                if item_prefer_raw and not is_raw:
                    continue
                if not item_prefer_raw and is_raw:
                    continue

            new_chs.append({
                "title": ch["title"], "url": ch["url"],
                "chapter_num": ch_num_str.group(1),
            })

        if new_chs:
            return {"title": item["title"], "url": item["url"],
                    "source": item.get("source", ""),
                    "status": "has_updates", "new_chapters": new_chs}
        else:
            return {"title": item["title"], "url": item["url"],
                    "source": item.get("source", ""),
                    "status": "up_to_date", "new_chapters": [],
                    "last_chapter": last_ch}

    # 并行检查
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(_check_one, t): t for t in targets}
        for fut in concurrent.futures.as_completed(futs, timeout=30):
            try:
                r = fut.result()
                results.append(r)
                total_new += len(r.get("new_chapters", []))
            except Exception:
                t = futs[fut]
                results.append({"title": t["title"], "url": t["url"],
                                "status": "error", "message": "超时",
                                "new_chapters": []})

    has_updates = sum(1 for r in results if r["status"] == "has_updates")
    up_to_date = sum(1 for r in results if r["status"] == "up_to_date")
    errors = sum(1 for r in results if r["status"] == "error")

    return jsonify({
        "results": results,
        "summary": {
            "total": len(results),
            "has_updates": has_updates,
            "up_to_date": up_to_date,
            "errors": errors,
            "new_chapters": total_new,
        }
    })

@app.route("/api/favorites/start-update", methods=["POST"])
def api_start_update():
    """根据 batch-update 的结果, 提交下载任务"""
    data = request.json or {}
    items = data.get("items", [])  # [{url, source, chapters: [{title, url}]}]

    if not items:
        return jsonify({"ok": False, "error": "无下载项"})

    dl_manager.clear()
    dl_manager.chapter_concurrency = config["chapter_concurrency"]
    dl_manager.image_concurrency = config["image_concurrency"]
    dl_manager.set_fallback_sources(sources)

    total_chs = 0
    for item in items:
        source = None
        for s in sources:
            if s.name == item.get("source"):
                source = s
                break
        if not source:
            continue
        chs = item.get("chapters", [])
        if chs:
            dl_manager.add_tasks(chs, item.get("title", "Unknown"),
                                 source, config["download_dir"])
            total_chs += len(chs)

    if total_chs == 0:
        return jsonify({"ok": False, "error": "无有效章节"})

    with _log_lock:
        _log_buffer.clear()
    _add_log(f"[追更] 开始下载 {len(items)} 部漫画，共 {total_chs} 章")

    # 记录追更日志 (含章节详情)
    chapter_details = []
    for item in items:
        chs = item.get("chapters", [])
        if not chs:
            continue
        ch_nums = [extract_chapter_number(c.get("title", "")) for c in chs]
        ch_nums_float = []
        for n in ch_nums:
            try: ch_nums_float.append((float(n), n))
            except: pass
        if ch_nums_float:
            ch_nums_float.sort()
            from_ch = ch_nums_float[0][1]
            to_ch = ch_nums_float[-1][1]
        else:
            from_ch = to_ch = ""
        chapter_details.append({
            "title": item.get("title", ""),
            "from": from_ch,
            "to": to_ch,
            "count": len(chs),
        })

    favorites.add_update_log({
        "manga_count": len(items),
        "chapter_count": total_chs,
        "titles": [i.get("title", "") for i in items],
        "chapter_details": chapter_details,
    })

    # 同时记录到下载日志
    for d in chapter_details:
        favorites.add_download_log({
            "manga_title": d["title"],
            "source": items[0].get("source", "") if items else "",
            "from_chapter": d["from"],
            "to_chapter": d["to"],
            "count": d["count"],
            "type": "update",
        })

    dl_manager.start()
    return jsonify({"ok": True, "count": total_chs})

# ─── API: Browser Batch Update (Streaming ZIP) ───
@app.route("/api/favorites/start-update-zip", methods=["POST"])
def api_start_update_zip():
    """追更结果 → 流式ZIP下载到浏览器，零磁盘占用"""
    data = request.json or {}
    items = data.get("items", [])  # [{title, url, source, chapters: [{title, url}]}]

    if not items:
        return jsonify({"error": "无下载项"}), 400

    def generate():
        from concurrent.futures import ThreadPoolExecutor, as_completed

        buf = BytesIO()
        zf = zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED)
        written = 0

        def _flush():
            nonlocal written
            buf.seek(0, 2)
            new_pos = buf.tell()
            if new_pos > written:
                buf.seek(written)
                data = buf.read(new_pos - written)
                written = new_pos
                return data
            return b''

        # 单个大线程池复用连接
        with ThreadPoolExecutor(max_workers=128) as pool:
            for item in items:
                manga_title = item.get("title", "Unknown")
                src_name = item.get("source", "")
                chapters = item.get("chapters", [])
                if not chapters:
                    continue

                source = sources[0]
                for s in sources:
                    if s.name == src_name:
                        source = s
                        break

                safe_manga = re.sub(r'[\\/:*?"<>|]', '_', manga_title).strip()

                def _dl_img(img_url, src=source):
                    for attempt in range(3):
                        d = src.download_image(img_url, timeout=20)
                        if d:
                            return d
                        time.sleep(0.2 * attempt)
                    return None

                def _prefetch(ch_url, src=source):
                    try:
                        return src.get_chapter_images(ch_url)
                    except Exception:
                        return []

                # 预取第一章图片列表
                next_images_future = pool.submit(
                    _prefetch, chapters[0].get("url", "")) if chapters else None

                for ch_idx, ch in enumerate(chapters):
                    ch_title = ch.get("title", f"Chapter_{ch_idx+1}")
                    ch_num = extract_chapter_number(ch_title)
                    is_raw = "raw" in ch_title.lower()
                    safe_ch = format_chapter_dir(ch_num, is_raw)

                    images = next_images_future.result() if next_images_future else []
                    next_images_future = None

                    if ch_idx + 1 < len(chapters):
                        next_images_future = pool.submit(
                            _prefetch, chapters[ch_idx + 1].get("url", ""))

                    if not images:
                        continue

                    futs = {pool.submit(_dl_img, url): i
                            for i, url in enumerate(images)}
                    img_data = {}

                    for fut in as_completed(futs):
                        idx = futs[fut]
                        raw = fut.result()
                        if raw:
                            img_data[idx] = raw

                    for i in range(len(images)):
                        if i not in img_data:
                            continue
                        raw = img_data[i]
                        ext = '.jpg'
                        if raw[:4] == b'\x89PNG':
                            ext = '.png'
                        elif raw[:4] == b'RIFF':
                            ext = '.webp'
                        elif raw[:3] == b'GIF':
                            ext = '.gif'
                        fname = f"{safe_manga}/{safe_ch}/{str(i+1).zfill(3)}{ext}"
                        zf.writestr(fname, raw)
                        del img_data[i]

                        chunk = _flush()
                        if chunk:
                            yield chunk

        zf.close()
        chunk = _flush()
        if chunk:
            yield chunk

    # 记录追更日志
    chapter_details = []
    total_chs = 0
    for item in items:
        chs = item.get("chapters", [])
        if not chs:
            continue
        total_chs += len(chs)
        ch_nums = [extract_chapter_number(c.get("title", "")) for c in chs]
        ch_nums_float = []
        for n in ch_nums:
            try: ch_nums_float.append((float(n), n))
            except: pass
        if ch_nums_float:
            ch_nums_float.sort()
            from_ch, to_ch = ch_nums_float[0][1], ch_nums_float[-1][1]
        else:
            from_ch = to_ch = ""
        chapter_details.append({"title": item.get("title", ""), "from": from_ch, "to": to_ch, "count": len(chs)})

    favorites.add_update_log({
        "manga_count": len(items),
        "chapter_count": total_chs,
        "titles": [i.get("title", "") for i in items],
        "chapter_details": chapter_details,
    })
    for d in chapter_details:
        favorites.add_download_log({
            "manga_title": d["title"],
            "source": items[0].get("source", "") if items else "",
            "from_chapter": d["from"],
            "to_chapter": d["to"],
            "count": d["count"],
            "type": "update",
        })

    # 更新收藏的下载记录 (供追更检测使用)
    for item in items:
        manga_url = item.get("url", "")
        if manga_url:
            for c in item.get("chapters", []):
                ch_title = c.get("title", "")
                ch_num = extract_chapter_number(ch_title)
                if ch_num:
                    is_raw = "raw" in ch_title.lower()
                    favorites.update_download_history(manga_url, ch_num, is_raw=is_raw)

    from datetime import datetime
    date_str = datetime.now().strftime('%Y-%m-%d')
    safe_filename = f'追更_{date_str}.zip'
    return Response(
        stream_with_context(generate()),
        mimetype='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename*=UTF-8\'\''
                                   + __import__("urllib.parse", fromlist=["quote"]).quote(safe_filename),
            'X-Accel-Buffering': 'no',
            'Cache-Control': 'no-cache',
        }
    )

@app.route("/api/favorites/scan-history", methods=["POST"])
def api_scan_history():
    """扫描下载目录, 回填历史"""
    count = favorites.scan_download_dir(config["download_dir"])
    return jsonify({"ok": True, "backfilled": count})

@app.route("/api/favorites/check-new")
def api_check_new():
    """静默检查有多少收藏有新章节 (导航徽章用)"""
    updatable = favorites.get_updatable()
    if not updatable:
        return jsonify({"count": 0})

    count = 0
    def _quick_check(item):
        hist = item.get("download_history") or {}
        try:
            last_num = float(hist.get("last_chapter", "0"))
        except:
            return False
        source = None
        for s in sources:
            if s.name == item.get("source"):
                source = s; break
        if not source:
            return False
        try:
            info = source.get_manga_info(item["url"])
            chs = source.get_chapters(item["url"], info.get("manga_id"))
            for ch in chs:
                m = re.search(r'(\d+(?:\.\d+)?)', ch.get("title", ""))
                if m and float(m.group(1)) > last_num:
                    return True
        except:
            pass
        return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        count = sum(pool.map(_quick_check, updatable))

    return jsonify({"count": count})

@app.route("/api/favorites/update-log")
def api_update_log():
    return jsonify(favorites.get_update_log())

@app.route("/api/download/history")
def api_download_history():
    return jsonify(favorites.get_download_log())

@app.route("/api/download/history/clear", methods=["POST"])
def api_download_history_clear():
    favorites.clear_download_log()
    return jsonify({"ok": True})

# ─── API: Config ───
@app.route("/api/config")
def api_config():
    return jsonify({
        "download_dir": config["download_dir"],
        "chapter_concurrency": config["chapter_concurrency"],
        "image_concurrency": config["image_concurrency"],
        "proxy_mode": config["proxy_mode"],
        "proxy_host": config["proxy_host"],
        "proxy_port": config["proxy_port"],
        "theme": config.get("theme", "dark"),
        "search_history": config.get_search_history(),
    })

@app.route("/api/config", methods=["POST"])
def api_config_save():
    d = request.json
    for k in ["download_dir", "chapter_concurrency", "image_concurrency",
              "proxy_mode", "proxy_host", "proxy_port", "theme"]:
        if k in d:
            config[k] = d[k]
    config.save()
    # Apply proxy
    proxies = config.get_proxy_dict()
    for s in sources:
        s.session.proxies = proxies or {}
    return jsonify({"ok": True})

# ─── API: Health Check ───
@app.route("/api/health")
def api_health():
    results = {}
    def _check(s):
        try:
            t0 = time.time()
            import requests as req
            resp = req.get(s.base_url, timeout=10,
                          headers={"User-Agent": "Mozilla/5.0"})
            ms = int((time.time() - t0) * 1000)
            return s.name, resp.status_code < 400, ms
        except:
            return s.name, False, -1

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for name, ok, ms in pool.map(_check, sources):
            results[name] = {"ok": ok, "ms": ms}
    return jsonify(results)

# ─── API: Stats ───
@app.route("/api/stats")
def api_stats():
    dd = config["download_dir"]
    manga_count = 0
    total_size = 0
    IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
    if os.path.exists(dd):
        for d in os.listdir(dd):
            dpath = os.path.join(dd, d)
            if not os.path.isdir(dpath):
                continue
            # 判断是否为漫画目录: 至少有一个子文件夹包含图片文件
            is_manga = False
            for sub in os.listdir(dpath):
                subpath = os.path.join(dpath, sub)
                if os.path.isdir(subpath):
                    for f in os.listdir(subpath):
                        if os.path.splitext(f)[1].lower() in IMG_EXT:
                            is_manga = True
                            break
                if is_manga:
                    break
            if is_manga:
                manga_count += 1
                for root, _, files in os.walk(dpath):
                    for f in files:
                        try: total_size += os.path.getsize(os.path.join(root, f))
                        except: pass
    return jsonify({
        "manga_count": manga_count,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "favorites_count": len(favorites.get_all()),
    })


if __name__ == "__main__":
    import webbrowser
    port = 5000
    print(f"Starting server at http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

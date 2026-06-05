import concurrent.futures
import threading
import time


def get_proxy_session(state):
    if state.proxy_session is None:
        with state.proxy_session_lock:
            if state.proxy_session is None:
                import requests as req
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry

                session = req.Session()
                session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })
                adapter = HTTPAdapter(
                    pool_connections=80,
                    pool_maxsize=150,
                    max_retries=Retry(total=2, backoff_factor=0.1),
                    pool_block=False,
                )
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                state.proxy_session = session
    return state.proxy_session


def find_session_for_url(state, url):
    for source in state.sources:
        if source.base_url and source.base_url in url:
            return source.session
        if source.base_url:
            domain = source.base_url.split("//")[1].split("/")[0]
            if domain in url:
                return source.session
    return get_proxy_session(state)


def download_cover_to_cache(state, url):
    if not url or url.startswith("data:"):
        return False
    now = time.time()
    with state.img_cache_lock:
        if url in state.img_cache:
            _, _, ts = state.img_cache[url]
            if now - ts < state.img_cache_ttl:
                return True

    with state.img_downloading_lock:
        if url in state.img_downloading:
            evt = state.img_downloading[url]
            evt.wait(timeout=15)
            with state.img_cache_lock:
                return url in state.img_cache
        evt = threading.Event()
        state.img_downloading[url] = evt

    try:
        session = find_session_for_url(state, url)
        referer = url.rsplit("/", 1)[0] + "/"
        response = session.get(url, timeout=(3, 10), headers={"Referer": referer})
        response.raise_for_status()
        data = response.content
        ct = response.headers.get("Content-Type", "image/jpeg")
        with state.img_cache_lock:
            if len(state.img_cache) >= state.img_cache_max:
                to_evict = state.img_cache_max // 10
                oldest_keys = sorted(state.img_cache, key=lambda key: state.img_cache[key][2])[:to_evict]
                for key in oldest_keys:
                    del state.img_cache[key]
            state.img_cache[url] = (data, ct, time.time())
        return True
    except Exception:
        return False
    finally:
        evt.set()
        with state.img_downloading_lock:
            state.img_downloading.pop(url, None)


def prefetch_covers(state, results):
    urls = [item.get("cover") for item in results if item.get("cover") and not item["cover"].startswith("data:")]
    urls = [url for url in urls if url not in state.img_cache]
    if not urls:
        return

    def _do():
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            done = sum(pool.map(lambda url: download_cover_to_cache(state, url), urls))
        print(f"[PREFETCH] {done}/{len(urls)} covers cached")

    threading.Thread(target=_do, daemon=True).start()


def start_batch_prefetch(state, urls):
    with state.img_cache_lock:
        urls = [url for url in urls if url not in state.img_cache or time.time() - state.img_cache[url][2] > state.img_cache_ttl]
    if not urls:
        return "all_cached", 0

    events = {}
    with state.img_downloading_lock:
        for url in urls:
            if url not in state.img_downloading:
                evt = threading.Event()
                state.img_downloading[url] = evt
                events[url] = evt

    def _bg_prefetch(url_list, evts):
        def _dl_one(url):
            if not url or url.startswith("data:"):
                return False
            with state.img_cache_lock:
                if url in state.img_cache:
                    _, _, ts = state.img_cache[url]
                    if time.time() - ts < state.img_cache_ttl:
                        return True
            try:
                session = find_session_for_url(state, url)
                referer = url.rsplit("/", 1)[0] + "/"
                response = session.get(url, timeout=(3, 10), headers={"Referer": referer})
                response.raise_for_status()
                data = response.content
                ct = response.headers.get("Content-Type", "image/jpeg")
                with state.img_cache_lock:
                    if len(state.img_cache) >= state.img_cache_max:
                        to_evict = state.img_cache_max // 10
                        oldest_keys = sorted(state.img_cache, key=lambda key: state.img_cache[key][2])[:to_evict]
                        for key in oldest_keys:
                            del state.img_cache[key]
                    state.img_cache[url] = (data, ct, time.time())
                return True
            except Exception:
                return False
            finally:
                evt = evts.get(url)
                if evt:
                    evt.set()
                with state.img_downloading_lock:
                    state.img_downloading.pop(url, None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            done = sum(pool.map(_dl_one, url_list))
        print(f"[READER PREFETCH] {done}/{len(url_list)} images cached")

    threading.Thread(target=_bg_prefetch, args=(urls, events), daemon=True).start()
    return "started", len(urls)

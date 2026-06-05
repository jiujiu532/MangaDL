import concurrent.futures
import threading
import time


def fetch_source_page(state, method_name, target_sources, src_page):
    """从所有源抓取第 src_page 页。"""
    per_source = []
    any_has_more = False

    def _fetch(source):
        try:
            items = getattr(source, method_name)(src_page)
            for result in items:
                result["_source"] = source.name
            state.source_health[source.name] = {"status": "online", "ts": time.time()}
            return items
        except Exception:
            state.source_health[source.name] = {"status": "offline", "ts": time.time()}
            return []

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
    futures = {pool.submit(_fetch, source): source for source in target_sources}
    try:
        for future in concurrent.futures.as_completed(futures, timeout=10):
            try:
                result = future.result(timeout=0.1)
                if result:
                    per_source.append(result)
                    if len(result) >= 5:
                        any_has_more = True
            except Exception:
                pass
    except (TimeoutError, concurrent.futures.TimeoutError):
        for future, source in futures.items():
            if not future.done():
                state.source_health[source.name] = {"status": "offline", "ts": time.time()}
    pool.shutdown(wait=False)

    all_items = []
    if per_source:
        max_len = max(len(group) for group in per_source)
        for index in range(max_len):
            for group in per_source:
                if index < len(group):
                    all_items.append(group[index])
    return all_items, any_has_more


def dedup_items(items):
    seen = set()
    unique = []
    for result in items:
        url = result.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(result)
    return unique


def resolve_targets(state, src_name):
    if src_name:
        return [source for source in state.sources if source.name == src_name]
    active = []
    now = time.time()
    for source in state.sources:
        health = state.source_health.get(source.name)
        if health and health["status"] == "offline" and now - health["ts"] < state.health_ttl:
            continue
        active.append(source)
    return active if active else state.sources


def get_or_create_pool(state, prefetch_covers, method_name, src_name=""):
    pool_key = f"{method_name}:{src_name}"
    now = time.time()
    if pool_key in state.listing_pool:
        pool_data = state.listing_pool[pool_key]
        if now - pool_data["ts"] < state.cache_ttl:
            return pool_data

    target = resolve_targets(state, src_name)
    all_items = []
    exhausted = False
    next_src = 1
    for src_page in range(1, state.initial_src_pages + 1):
        items, has_more = fetch_source_page(state, method_name, target, src_page)
        all_items.extend(items)
        next_src = src_page + 1
        if not has_more:
            exhausted = True
            break

    unique = dedup_items(all_items)
    pool_data = {
        "ts": now,
        "items": unique,
        "next_src_page": next_src,
        "exhausted": exhausted,
        "target": target,
        "method": method_name,
    }
    state.listing_pool[pool_key] = pool_data
    prefetch_covers(unique)
    return pool_data


def expand_pool(state, prefetch_covers, pool_key, pool_data, count=None):
    if pool_data["exhausted"]:
        return
    with state.expand_lock:
        if pool_key in state.expanding:
            return
        state.expanding.add(pool_key)
    try:
        target = pool_data["target"]
        method = pool_data["method"]
        rounds = count or state.expand_src_pages
        start = pool_data["next_src_page"]
        end = start + rounds

        new_items = []
        exhausted = False
        next_src = start
        for src_page in range(start, end):
            items, has_more = fetch_source_page(state, method, target, src_page)
            new_items.extend(items)
            next_src = src_page + 1
            if not has_more:
                exhausted = True
                break

        if new_items:
            existing_urls = {item.get("url", "") for item in pool_data["items"]}
            for result in new_items:
                url = result.get("url", "")
                if url and url not in existing_urls:
                    existing_urls.add(url)
                    pool_data["items"].append(result)
            prefetch_covers(new_items)

        pool_data["next_src_page"] = next_src
        pool_data["exhausted"] = exhausted
    finally:
        with state.expand_lock:
            state.expanding.discard(pool_key)


def ensure_bg_expand(state, prefetch_covers, pool_key, pool_data):
    if pool_data["exhausted"] or pool_key in state.bg_loop_running:
        return
    state.bg_loop_running.add(pool_key)

    def _bg_loop():
        try:
            while not pool_data["exhausted"]:
                expand_pool(state, prefetch_covers, pool_key, pool_data)
                time.sleep(0.5)
        finally:
            state.bg_loop_running.discard(pool_key)

    threading.Thread(target=_bg_loop, daemon=True).start()


def fetch_listing(state, prefetch_covers, method_name: str, src_name: str = "", page: int = 1):
    pool_data = get_or_create_pool(state, prefetch_covers, method_name, src_name)
    pool_key = f"{method_name}:{src_name}"

    total = len(pool_data["items"])
    total_pages = max(1, (total + state.page_size - 1) // state.page_size)

    if page > total_pages and not pool_data["exhausted"]:
        for _ in range(25):
            if pool_key not in state.expanding:
                break
            time.sleep(0.2)
        total = len(pool_data["items"])
        total_pages = max(1, (total + state.page_size - 1) // state.page_size)
        if page > total_pages:
            items_before = len(pool_data["items"])
            needed = page * state.page_size
            extra = min(max(2, (needed - items_before) // 20 + 1), 10)
            expand_pool(state, prefetch_covers, pool_key, pool_data, extra)
            items_after = len(pool_data["items"])
            total = items_after
            total_pages = max(1, (total + state.page_size - 1) // state.page_size)
            if items_after == items_before:
                pool_data["exhausted"] = True

    if page >= 1 and not pool_data["exhausted"]:
        ensure_bg_expand(state, prefetch_covers, pool_key, pool_data)

    start = (page - 1) * state.page_size
    end = start + state.page_size
    items = pool_data["items"][start:end]

    exhausted = pool_data["exhausted"]
    has_next = (not exhausted and page <= total_pages) or page < total_pages
    return {
        "items": items,
        "page": page,
        "total_pages": total_pages,
        "has_next": has_next,
    }

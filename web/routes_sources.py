import concurrent.futures
import difflib
import re
import threading
import time

from flask import jsonify, request

from .image_cache import download_cover_to_cache, prefetch_covers
from .listing_cache import fetch_listing
from .utils import fuzzy_match, get_source_by_name_or_url


def register(app, state):
    @app.route("/api/sources")
    def api_sources():
        return jsonify([
            {"name": source.name, "icon": source.icon, "url": source.base_url}
            for source in state.sources
        ])

    @app.route("/api/search")
    def api_search():
        kw = request.args.get("q", "").strip()
        src_name = request.args.get("source", "")
        if not kw:
            return jsonify([])

        state.config.add_search_history(kw)
        state.config.save()

        target_sources = state.sources
        if src_name:
            target_sources = [source for source in state.sources if source.name == src_name]

        def _search_one(source):
            try:
                results = source.search(kw)
                for result in results:
                    result["_source"] = source.name
                return results
            except Exception:
                return []

        all_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_search_one, source): source for source in target_sources}
            for future in concurrent.futures.as_completed(futures):
                all_results.extend(future.result())

        kw_lower = kw.lower()
        kw_words = [word for word in kw_lower.split() if word]
        min_ratio = 1.0 if len(kw_words) <= 3 else 0.6

        scored = []
        for result in all_results:
            title = result.get("title", "").lower()
            if kw_lower in title:
                scored.append((0, result))
                continue
            if kw_words:
                matched = 0
                for word in kw_words:
                    if re.search(r"(?:^|[\s\-_,.()\[\]])" + re.escape(word) + r"(?:$|[\s\-_,.()\[\]])", title):
                        matched += 1
                ratio = matched / len(kw_words)
                if ratio >= min_ratio:
                    scored.append((1 - ratio, result))
                    continue
            similarity = difflib.SequenceMatcher(None, kw_lower, title).ratio()
            if similarity >= 0.65:
                scored.append((1 - similarity, result))

        scored.sort(key=lambda item: item[0])
        return jsonify([result for _, result in scored])

    @app.route("/api/popular")
    def api_popular():
        src_name = request.args.get("source", "")
        page = int(request.args.get("page", 1))
        return jsonify(fetch_listing(state, lambda items: prefetch_covers(state, items), "get_popular", src_name, page))

    @app.route("/api/latest")
    def api_latest():
        src_name = request.args.get("source", "")
        page = int(request.args.get("page", 1))
        return jsonify(fetch_listing(state, lambda items: prefetch_covers(state, items), "get_latest", src_name, page))

    @app.route("/api/cross-source")
    def api_cross_source():
        title = request.args.get("title", "").strip()
        current = request.args.get("current_source", "")
        if not title:
            return jsonify([])

        def _probe(source):
            started = time.time()
            try:
                try:
                    source.session.head(source.base_url, timeout=3)
                except Exception:
                    latency = int((time.time() - started) * 1000)
                    return {"source": source.name, "icon": source.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "offline"}

                hits = source.search(title)
                latency = int((time.time() - started) * 1000)
                best = None
                best_score = 0
                for hit in hits:
                    score = fuzzy_match(title, hit.get("title", ""))
                    if score > best_score:
                        best_score, best = score, hit
                if best and best_score >= 0.75:
                    ch_count = 0
                    try:
                        info = source.get_manga_info(best["url"])
                        chapters = source.get_chapters(best["url"], info.get("manga_id"))
                        seen_nums = set()
                        for chapter in chapters:
                            match = re.search(r"#?([\d]+(?:\.[\d]+)?)", chapter.get("title", ""))
                            seen_nums.add(match.group(1) if match else chapter.get("title", ""))
                        ch_count = len(seen_nums)
                    except Exception:
                        pass
                    total_ms = int((time.time() - started) * 1000)
                    return {
                        "source": source.name,
                        "icon": source.icon,
                        "latency_ms": total_ms,
                        "match": {"title": best.get("title", ""), "url": best.get("url", ""), "cover": best.get("cover", "")},
                        "chapter_count": ch_count,
                        "status": "found",
                    }
                return {"source": source.name, "icon": source.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "not_found"}
            except Exception:
                latency = int((time.time() - started) * 1000)
                return {"source": source.name, "icon": source.icon, "latency_ms": latency, "match": None, "chapter_count": 0, "status": "error"}

        results = []
        other_sources = [source for source in state.sources if source.name != current]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_probe, source): source for source in other_sources}
            for future in concurrent.futures.as_completed(futures, timeout=20):
                try:
                    results.append(future.result())
                except Exception:
                    pass

        results.sort(key=lambda result: (0 if result.get("match") else 1, result["latency_ms"]))
        return jsonify({"current_source": current, "results": results})

    @app.route("/api/source-health")
    def api_source_health():
        def _ping(source):
            started = time.time()
            try:
                response = source.session.get(source.base_url, timeout=8)
                latency = int((time.time() - started) * 1000)
                if latency < 500:
                    grade = "fast"
                elif latency < 1500:
                    grade = "medium"
                else:
                    grade = "slow"
                return {"source": source.name, "icon": source.icon, "status": "online", "latency_ms": latency, "code": response.status_code, "grade": grade}
            except Exception:
                latency = int((time.time() - started) * 1000)
                return {"source": source.name, "icon": source.icon, "status": "offline", "latency_ms": latency, "code": 0, "grade": "offline"}

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for result in pool.map(_ping, state.sources):
                results.append(result)
        results.sort(key=lambda item: (0 if item["status"] == "online" else 1, item["latency_ms"]))
        return jsonify(results)

    @app.route("/api/speed-test")
    def api_speed_test():
        src_name = request.args.get("source", "")
        manga_url = request.args.get("url", "")
        source = get_source_by_name_or_url(state.sources, src_name, manga_url)
        if not source or not manga_url:
            return jsonify({"error": "bad params"}), 400
        try:
            info = source.get_manga_info(manga_url)
            chapters = source.get_chapters(manga_url, info.get("manga_id"))
            if not chapters:
                return jsonify({"speed_kbs": 0})
            images = source.get_chapter_images(chapters[0]["url"])
            if not images:
                return jsonify({"speed_kbs": 0})
            started = time.time()
            data = source.download_image(images[0])
            elapsed = time.time() - started
            if data and elapsed > 0:
                speed = len(data) / 1024 / elapsed
                return jsonify({"speed_kbs": round(speed, 1), "size_bytes": len(data), "elapsed_ms": int(elapsed * 1000)})
            return jsonify({"speed_kbs": 0})
        except Exception as exc:
            return jsonify({"speed_kbs": 0, "error": str(exc)})

    @app.route("/api/detail")
    def api_detail():
        url = request.args.get("url", "")
        src_name = request.args.get("source", "")
        if not url:
            return jsonify({"error": "no url"}), 400
        source = get_source_by_name_or_url(state.sources, src_name, url)
        try:
            info = source.get_manga_info(url)
            chapters = source.get_chapters(url, info.get("manga_id"))
            return jsonify({"info": info, "chapters": chapters, "source": source.name})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/chapter-images")
    def api_chapter_images():
        url = request.args.get("url", "")
        src_name = request.args.get("source", "")
        if not url:
            return jsonify({"error": "no url"}), 400
        source = get_source_by_name_or_url(state.sources, src_name, url)
        try:
            images = source.get_chapter_images(url)
            if images:
                def _prefetch_chapter_images(img_urls):
                    from concurrent.futures import ThreadPoolExecutor

                    with ThreadPoolExecutor(max_workers=32) as pool:
                        pool.map(lambda img_url: download_cover_to_cache(state, img_url), img_urls)

                threading.Thread(target=_prefetch_chapter_images, args=(images,), daemon=True).start()
            return jsonify({"images": images, "source": source.name})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

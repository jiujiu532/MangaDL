from datetime import datetime

import concurrent.futures
import re

from flask import Response, jsonify, request, stream_with_context

from download_manager import extract_chapter_number

from .utils import chapter_range, get_source_by_name_or_url
from .zip_stream import stream_zip


def register(app, state):
    @app.route("/api/favorites")
    def api_favorites():
        group = request.args.get("group", "")
        if group and group != "All":
            items = state.favorites.get_by_group(group)
        else:
            items = state.favorites.get_all()
        return jsonify({"groups": state.favorites.get_groups(), "items": items})

    @app.route("/api/favorites/add", methods=["POST"])
    def api_fav_add():
        data = request.json or {}
        state.favorites.add(data["title"], data["url"], data.get("cover", ""), data.get("source", ""), data.get("group"))
        return jsonify({"ok": True})

    @app.route("/api/favorites/remove", methods=["POST"])
    def api_fav_remove():
        state.favorites.remove(request.json["url"])
        return jsonify({"ok": True})

    @app.route("/api/favorites/update_group", methods=["POST"])
    def api_fav_group():
        data = request.json or {}
        state.favorites.update_group(data["url"], data["group"])
        return jsonify({"ok": True})

    @app.route("/api/favorites/check")
    def api_fav_check():
        url = request.args.get("url", "")
        return jsonify({"favorited": state.favorites.is_favorited(url)})

    @app.route("/api/favorites/batch-update", methods=["POST"])
    def api_batch_update():
        data = request.json or {}
        urls = data.get("urls", [])
        prefer_raw = data.get("prefer_raw", True)
        state.favorites.backfill_from_download_log()

        if urls:
            targets = [item for item in state.favorites.get_all() if item["url"] in urls]
        else:
            targets = state.favorites.get_updatable()

        if not targets:
            return jsonify({"results": [], "summary": "没有可追更的漫画"})

        def _check_one(item):
            hist = item.get("download_history") or {}
            last_ch = hist.get("last_chapter", "0")
            try:
                last_num = float(last_ch)
            except (ValueError, TypeError):
                last_num = 0

            if prefer_raw == "auto":
                item_version = hist.get("last_version", "raw")
                item_prefer_raw = item_version == "raw"
            else:
                item_prefer_raw = prefer_raw

            source = get_source_by_name_or_url(state.sources, item.get("source", ""))
            if not source or source.name != item.get("source"):
                return {"title": item["title"], "url": item["url"], "source": item.get("source", ""), "status": "error", "message": "源不可用", "new_chapters": []}

            try:
                info = source.get_manga_info(item["url"])
                chapters = source.get_chapters(item["url"], info.get("manga_id"))
            except Exception as exc:
                return {"title": item["title"], "url": item["url"], "source": item.get("source", ""), "status": "error", "message": str(exc), "new_chapters": []}

            new_chs = []
            for chapter in chapters:
                ch_num_str = re.search(r"(\d+(?:\.\d+)?)", chapter.get("title", ""))
                if not ch_num_str:
                    continue
                ch_num = float(ch_num_str.group(1))
                if ch_num <= last_num:
                    continue
                if ch_num_str.group(1) in hist.get("chapters", []):
                    continue
                title_lower = chapter.get("title", "").lower()
                is_raw = "raw" in title_lower
                if prefer_raw != "auto":
                    if item_prefer_raw and not is_raw:
                        continue
                    if not item_prefer_raw and is_raw:
                        continue
                new_chs.append({"title": chapter["title"], "url": chapter["url"], "chapter_num": ch_num_str.group(1)})

            if new_chs:
                return {"title": item["title"], "url": item["url"], "source": item.get("source", ""), "status": "has_updates", "new_chapters": new_chs}
            return {"title": item["title"], "url": item["url"], "source": item.get("source", ""), "status": "up_to_date", "new_chapters": [], "last_chapter": last_ch}

        results = []
        total_new = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_check_one, target): target for target in targets}
            for future in concurrent.futures.as_completed(futures, timeout=30):
                try:
                    result = future.result()
                    results.append(result)
                    total_new += len(result.get("new_chapters", []))
                except Exception:
                    target = futures[future]
                    results.append({"title": target["title"], "url": target["url"], "status": "error", "message": "超时", "new_chapters": []})

        return jsonify({
            "results": results,
            "summary": {
                "total": len(results),
                "has_updates": sum(1 for item in results if item["status"] == "has_updates"),
                "up_to_date": sum(1 for item in results if item["status"] == "up_to_date"),
                "errors": sum(1 for item in results if item["status"] == "error"),
                "new_chapters": total_new,
            },
        })

    @app.route("/api/favorites/start-update", methods=["POST"])
    def api_start_update():
        data = request.json or {}
        items = data.get("items", [])
        if not items:
            return jsonify({"ok": False, "error": "无下载项"})

        state.dl_manager.clear()
        state.dl_manager.chapter_concurrency = state.config["chapter_concurrency"]
        state.dl_manager.image_concurrency = state.config["image_concurrency"]
        state.dl_manager.set_fallback_sources(state.sources)

        total_chs = 0
        for item in items:
            source = get_source_by_name_or_url(state.sources, item.get("source", ""))
            if not source or source.name != item.get("source"):
                continue
            chapters = item.get("chapters", [])
            if chapters:
                state.dl_manager.add_tasks(chapters, item.get("title", "Unknown"), source, state.config["download_dir"])
                total_chs += len(chapters)

        if total_chs == 0:
            return jsonify({"ok": False, "error": "无有效章节"})

        state.clear_logs()
        state.add_log(f"[追更] 开始下载 {len(items)} 部漫画，共 {total_chs} 章")

        chapter_details = []
        for item in items:
            chapters = item.get("chapters", [])
            if not chapters:
                continue
            from_ch, to_ch = chapter_range(chapters, extract_chapter_number)
            chapter_details.append({"title": item.get("title", ""), "from": from_ch, "to": to_ch, "count": len(chapters)})

        state.favorites.add_update_log({
            "manga_count": len(items),
            "chapter_count": total_chs,
            "titles": [item.get("title", "") for item in items],
            "chapter_details": chapter_details,
        })
        for detail in chapter_details:
            state.favorites.add_download_log({
                "manga_title": detail["title"],
                "source": items[0].get("source", "") if items else "",
                "from_chapter": detail["from"],
                "to_chapter": detail["to"],
                "count": detail["count"],
                "type": "update",
            })

        state.dl_manager.start()
        return jsonify({"ok": True, "count": total_chs})

    @app.route("/api/favorites/start-update-zip", methods=["POST"])
    def api_start_update_zip():
        data = request.json or {}
        items = data.get("items", [])
        if not items:
            return jsonify({"error": "无下载项"}), 400

        generate = stream_zip(
            items,
            source_resolver=lambda item: get_source_by_name_or_url(state.sources, item.get("source", "")),
            archive_name_resolver=lambda item: item.get("title", "Unknown"),
        )

        chapter_details = []
        total_chs = 0
        for item in items:
            chapters = item.get("chapters", [])
            if not chapters:
                continue
            total_chs += len(chapters)
            from_ch, to_ch = chapter_range(chapters, extract_chapter_number)
            chapter_details.append({"title": item.get("title", ""), "from": from_ch, "to": to_ch, "count": len(chapters)})

        state.favorites.add_update_log({
            "manga_count": len(items),
            "chapter_count": total_chs,
            "titles": [item.get("title", "") for item in items],
            "chapter_details": chapter_details,
        })
        for detail in chapter_details:
            state.favorites.add_download_log({
                "manga_title": detail["title"],
                "source": items[0].get("source", "") if items else "",
                "from_chapter": detail["from"],
                "to_chapter": detail["to"],
                "count": detail["count"],
                "type": "update",
            })

        for item in items:
            manga_url = item.get("url", "")
            if manga_url:
                for chapter in item.get("chapters", []):
                    ch_title = chapter.get("title", "")
                    ch_num = extract_chapter_number(ch_title)
                    if ch_num:
                        is_raw = "raw" in ch_title.lower()
                        state.favorites.update_download_history(manga_url, ch_num, is_raw=is_raw)

        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_filename = __import__("urllib.parse", fromlist=["quote"]).quote(f"追更_{date_str}.zip")
        return Response(
            stream_with_context(generate()),
            mimetype="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    @app.route("/api/favorites/scan-history", methods=["POST"])
    def api_scan_history():
        count = state.favorites.scan_download_dir(state.config["download_dir"])
        return jsonify({"ok": True, "backfilled": count})

    @app.route("/api/favorites/check-new")
    def api_check_new():
        updatable = state.favorites.get_updatable()
        if not updatable:
            return jsonify({"count": 0})

        def _quick_check(item):
            hist = item.get("download_history") or {}
            try:
                last_num = float(hist.get("last_chapter", "0"))
            except Exception:
                return False
            source = get_source_by_name_or_url(state.sources, item.get("source", ""))
            if not source or source.name != item.get("source"):
                return False
            try:
                info = source.get_manga_info(item["url"])
                chapters = source.get_chapters(item["url"], info.get("manga_id"))
                for chapter in chapters:
                    match = re.search(r"(\d+(?:\.\d+)?)", chapter.get("title", ""))
                    if match and float(match.group(1)) > last_num:
                        return True
            except Exception:
                pass
            return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            count = sum(pool.map(_quick_check, updatable))
        return jsonify({"count": count})

    @app.route("/api/favorites/update-log")
    def api_update_log():
        return jsonify(state.favorites.get_update_log())

from flask import Response, jsonify, request, stream_with_context

from download_manager import TaskStatus, extract_chapter_number

from .utils import chapter_range, get_source_by_name_or_url, safe_filename
from .zip_stream import stream_zip


def register(app, state):
    @app.route("/api/download", methods=["POST"])
    def api_download():
        data = request.json or {}
        chapters = data.get("chapters", [])
        manga_title = data.get("title", "Unknown")
        src_name = data.get("source", "")
        source = get_source_by_name_or_url(state.sources, src_name)

        state.dl_manager.clear()
        state.dl_manager.chapter_concurrency = state.config["chapter_concurrency"]
        state.dl_manager.image_concurrency = state.config["image_concurrency"]
        state.dl_manager.set_fallback_sources(state.sources)
        state.dl_manager.add_tasks(chapters, manga_title, source, state.config["download_dir"])

        state.clear_logs()
        state.add_log(f"[START] {manga_title} - {len(chapters)} chapters")
        state.dl_manager.start()

        from_ch, to_ch = chapter_range(chapters, extract_chapter_number)
        state.favorites.add_download_log({
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
        for task in state.dl_manager.tasks:
            tasks.append({
                "title": task.chapter_title,
                "status": task.status.value,
                "progress": task.progress,
                "total": task.total,
                "speed": round(task.speed, 1),
            })
        done = sum(
            1
            for task in state.dl_manager.tasks
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        )
        return jsonify({"tasks": tasks, "done": done, "total": len(state.dl_manager.tasks)})

    @app.route("/api/download/pause/<int:idx>", methods=["POST"])
    def api_pause(idx):
        state.dl_manager.pause_task(idx)
        return jsonify({"ok": True})

    @app.route("/api/download/resume/<int:idx>", methods=["POST"])
    def api_resume(idx):
        state.dl_manager.resume_task(idx)
        return jsonify({"ok": True})

    @app.route("/api/download/cancel/<int:idx>", methods=["POST"])
    def api_cancel(idx):
        state.dl_manager.cancel_task(idx)
        return jsonify({"ok": True})

    @app.route("/api/download/cancel_all", methods=["POST"])
    def api_cancel_all():
        state.dl_manager.stop_all()
        return jsonify({"ok": True})

    @app.route("/api/download/zip", methods=["POST"])
    def api_download_zip():
        data = request.json or {}
        chapters = data.get("chapters", [])
        manga_title = data.get("title", "Unknown")
        src_name = data.get("source", "")
        manga_url = data.get("manga_url", "")
        if not chapters:
            return jsonify({"error": "no chapters"}), 400

        chapter_groups = [{"title": manga_title, "source": src_name, "chapters": chapters}]
        generate = stream_zip(
            chapter_groups,
            source_resolver=lambda group: get_source_by_name_or_url(state.sources, group.get("source", "")),
            archive_name_resolver=lambda group: group.get("title", "Unknown"),
        )

        from_ch, to_ch = chapter_range(chapters, extract_chapter_number)
        state.favorites.add_download_log({
            "manga_title": manga_title,
            "source": src_name,
            "from_chapter": from_ch,
            "to_chapter": to_ch,
            "count": len(chapters),
            "type": "manual",
        })
        if manga_url:
            for chapter in chapters:
                ch_title = chapter.get("title", "")
                ch_num = extract_chapter_number(ch_title)
                if ch_num:
                    is_raw = "raw" in ch_title.lower()
                    state.favorites.update_download_history(manga_url, ch_num, is_raw=is_raw)

        safe_name = safe_filename(manga_title, ".zip")
        quoted = __import__("urllib.parse", fromlist=["quote"]).quote(safe_name)
        return Response(
            stream_with_context(generate()),
            mimetype="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    @app.route("/api/download/logs")
    def api_logs():
        with state.log_lock:
            return jsonify(state.log_buffer[:])

    @app.route("/api/download/history")
    def api_download_history():
        return jsonify(state.favorites.get_download_log())

    @app.route("/api/download/history/clear", methods=["POST"])
    def api_download_history_clear():
        state.favorites.clear_download_log()
        return jsonify({"ok": True})

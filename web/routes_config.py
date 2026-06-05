import concurrent.futures
import time

from flask import jsonify, request

from .utils import build_stats


def register(app, state):
    @app.route("/api/config")
    def api_config():
        return jsonify({
            "download_dir": state.config["download_dir"],
            "chapter_concurrency": state.config["chapter_concurrency"],
            "image_concurrency": state.config["image_concurrency"],
            "proxy_mode": state.config["proxy_mode"],
            "proxy_host": state.config["proxy_host"],
            "proxy_port": state.config["proxy_port"],
            "theme": state.config.get("theme", "dark"),
            "search_history": state.config.get_search_history(),
        })

    @app.route("/api/config", methods=["POST"])
    def api_config_save():
        data = request.json or {}
        for key in ["download_dir", "chapter_concurrency", "image_concurrency", "proxy_mode", "proxy_host", "proxy_port", "theme"]:
            if key in data:
                state.config[key] = data[key]
        state.config.save()
        proxies = state.config.get_proxy_dict()
        for source in state.sources:
            source.session.proxies = proxies or {}
        return jsonify({"ok": True})

    @app.route("/api/health")
    def api_health():
        def _check(source):
            try:
                started = time.time()
                import requests as req

                response = req.get(source.base_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                return source.name, response.status_code < 400, int((time.time() - started) * 1000)
            except Exception:
                return source.name, False, -1

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for name, ok, ms in pool.map(_check, state.sources):
                results[name] = {"ok": ok, "ms": ms}
        return jsonify(results)

    @app.route("/api/stats")
    def api_stats():
        return jsonify(build_stats(state.config["download_dir"], len(state.favorites.get_all())))

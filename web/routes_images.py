from flask import Response, jsonify, request

from .image_cache import download_cover_to_cache, start_batch_prefetch


def register(app, state):
    @app.route("/api/img-prefetch", methods=["POST"])
    def api_img_prefetch():
        data = request.json or {}
        urls = data.get("urls", [])
        if not urls:
            return jsonify({"status": "empty"})
        status, count = start_batch_prefetch(state, urls)
        if status == "all_cached":
            return jsonify({"status": status})
        return jsonify({"status": status, "count": count})

    @app.route("/api/img-proxy")
    def api_img_proxy():
        url = request.args.get("url", "")
        if not url:
            return Response("Missing url", status=400)

        now = __import__("time").time()
        with state.img_cache_lock:
            if url in state.img_cache:
                data, ct, ts = state.img_cache[url]
                if now - ts < state.img_cache_ttl:
                    return Response(data, mimetype=ct or "image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

        with state.img_downloading_lock:
            evt = state.img_downloading.get(url)
        if evt:
            evt.wait(timeout=12)
            with state.img_cache_lock:
                if url in state.img_cache:
                    data, ct, _ = state.img_cache[url]
                    return Response(data, mimetype=ct, headers={"Cache-Control": "public, max-age=3600"})

        if download_cover_to_cache(state, url):
            with state.img_cache_lock:
                data, ct, _ = state.img_cache[url]
            return Response(data, mimetype=ct, headers={"Cache-Control": "public, max-age=3600"})
        return Response("Failed to fetch image", status=502)

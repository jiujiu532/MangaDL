from flask import Flask

from .image_cache import prefetch_covers
from .listing_cache import fetch_listing
from .routes_config import register as register_config_routes
from .routes_download import register as register_download_routes
from .routes_favorites import register as register_favorites_routes
from .routes_images import register as register_image_routes
from .routes_pages import register as register_page_routes
from .routes_sources import register as register_source_routes
from .state import WebState


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    state = WebState()
    app.extensions["web_state"] = state

    register_page_routes(app, state)
    register_source_routes(app, state)
    register_image_routes(app, state)
    register_download_routes(app, state)
    register_favorites_routes(app, state)
    register_config_routes(app, state)

    state.preload_listings(lambda method_name, src_name="", page=1: fetch_listing(state, lambda items: prefetch_covers(state, items), method_name, src_name, page))
    return app


app = create_app()

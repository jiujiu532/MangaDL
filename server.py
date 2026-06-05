"""
漫画下载器 Web Server — Flask 兼容入口
实际实现已拆分到 web/ 目录。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web import app, create_app

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    import webbrowser

    port = 5000
    print(f"Starting server at http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)

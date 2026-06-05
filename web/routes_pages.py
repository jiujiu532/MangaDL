from flask import render_template


def register(app, state):
    @app.route("/")
    def index():
        return render_template("index.html")

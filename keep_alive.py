
from flask import Flask
from threading import Thread
import os

app = Flask("")


@app.route("/")
def home():
    return "I'm alive"


def run():
    # Render 會提供 PORT 環境變數，本機沒有就用 8080
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run)
    t.start()
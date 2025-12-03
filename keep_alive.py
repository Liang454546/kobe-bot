# keep_alive.py ─ 2025 終極不死版（支援所有平台）
import os
import logging
from flask import Flask
from threading import Thread
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KeepAlive")

app = Flask(__name__)

@app.route('/')
def home():
    return (
        "<h1>Kobe Bot 還活著！</h1>"
        "<p>曼巴精神永不熄滅。</p>"
        "<pre>   Mamba Out.</pre>"
    ), 200

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "Kobe Bot"}, 200

# 關鍵：加上 uptime 檢查（某些平台只 ping / 就認為活著）
@app.route('/uptime')
def uptime():
    return {"uptime": time.time() - START_TIME}, 200

# 全域記錄啟動時間（給監控用）
START_TIME = time.time()

def run_flask():
    port = int(os.environ.get("PORT", 8080))  # 2025 主流平台預設 8080
    logger.info(f"Keep-Alive 伺服器啟動於 port {port}")
    
    # 超重要：使用 threaded + 低延遲設定
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,   # 防止雙重啟動
        threaded=True         # 支援多 concurrent requests
    )

def keep_alive():
    """啟動一個永不中斷的背景 Flask 伺服器"""
    t = Thread(target=run_flask, daemon=True)
    t.start()
    logger.info("Keep-Alive 已啟動 ─ Kobe Bot 永不睡眠！")

# 可選：加上自動 ping 自己（對抗某些平台的冷啟動）
def auto_ping():
    import requests
    url = os.getenv("REPL_URL") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    url = url.rstrip("/")
    
    def ping():
        while True:
            try:
                requests.get(f"{url}/health", timeout=10)
                logger.debug("Auto-ping 成功")
            except:
                logger.warning("Auto-ping 失敗")
            time.sleep(60)  # 每分鐘 ping 一次
    
    if url:
        t = Thread(target=ping, daemon=True)
        t.start()
        logger.info(f"Auto-Ping 已啟動：{url}")

# 使用方式（main.py 最後面）：
# if __name__ == "__main__":
#     keep_alive()
#     auto_ping()  # 可選：超級保險
#     bot.run(os.getenv("TOKEN"))

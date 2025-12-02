import runpy

if __name__ == "__main__":
    # 執行現有的 kobe_bot.py 作為主程式，讓部署平台仍可呼叫 `python main.py`
    runpy.run_path("kobe_bot.py", run_name="__main__")
import asyncio
import os
from pathlib import Path
import discord
from discord.ext import commands
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f'{bot.user} 上線，已載入 {len(bot.cogs)} 個模組。')


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.content.lower() == "kobe":
        await message.channel.send("Man! What can I say?")
    await bot.process_commands(message)


async def _load_extension(ext: str) -> None:
    try:
        res = bot.load_extension(ext)
        # `load_extension` may return a coroutine in some discord.py versions
        if asyncio.iscoroutine(res):
            await res
        print(f"載入擴充: {ext}")
    except Exception as e:
        print(f"載入擴充失敗 {ext}: {e}")


async def load_cogs():
    base = Path(__file__).parent / "cogs"
    if not base.exists():
        print("找不到 cogs 資料夾，跳過載入。")
        return
    for p in base.glob("*.py"):
        if p.stem == "__init__":
            continue
        await _load_extension(f"cogs.{p.stem}")


async def main():
    # 啟動 keep-alive 服務（若需要）
    try:
        keep_alive()
    except Exception as e:
        print(f"啟動 keep_alive 失敗: {e}")

    # 載入 cogs
    await load_cogs()

    # 讀取 Token，並檢查是否為空
    token = os.getenv("TOKEN")
    if not token:
        print("環境變數 TOKEN 未設定或為空，Bot 無法啟動。請檢查部署平台的設定。")
        return

    try:
        await bot.start(token)
    except Exception as e:
        print(f"Bot 啟動失敗: {e}")


if __name__ == "__main__":
    asyncio.run(main())
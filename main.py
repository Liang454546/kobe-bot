import discord
from discord.ext import commands
import os
import asyncio
import logging
from dotenv import load_dotenv
from keep_alive import keep_alive, auto_ping
import google.generativeai as genai

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.presences = True 

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ==========================================
# 🧠 中央 AI 大腦 (輕量穩定版)
# ==========================================
bot.ai_model = None

async def init_ai():
    if not GEMINI_KEY:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY")
        return

    try:
        genai.configure(api_key=GEMINI_KEY)
        # 🔥 直接鎖定最穩定的 flash 模型，不進行迴圈測試，節省額度
        bot.ai_model = genai.GenerativeModel("gemini-1.5-flash")
        
        # 輕量測試 (Ping 一下就好)
        try:
            await asyncio.to_thread(bot.ai_model.generate_content, "Hi")
            logger.info("✅ AI 啟動成功 (Gemini 1.5 Flash)")
        except Exception as e:
            if "429" in str(e):
                logger.warning("⚠️ AI 額度暫時額滿 (Rate Limit)，請稍等 1 分鐘後再試。")
            else:
                logger.error(f"❌ AI 連線測試失敗: {e}")

    except Exception as e:
        logger.error(f"❌ AI 初始化錯誤: {e}")

async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: return "⚠️ AI 冷卻中或未啟動"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。繁體中文。"
        contents = []
        
        if history:
            if not history:
                contents.append({"role": "user", "parts": [base_prompt]})
                contents.append({"role": "model", "parts": ["收到。"]})
            else:
                contents.extend(history)
            user_parts = [prompt]
            if image: user_parts.append(image)
            contents.append({"role": "user", "parts": user_parts})
        else:
            parts = [base_prompt, f"情境/用戶輸入：{prompt}"]
            if image: parts.append(image)
            contents = parts

        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()

    except Exception as e:
        if "429" in str(e):
            return "⚠️ 思緒混亂 (API 額度滿了，請休息一下)"
        logger.error(f"AI 生成錯誤: {e}")
        return "⚠️ 發生錯誤"

bot.ask_brain = ask_brain

# ==========================================

@bot.event
async def on_ready():
    await init_ai()
    await load_cogs()
    print(f"【{bot.user} 已上線】曼巴時刻啟動！")

async def load_cogs():
    if os.path.exists("./cogs"):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f"cogs.{filename[:-3]}")
                    logger.info(f"✅ 載入模組: {filename}")
                except Exception as e:
                    logger.error(f"❌ 無法載入 {filename}: {e}")

async def main():
    if not TOKEN:
        logger.error("錯誤：找不到 TOKEN")
        return
    async with bot:
        keep_alive()
        auto_ping()
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

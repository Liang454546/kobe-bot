import discord
import os
import asyncio
import logging
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive, auto_ping
import google.generativeai as genai

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# 設定 Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 設定權限
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.presences = True 

# 關閉預設 Help
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ==========================================
# 🧠 中央 AI 大腦初始化
# ==========================================
bot.ai_model = None
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        # 這裡統一設定全機器人使用的模型
        bot.ai_model = genai.GenerativeModel("gemini-2.0-flash")
        logger.info("✅ 中央 AI 大腦 (Gemini 2.0 Flash) 啟動成功")
    except Exception as e:
        logger.error(f"❌ 中央 AI 啟動失敗: {e}")

# 通用 AI 呼叫函式 (所有 Cog 都用這個)
async def ask_brain(prompt, image=None, system_instruction=None):
    if not bot.ai_model: return None
    try:
        # 預設人設
        base_prompt = "你是 Kobe Bryant。語氣毒舌、嚴格、曼巴精神。繁體中文(台灣)。"
        if system_instruction:
            base_prompt = system_instruction
            
        contents = [base_prompt, prompt]
        if image: contents.append(image)
        
        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()
    except Exception as e:
        logger.error(f"AI 生成錯誤: {e}")
        return None

# 將函式掛載到 bot 上，讓 Cogs 可以呼叫 self.bot.ask_brain(...)
bot.ask_brain = ask_brain

# ==========================================

@bot.event
async def on_ready():
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
        logger.error("錯誤：找不到 TOKEN，請檢查環境變數！")
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

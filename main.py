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
# 🧠 中央 AI 大腦 (支援記憶版)
# ==========================================
bot.ai_model = None

async def init_ai():
    if GEMINI_KEY:
        try:
            genai.configure(api_key=GEMINI_KEY)
            bot.ai_model = genai.GenerativeModel("gemini-2.0-flash")
            logger.info("✅ 中央 AI 大腦 (Gemini 2.0 Flash) 啟動成功")
        except Exception as e:
            logger.error(f"❌ 中央 AI 啟動失敗: {e}")
    else:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY")

# 通用 AI 呼叫函式
async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: return None
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。語氣毒舌、嚴格。繁體中文(台灣)。"
        
        # 記憶模式：組合歷史訊息
        if history:
            # 結構：[系統人設] + [過去對話] + [當前問題]
            contents = [{"role": "user", "parts": [base_prompt + "\n(請保持這個人設回答接下來的對話)"]}] 
            contents.append({"role": "model", "parts": ["收到。Mamba Mentality."]}) # 假回應以確立人設
            contents.extend(history) # 加入過去對話
            contents.append({"role": "user", "parts": [prompt]}) # 加入這一次的問題
        
        # 單次模式 (無記憶或有圖片)
        else:
            contents = [base_prompt, f"用戶輸入：{prompt}"]
            if image: contents.append(image)
        
        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()
    except Exception as e:
        logger.error(f"AI 生成錯誤: {e}")
        return None

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

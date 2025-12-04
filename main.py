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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.presences = True 

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ==========================================
# 🧠 中央 AI 大腦
# ==========================================
bot.ai_model = None

async def init_ai():
    if not GEMINI_KEY:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY")
        return

    try:
        genai.configure(api_key=GEMINI_KEY)
        
        # 🔥 這裡使用目前 Google 提供「免費且最穩定」的模型
        # 如果您的 debug_ai.py 顯示其他名稱，請修改這裡
        model_name = "gemini-1.5-flash" 
        
        bot.ai_model = genai.GenerativeModel(model_name)
        
        # 開機測試
        await asyncio.to_thread(bot.ai_model.generate_content, "Hi")
        logger.info(f"✅ AI 啟動成功！使用模型: {model_name}")

    except Exception as e:
        logger.error(f"❌ AI 初始化失敗: {e}")
        logger.error("💡 請檢查 API Key 是否正確，或使用 debug_ai.py 檢查可用模型。")

async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: return "⚠️ AI 系統離線中 (請檢查後台)"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。繁體中文。"
        contents = []
        
        if history:
            if not history:
                contents.append({"role": "user", "parts": [base_prompt]})
                contents.append({"role": "model", "parts": ["收到。"]})
            else:
                contents.extend(history)
            
            user_msg = {"role": "user", "parts": [prompt]}
            if image: user_msg["parts"].append(image)
            contents.append(user_msg)
        else:
            parts = [base_prompt, f"用戶輸入：{prompt}"]
            if image: parts.append(image)
            contents = parts

        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()

    except Exception as e:
        logger.error(f"AI 生成錯誤: {e}")
        return "⚠️ AI 連線錯誤 (404/429)，請稍後再試。"

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

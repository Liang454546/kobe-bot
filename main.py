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
# 🧠 中央 AI 大腦 (自動修復版)
# ==========================================
bot.ai_model = None

MODEL_CANDIDATES = [
    "gemini-2.5-flash", 
    "gemini-2.0-flash-exp", 
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro"
]

async def init_ai():
    if not GEMINI_KEY:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY，AI 功能將無法使用")
        return

    try:
        genai.configure(api_key=GEMINI_KEY)
        logger.info("🔄 正在初始化 AI 大腦...")
        
        for model_name in MODEL_CANDIDATES:
            try:
                model = genai.GenerativeModel(model_name)
                # 🔥 使用更明確的測試語句，避免被 Safety Filter 擋下
                logger.info(f"🧪 測試模型連線: {model_name}...")
                response = await asyncio.to_thread(model.generate_content, "Hello, system check.")
                
                if response and response.text:
                    bot.ai_model = model
                    logger.info(f"✅ AI 啟動成功！已鎖定使用模型: {model_name}")
                    return 
            except Exception as e:
                # 忽略 404/429/Safety 等錯誤，繼續試下一個
                logger.warning(f"⚠️ 模型 {model_name} 測試失敗: {e}")
                continue 

        logger.error("🚫 所有模型測試皆失敗！請檢查您的 API Key 是否正確。")

    except Exception as e:
        logger.error(f"❌ AI 初始化嚴重錯誤: {e}")

async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: return "⚠️ AI 系統離線中"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。語氣毒舌、嚴格。繁體中文(台灣)。"
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

        # 加入 try-except 避免生成失敗導致崩潰
        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        
        # 檢查是否有內容被阻擋 (Safety)
        if not response.text:
            return "⚠️ 內容被 AI 安全系統阻擋 (Safety Block)"
            
        return response.text.strip()

    except Exception as e:
        if "429" in str(e):
            return "⚠️ 思緒混亂 (API 額度滿了，請休息一下)"
        logger.error(f"AI 生成錯誤: {e}")
        return "⚠️ 發生錯誤，請稍後再試。"

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



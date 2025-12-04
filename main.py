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
# 🧠 中央 AI 大腦 (2025 最新版)
# ==========================================
bot.ai_model = None

# 備選模型清單 (優先順序：由新到舊)
# Bot 會依序測試，直到找到一個您的 Key 能用的
MODEL_CANDIDATES = [
    "gemini-2.5-flash",        # 🔥 2025 首選：高效、多模態、1M Context
    "gemini-2.0-flash-exp",    # 次選：實驗版
    "gemini-1.5-flash",        # 保底：最穩定舊版
    "gemini-1.5-pro",
    "gemini-pro"
]

async def init_ai():
    if not GEMINI_KEY:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY，AI 功能將無法使用")
        return

    try:
        genai.configure(api_key=GEMINI_KEY)
        
        # 🔥 自動測試模型
        logger.info("🔄 正在初始化 AI 大腦...")
        for model_name in MODEL_CANDIDATES:
            try:
                # 建立模型物件
                model = genai.GenerativeModel(model_name)
                # 嘗試生成一個極短的測試請求
                logger.info(f"🧪 測試模型連線: {model_name}...")
                response = await asyncio.to_thread(model.generate_content, "Hi")
                
                if response:
                    bot.ai_model = model
                    logger.info(f"✅ AI 啟動成功！已鎖定使用模型: {model_name}")
                    return # 成功就離開，不再測試後面的
            except Exception as e:
                # 404 代表該 Key 無權限存取此模型，繼續試下一個
                if "404" in str(e):
                    logger.warning(f"⚠️ 模型 {model_name} 權限不足或未開放 (404)，嘗試下一個...")
                elif "429" in str(e):
                    logger.warning(f"⚠️ 模型 {model_name} 額度暫時額滿 (429)，嘗試下一個...")
                else:
                    logger.warning(f"❌ 模型 {model_name} 測試失敗: {e}")
                continue 

        logger.error("🚫 所有模型測試皆失敗！請檢查您的 API Key 是否正確，或是否來自 Google AI Studio。")

    except Exception as e:
        logger.error(f"❌ AI 初始化嚴重錯誤: {e}")

# 通用 AI 呼叫函式
async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: 
        return "⚠️ AI 系統離線中 (請檢查 API Key)"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。語氣毒舌、嚴格。繁體中文(台灣)。"
        contents = []
        
        # 記憶模式
        if history:
            if not history:
                contents.append({"role": "user", "parts": [base_prompt]})
                contents.append({"role": "model", "parts": ["收到。"]})
            else:
                contents.extend(history)
            
            user_parts = [prompt]
            if image: user_parts.append(image)
            contents.append({"role": "user", "parts": user_parts})
            
        # 單次模式
        else:
            parts = [base_prompt, f"情境/用戶輸入：{prompt}"]
            if image: parts.append(image)
            contents = parts

        # 呼叫 API
        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()

    except Exception as e:
        if "429" in str(e):
            return "⚠️ 思緒混亂 (API 額度滿了，請休息一下)"
        logger.error(f"AI 生成錯誤: {e}")
        return "⚠️ AI 連線錯誤，請稍後再試。"

# 掛載函式
bot.ask_brain = ask_brain

# ==========================================

@bot.event
async def on_ready():
    await init_ai() # 啟動並測試 AI
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

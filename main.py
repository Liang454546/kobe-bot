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

# 設定 Log 顯示等級，方便除錯
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 設定權限
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.presences = True 

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ==========================================
# 🧠 中央 AI 大腦 (使用穩定版模型)
# ==========================================
bot.ai_model = None

async def init_ai():
    if GEMINI_KEY:
        try:
            genai.configure(api_key=GEMINI_KEY)
            # 🔥 修改：使用 gemini-1.5-flash (最穩定)
            bot.ai_model = genai.GenerativeModel("gemini-1.5-flash")
            logger.info("✅ 中央 AI 大腦 (Gemini 1.5 Flash) 啟動成功")
        except Exception as e:
            logger.error(f"❌ 中央 AI 啟動失敗: {e}")
    else:
        logger.warning("⚠️ 找不到 GEMINI_API_KEY，AI 功能將無法使用")

# 通用 AI 呼叫函式
async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: 
        return "⚠️ AI 尚未啟動，請檢查 API Key。"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。語氣毒舌、嚴格。繁體中文(台灣)。"
        
        contents = []
        
        # 記憶模式
        if history:
            # 為了避免格式錯誤，我們將 system prompt 放在第一則 user message
            if not history:
                contents.append({"role": "user", "parts": [base_prompt]})
                contents.append({"role": "model", "parts": ["收到。"]})
            else:
                contents.extend(history)
            
            # 加入當前訊息
            user_parts = [prompt]
            if image: user_parts.append(image)
            contents.append({"role": "user", "parts": user_parts})
            
        # 單次模式
        else:
            parts = [base_prompt, f"情境/用戶輸入：{prompt}"]
            if image: parts.append(image)
            contents = parts # 單次模式直接傳 list

        # 呼叫 API
        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()

    except Exception as e:
        logger.error(f"AI 生成錯誤: {e}")
        return "⚠️ AI 連線錯誤 (請檢查後台 Log)"

# 掛載函式
bot.ask_brain = ask_brain

# ==========================================

@bot.event
async def on_ready():
    await init_ai() # 啟動 AI
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

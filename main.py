import discord
import os
import asyncio
import logging
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive, auto_ping  # 若無，移除這行
import google.generativeai as genai
from PIL import Image  # 為測試加

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.presences = True  # 注意：需伺服器權限

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
        
        # 🔥 2025 年穩定模型：支援多模態，避免 1.5-flash 404
        model_name = "gemini-2.5-flash"
        
        bot.ai_model = genai.GenerativeModel(
            model_name,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                max_output_tokens=100,  # 限 100 token
                temperature=0.7  # 適合 roast 的創意
            )
        )
        
        # 開機測試：文字 + 圖片多模態
        await asyncio.to_thread(bot.ai_model.generate_content, "Hi")
        test_image = Image.new('RGB', (100, 100), color='red')
        response = await asyncio.to_thread(bot.ai_model.generate_content, ["描述這張圖", test_image])
        if not response.text:
            raise ValueError("模型不支援多模態")
        logger.info(f"✅ AI 啟動成功！使用模型: {model_name}")

    except Exception as e:
        logger.error(f"❌ AI 初始化失敗: {e}")
        logger.error("💡 請檢查 API Key 或使用 debug_ai.py 檢查可用模型。")
        # 列出可用模型
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            logger.info(f"可用模型: {models[:3]}...")
        except:
            pass

async def ask_brain(prompt, image=None, system_instruction=None, history=None):
    if not bot.ai_model: return "⚠️ AI 系統離線中 (請檢查後台)"
    
    try:
        base_prompt = system_instruction or "你是 Kobe Bryant。繁體中文。"
        contents = []
        
        # 統一處理歷史（限 20 項目，避免 token 溢）
        if history:
            trimmed_history = history[-20:] if len(history) > 20 else history
            contents.extend(trimmed_history)
        
        # 初始系統提示
        if not contents:
            contents.append({"role": "user", "parts": [base_prompt]})
            contents.append({"role": "model", "parts": ["收到。"]})
        
        # 新用戶訊息
        user_parts = [f"用戶輸入：{prompt}"]
        if image:
            # 手動轉 Base64（備案，若 SDK 自動失效）
            import base64
            import io
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            user_parts.append({
                'inline_data': {'mime_type': 'image/jpeg', 'data': img_str}
            })
        contents.append({"role": "user", "parts": user_parts})

        response = await asyncio.to_thread(bot.ai_model.generate_content, contents=contents)
        return response.text.strip()

    except Exception as e:
        logger.error(f"AI 生成錯誤: {e}")
        if "404" in str(e): return "⚠️ 模型更新中，請重啟 bot。"
        if "429" in str(e): return "⚠️ AI 額度滿了 (Rate Limit)，請稍候。"
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
    keep_alive()  # 若無，移除
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

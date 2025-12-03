import discord
from discord.ext import commands, tasks
import random
import asyncio
import time
import aiosqlite
import os
import google.generativeai as genai
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
        self.voice_sessions = {}
        
        # 回嗆清單（不變）
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走！但記住：那些殺不死你的，只會讓你更強。🖕😤",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！Mamba Out. 🏀👎",
            "這就是你的態度？難怪你還在打低端局！Soft. 🥚💀",
            "我走不是因為我怕，是因為我不屑！別吵我，正在訓練。😤👋"
        ]

        self.not_in_voice_roasts = [
            "我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？3 人小隊，去看醫生吧！🏥💊",
            "眼睛不需要可以捐給有需要的人！👀 我哪裡在語音裡了？小隊別浪費時間。",
            "你是在跟鬼說話嗎？👻 這裡只有文字，清醒點！曼巴需要專注。",
            "你的曼巴精神是用來幻想的嗎？🏀 我人都不在，你叫誰滾？軟蛋！"
        ]
        
        # AI 設定（修：換 2025 穩定模型）
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                # 修：改 gemini-2.5-flash (2025 穩定，無 404，vision OK)
                self.model = genai.GenerativeModel("gemini-2.5-flash")
                logger.info("✅ Voice AI: Gemini 2.5 Flash 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
        else:
            logger.warning("GEMINI_API_KEY 缺失，AI 備用")

        self.voice_check.start()

    # AI Kobe 生成（加 retry 防 404）
    async def ask_kobe(self, prompt, cooldown_time=0):
        if not self.model: return random.choice(self.aggressive_leave_msgs)  # 備用
        for attempt in range(3):
            try:
                sys_prompt = "你是 Kobe Bryant，在 3 人小 Discord 語音室當教練。語氣毒舌嚴格勵志，繁體中文(台灣)，簡短(30字內)，多 emoji (🏀🐍)。"
                contents = [sys_prompt, prompt]
                response = await asyncio.to_thread(self.model.generate_content, contents=contents)
                return response.text
            except Exception as e:
                logger.error(f"AI 生成失敗 (嘗試 {attempt+1}): {e}")
                if "404" in str(e):
                    logger.error("模型 404？確認 gemini-2.5-flash 可用，或換 gemini-3-pro-preview。")
                    return None
                await asyncio.sleep(1)
        return None

    # ... (其他函式如 on_voice_state_update, on_message, voice_check 等，不變，借之前版)
    # (進場/離開/靜音邏輯全保留，語音連線已成功)

async def setup(bot):
    await bot.add_cog(Voice(bot))

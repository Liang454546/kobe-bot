# Voice.py ─ 曼巴語音監獄長（2025 最終版）
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
        self.voice_sessions = {}  # {user_id: join_time}
        
        # 超兇回嗆庫
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走！但記住：那些殺不死你的，只會讓你更強。",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！Mamba Out.",
            "這就是你的態度？難怪你還在打低端局！Soft.",
            "我走不是因為我怕，是因為我不屑！別吵我，正在訓練。"
        ]
        self.not_in_voice_roasts = [
            "我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？3人小隊，去看醫生吧！",
            "眼睛不需要可以捐給有需要的人！ 我哪裡在語音裡了？",
            "你是在跟鬼說話嗎？ 這裡只有文字，清醒點！",
            "你的曼巴精神是用來幻想的嗎？ 我人都不在，你叫誰滾？軟蛋！"
        ]

        # === 2025 正確 Gemini 初始化 ===
        self.model = None
        self.has_ai = False
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel(
                    "gemini-1.5-flash",  # 唯一永不 404 的神
                    generation_config={
                        "temperature": 1.0,
                        "max_output_tokens": 60
                    }
                )
                self.has_ai = True
                logger.info("Voice Cog - Gemini 1.5 Flash 啟動成功")
            except Exception as e:
                logger.error(f"Voice AI 初始化失敗: {e}")
                self.has_ai = False
        else:
            logger.warning("無 GEMINI_API_KEY，語音回嗆用固定語錄")

        # 冷卻（防止被刷爆）
        self.kick_cooldown = {}  # user_id -> timestamp

        self.voice_check.start()

    def cog_unload(self):
        self.voice_check.cancel()

    # ========================================
    # 真正 async 的 Kobe AI（再也不卡了！）
    # ========================================
    async def ask_kobe(self, prompt: str) -> str:
        if not self.has_ai:
            return random.choice(self.aggressive_leave_msgs)

        full_prompt = (
            "你是 Kobe Bryant，在一個 3 人小 Discord 語音室當超兇教練。\n"
            "語氣極度毒舌但勵志，用繁體中文（台灣腔），30 字內，多 emoji \n"
            f"情境：{prompt}"
        )

        for _ in range(2):  # retry 一次就夠了
            try:
                response = await self.model.generate_content_async(full_prompt)
                text = response.text.strip()
                return text if text else "Mamba 不廢話！"
            except Exception as e:
                logger.error(f"Voice AI 失敗: {e}")
                if "quota" in str(e).lower() or "429" in str(e):
                    return "冷卻中...你太軟了！"
                await asyncio.sleep(1)

        return random.choice(self.aggressive_leave_msgs)

    # ========================================
    # 關鍵指令：叫 Kobe 滾
    # ========================================
    @commands.command(name="滾", aliases=["kickkobe", "kobe滾", "滾啦"])
    async def kick_kobe(self, ctx):
        now = time.time()
        if now - self.kick_cooldown.get(ctx.author.id, 0) < 30:
            await ctx.send("冷卻中！你以為曼巴是呼之即來揮之即去？😤")
            return
        self.kick_cooldown[ctx.author.id] = now

        voice_client = ctx.guild.voice_client
        
        if not voice_client:
            msg = random.choice(self.not_in_voice_roasts)
            await ctx.send(f"{ctx.author.mention} {msg}")
            return

        # 用 AI 生成超兇回嗆
        ai_reply = await self.ask_kobe(f"{ctx.author.display_name} 在語音叫我滾，超兇回他")
        final_msg = ai_reply or random.choice(self.aggressive_leave_msgs)
        
        await ctx.send(f"||{ctx.author.mention}|| {final_msg}")
        
        # 真正離開語音
        await voice_client.disconnect()

    # ========================================
    # 自動進語音（有人進就跟進）
    # ========================================
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # 有人進語音頻道
        if after.channel and not before.channel:
            if member.guild.voice_client:
                return  # 已經在某個頻道了

            voice_channel = after.channel
            try:
                vc = await voice_channel.connect()
                await asyncio.sleep(1)
                await vc.disconnect()  # 閃現一下就跑（經典曼巴式進場）
                await asyncio.sleep(2)
                vc = await voice_channel.connect()
                
                # 進場語音（可選：播音檔）
                # if vc.is_connected():
                #     vc.play(discord.FFmpegPCMAudio("mamba.mp3"))
                    
            except Exception as e:
                logger.error(f"語音連接失敗: {e}")

    # ========================================
    # 每 30 秒檢查語音狀態（可擴充結算時長）
    # ========================================
    @tasks.loop(seconds=30)
    async def voice_check(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if not vc or not vc.channel:
                continue
                
            members = [m for m in vc.channel.members if not m.bot]
            if len(members) == 0:
                await vc.disconnect()

    @voice_check.before_loop
    async def before_voice_check(self):
        await self.bot.wait_until_ready()

    @voice_check.error
    async def voice_check_error(self, error):
        logger.error(f"voice_check 任務錯誤: {error}")

async def setup(bot):
    await bot.add_cog(Voice(bot))

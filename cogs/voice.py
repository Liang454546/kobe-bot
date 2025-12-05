import discord
from discord.ext import commands, tasks
import random
import asyncio
import logging
import os
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # 回嗆語錄
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走！但記住：那些殺不死你的，只會讓你更強。",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！Mamba Out.",
            "這就是你的態度？難怪你還在打低端局！Soft.",
            "我走不是因為我怕，是因為我不屑！別吵我，正在訓練。"
        ]
        self.not_in_voice_roasts = [
            "我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？去看醫生吧！",
            "眼睛不需要可以捐給有需要的人！ 我哪裡在語音裡了？",
            "你是在跟鬼說話嗎？ 這裡只有文字，清醒點！",
            "你的曼巴精神是用來幻想的嗎？ 我人都不在，你叫誰滾？軟蛋！"
        ]

        # AI 初始化
        self.model = None
        self.has_ai = False
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                self.has_ai = True
                logger.info("✅ Voice Cog AI 啟動成功")
            except:
                self.has_ai = False

        self.kick_cooldown = {}
        self.voice_check.start()

    def cog_unload(self):
        self.voice_check.cancel()

    async def ask_kobe(self, prompt):
        if not self.has_ai: return random.choice(self.aggressive_leave_msgs)
        try:
            response = await self.model.generate_content_async(f"你是Kobe。毒舌回嗆：{prompt}")
            return response.text.strip()
        except: return random.choice(self.aggressive_leave_msgs)

    # ==========================================
    # 🎤 語音進出監控 (穩定版)
    # ==========================================
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return

        # A. 有人加入語音
        if after.channel and not before.channel:
            # 如果機器人還沒進去，就進去並待著
            if not member.guild.voice_client:
                try:
                    # 🔥 修正：直接連線，不跳出
                    await after.channel.connect()
                    
                    # (可選) 在文字頻道打招呼
                    # channel = self.get_text_channel(member.guild)
                    # if channel: await channel.send(f"🎙️ 曼巴教練已進駐 `{after.channel.name}` 監控訓練！")
                except Exception as e:
                    logger.error(f"語音連線失敗: {e}")

        # B. 有人離開語音
        elif before.channel and not after.channel:
            vc = member.guild.voice_client
            # 如果機器人在該頻道，且頻道只剩機器人 1 人 -> 離開
            if vc and vc.channel == before.channel:
                if len(vc.channel.members) == 1:
                    await vc.disconnect()

    @commands.command(name="滾", aliases=["kickkobe"])
    async def kick_kobe(self, ctx):
        if not ctx.guild.voice_client:
            return await ctx.send(random.choice(self.not_in_voice_roasts))
        
        msg = await self.ask_kobe(f"{ctx.author.display_name} 叫我滾")
        await ctx.send(f"||{ctx.author.mention}|| {msg}")
        await ctx.guild.voice_client.disconnect()

    @tasks.loop(minutes=1)
    async def voice_check(self):
        # 定期檢查：如果機器人卡在沒人的頻道，自動斷線
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and len(vc.channel.members) == 1:
                await vc.disconnect()

    @voice_check.before_loop
    async def before_voice_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Voice(bot))

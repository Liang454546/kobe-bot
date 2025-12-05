import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random
import logging
import os
import google.generativeai as genai
import asyncio
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_CHANNEL_ID = 1385233731073343498

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_today = False
        self.checked_9am = False
        
        self.quotes = [
            "你見過凌晨四點的洛杉磯嗎？早安，曼巴們。🏀",
            "每一種負面情緒——壓力、挑戰——都是我崛起的機會。🐍",
            "低頭不是認輸，是要看清自己的路；仰頭不是驕傲，是要看清自己的天空。",
            "休息是為了走更長遠的路，但不是讓你躺在床上滑手機！😤",
            "今天的努力，是為了明天的奇蹟。👑",
            "我不想和別人一樣，即使這個人是喬丹。——Kobe"
        ]
        
        self.angry_roasts = [
            "😡 **{mention}**！現在凌晨四點你還亮著燈？你的肝是鐵做的嗎？去睡覺！",
            "🏀 **{mention}**，你以為你在練球嗎？不，你在修仙！給我滾去睡覺！",
            "⚠️ **{mention}** 警告！曼巴精神是用來訓練的，不是用來熬夜打遊戲的！",
            "👀 抓到了！**{mention}** 這麼晚還在線上？明天的精神去哪了？",
            "💀 **{mention}**，你是想挑戰人體極限嗎？快去睡，不然沒收你的鍵盤！",
            "3 人小隊裡，就你還醒？**{mention}** 別拖後腿，睡吧！🐍"
        ]
        
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
                logger.info("✅ Daily Cog - Gemini AI 啟動成功")
            except Exception as e:
                logger.error(f"Gemini 啟動失敗: {e}")
        
        self.morning_call.start()

    def cog_unload(self):
        self.morning_call.cancel()

    async def ask_kobe(self, prompt: str) -> str | None:
        if hasattr(self.bot, 'ask_brain'):
            reply = await self.bot.ask_brain(prompt, system_instruction="你是 Kobe Bryant，嚴格的曼巴教練。")
            if reply and "⚠️" not in reply: return reply

        if not self.model: return None
        try:
            response = await self.model.generate_content_async(f"你是 Kobe Bryant。請毒舌罵人：{prompt}")
            return response.text.strip()
        except: return None

    @tasks.loop(seconds=60)
    async def morning_call(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        # 04:00 點名
        if now.hour == 4 and now.minute == 0:
            if not self.checked_today:
                await self.send_motivation()
                self.checked_today = True
        elif now.hour == 4 and now.minute == 1:
            self.checked_today = False

        # 09:00 每日一問
        if now.hour == 9 and now.minute == 0:
            if not self.checked_9am:
                await self.send_daily_question()
                self.checked_9am = True
        elif now.hour == 9 and now.minute == 1:
            self.checked_9am = False

    @morning_call.error
    async def morning_call_error(self, error):
        logger.error(f"morning_call 任務錯誤: {error}")

    async def send_daily_question(self):
        channel = self.get_target_channel()
        if not channel: return

        prompt = "出一個二選一的問題給球員，逼他們選擇是要『變強』還是『當廢物』。例如：今天你要練球還是睡覺？語氣要非常有壓迫感。"
        question = await self.ask_kobe(prompt) or "今天你要變強還是繼續當廢物？回覆 1 或 2。"
        
        embed = discord.Embed(title="❓ 每日曼巴靈魂拷問", description=question, color=0xe67e22)
        embed.set_footer(text="不回答？那就當作你默認是廢物。")
        await channel.send(embed=embed)

    async def send_motivation(self):
        channel = self.get_target_channel()
        if not channel: return

        stay_up_late = []
        if self.bot.guilds:
            guild = self.bot.guilds[0]
            for member in guild.members:
                if member.bot: continue
                if member.status == discord.Status.online:
                    stay_up_late.append(member)

        if stay_up_late:
            if len(stay_up_late) > 1:
                names = "、".join(m.display_name for m in stay_up_late)
                ai_text = await self.ask_kobe(f"3人小隊 {names} 都還醒著，群體毒舌罵醒他們")
                msg = ai_text or f"😡 {names}！你們全隊還在線上？曼巴不允許這種墮落！快睡！🐍🏀"
            else:
                target = stay_up_late[0]
                ai_text = await self.ask_kobe(f"只有 {target.display_name} 還醒著，個人罵他去睡覺")
                msg = ai_text or random.choice(self.angry_roasts).format(mention=target.mention)
            await channel.send(f"🌅 **凌晨四點 · 曼巴點名！**\n{msg}")
        else:
            ai_text = await self.ask_kobe("全員都睡了，發一條勵志語錄鼓勵明天訓練")
            msg = ai_text or random.choice(self.quotes)
            await channel.send(f"🌅 **凌晨四點 · 曼巴時刻**\n{msg} 🐍🏀")

    def get_target_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            channel = discord.utils.get(guild.text_channels, name="general") or guild.system_channel
        return channel

    @morning_call.before_loop
    async def before_morning_call(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Daily(bot))

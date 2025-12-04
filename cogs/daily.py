import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random
import logging
import os
import google.generativeai as genai
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔥 請在這裡填入您要指定的「頻道 ID」(數字)
TARGET_CHANNEL_ID = 1385233731073343498

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_today = False
        
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
        
        # 使用 main.py 的中央大腦，若無則用備用方案
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
        # 嘗試使用 main.py 的中央大腦
        if hasattr(self.bot, 'ask_brain'):
            reply = await self.bot.ask_brain(prompt, system_instruction="你是 Kobe Bryant，在凌晨4點的嚴格教練。")
            if reply and "⚠️" not in reply:
                return reply

        # 備用方案
        if not self.model: return None
        try:
            response = await self.model.generate_content_async(f"你是 Kobe Bryant，現在凌晨4點。請毒舌罵人：{prompt}")
            return response.text.strip()
        except: return None

    @tasks.loop(seconds=60)
    async def morning_call(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        if now.hour == 4 and now.minute == 0 and not self.checked_today:
            await self.send_motivation()
            self.checked_today = True
            logger.info("🕔 凌晨 4 點曼巴點名完成")
        elif now.hour == 4 and now.minute == 1:
            self.checked_today = False

    @morning_call.error
    async def morning_call_error(self, error):
        logger.error(f"morning_call 任務錯誤: {error}")

    async def send_motivation(self):
        if not self.bot.guilds:
            return
            
        guild = self.bot.guilds[0]
        
        # 🔥 修改：優先使用指定頻道 ID
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        
        if not channel:
            channel = discord.utils.get(guild.text_channels, name="general") \
                      or discord.utils.get(guild.text_channels, name="聊天") \
                      or next((c for c in guild.text_channels if "chat" in c.name.lower()), None) \
                      or guild.system_channel
                  
        if not channel or not channel.permissions_for(guild.me).send_messages:
            logger.warning("找不到可發送訊息的頻道")
            return

        stay_up_late = []
        for member in guild.members:
            if member.bot:
                continue
            if member.status == discord.Status.online:
                has_real_activity = any(
                    act.type in (discord.ActivityType.playing,
                                discord.ActivityType.streaming,
                                discord.ActivityType.listening,
                                discord.ActivityType.watching)
                    for act in member.activities
                )
                if has_real_activity or not any(act.type == discord.ActivityType.custom for act in member.activities):
                    stay_up_late.append(member)
                    logger.info(f"🔥 偵測熬夜：{member.display_name}")

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

    @morning_call.before_loop
    async def before_morning_call(self):
        await self.bot.wait_until_ready()
        logger.info("Daily Cog 已就緒，等待凌晨 4 點...")

async def setup(bot):
    await bot.add_cog(Daily(bot))

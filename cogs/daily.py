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

# 🔥 請確認這裡填入的是您的「指定頻道 ID」
TARGET_CHANNEL_ID = 1385233731073343498

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_4am = False
        self.checked_7am = False # 天氣
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
        
        self.time_check_loop.start()

    def cog_unload(self):
        self.time_check_loop.cancel()

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
    async def time_check_loop(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        # 1. 凌晨 04:00 點名
        if now.hour == 4 and now.minute == 0:
            if not self.checked_4am:
                await self.send_motivation()
                self.checked_4am = True
        elif now.hour == 4 and now.minute == 1: self.checked_4am = False

        # 2. 早上 07:00 毒舌天氣
        if now.hour == 7 and now.minute == 0:
            if not self.checked_7am:
                await self.send_weather_roast()
                self.checked_7am = True
        elif now.hour == 7 and now.minute == 1: self.checked_7am = False

        # 3. 早上 09:00 狗狗圖
        if now.hour == 9 and now.minute == 0:
            if not self.checked_9am:
                await self.send_dog_meme()
                self.checked_9am = True
        elif now.hour == 9 and now.minute == 1: self.checked_9am = False

    # 🔥 新增：毒舌天氣預報
    async def send_weather_roast(self):
        channel = self.get_target_channel()
        if not channel: return

        # 抓天氣 (wttr.in 免費 API)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://wttr.in/Taipei?format=%t+%C') as resp:
                    if resp.status == 200:
                        weather_data = await resp.text()
                        weather_data = weather_data.strip() # e.g., "+28°C Sunny"
                    else:
                        weather_data = "未知"
        except: weather_data = "未知"

        # AI 毒舌
        prompt = f"現在台北天氣：{weather_data}。請根據這個天氣，毒舌嘲諷這群懶惰鬼。\n例如：天氣好就罵他們還窩在家打電動；天氣差就罵他們這點雨就不敢出門訓練？"
        roast = await self.ask_kobe(prompt) or "天氣再好，你們這些軟蛋也只會窩在冷氣房。"

        embed = discord.Embed(title=f"🌦️ 曼巴氣象站：台北 {weather_data}", description=roast, color=0x3498db)
        embed.set_footer(text="No excuses. 🐍")
        await channel.send(embed=embed)

    async def send_dog_meme(self):
        channel = self.get_target_channel()
        if not channel: return
        dog_url = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://dog.ceo/api/breeds/image/random') as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        dog_url = data['message']
        except: pass
        if not dog_url: return

        prompt = "這隻狗比你們努力。罵他們。"
        comment = await self.ask_kobe(prompt) or "連狗都起床了，你呢？"
        embed = discord.Embed(title="🐶 每日曼巴犬", description=comment, color=0xe67e22)
        embed.set_image(url=dog_url)
        await channel.send(embed=embed)

    async def send_motivation(self):
        # ... (4AM 點名邏輯保持不變) ...
        channel = self.get_target_channel()
        if not channel: return
        guild = self.bot.guilds[0]
        stay_up_late = [m for m in guild.members if not m.bot and m.status == discord.Status.online]
        
        if stay_up_late:
             names = "、".join(m.display_name for m in stay_up_late)
             msg = await self.ask_kobe(f"{names} 還醒著。罵他們。") or f"😡 {names} 快睡！"
             await channel.send(f"🌅 **凌晨四點點名**\n{msg}")
        else:
             await channel.send(f"🌅 **凌晨四點**\n{random.choice(self.quotes)}")

    def get_target_channel(self):
        if not self.bot.guilds: return None
        guild = self.bot.guilds[0]
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            channel = discord.utils.get(guild.text_channels, name="general") or \
                      discord.utils.get(guild.text_channels, name="聊天") or \
                      guild.system_channel
        return channel

    @time_check_loop.before_loop
    async def before_loop(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Daily(bot))

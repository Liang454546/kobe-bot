import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random
import logging
import os
import google.generativeai as genai
import asyncio
import aiohttp # 新增：用於抓取狗狗圖片

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 🔥 請確認這裡填入的是您的「指定頻道 ID」
TARGET_CHANNEL_ID = 1385233731073343498

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_4am = False
        self.checked_9am = False # 防止重複發送
        
        # 勵志語錄
        self.quotes = [
            "你見過凌晨四點的洛杉磯嗎？早安，曼巴們。🏀",
            "每一種負面情緒——壓力、挑戰——都是我崛起的機會。🐍",
            "低頭不是認輸，是要看清自己的路；仰頭不是驕傲，是要看清自己的天空。",
            "休息是為了走更長遠的路，但不是讓你躺在床上滑手機！😤",
            "今天的努力，是為了明天的奇蹟。👑",
            "我不想和別人一樣，即使這個人是喬丹。——Kobe"
        ]
        
        # 憤怒罵人語錄
        self.angry_roasts = [
            "😡 **{mention}**！現在凌晨四點你還亮著燈？你的肝是鐵做的嗎？去睡覺！",
            "🏀 **{mention}**，你以為你在練球嗎？不，你在修仙！給我滾去睡覺！",
            "⚠️ **{mention}** 警告！曼巴精神是用來訓練的，不是用來熬夜打遊戲的！",
            "👀 抓到了！**{mention}** 這麼晚還在線上？明天的精神去哪了？",
            "💀 **{mention}**，你是想挑戰人體極限嗎？快去睡，不然沒收你的鍵盤！",
            "3 人小隊裡，就你還醒？**{mention}** 別拖後腿，睡吧！🐍"
        ]
        
        # 使用 main.py 的中央大腦
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
        # 嘗試使用 main.py 的中央大腦
        if hasattr(self.bot, 'ask_brain'):
            reply = await self.bot.ask_brain(prompt, system_instruction="你是 Kobe Bryant，嚴格的曼巴教練。")
            if reply and "⚠️" not in reply:
                return reply

        # 備用方案
        if not self.model: return None
        try:
            response = await self.model.generate_content_async(f"你是 Kobe Bryant。請毒舌罵人：{prompt}")
            return response.text.strip()
        except: return None

    # 🔥 統一的時間檢查迴圈 (每 60 秒檢查一次)
    @tasks.loop(seconds=60)
    async def time_check_loop(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        # === 任務 1: 凌晨 04:00 點名 ===
        if now.hour == 4 and now.minute == 0:
            if not self.checked_4am:
                await self.send_motivation()
                self.checked_4am = True
                logger.info("🕔 凌晨 4 點曼巴點名完成")
        elif now.hour == 4 and now.minute == 1:
            self.checked_4am = False

        # === 任務 2: 早上 09:00 狗狗梗圖 ===
        if now.hour == 9 and now.minute == 0:
            if not self.checked_9am:
                await self.send_dog_meme()
                self.checked_9am = True
                logger.info("🐶 早上 9 點狗狗梗圖發送完成")
        elif now.hour == 9 and now.minute == 1:
            self.checked_9am = False

    @time_check_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        logger.info("Daily Cog 計時器已啟動...")

    # ---------------------------------------------------
    # 🐶 發送每日毒舌狗狗圖
    # ---------------------------------------------------
    async def send_dog_meme(self):
        channel = self.get_target_channel()
        if not channel: return

        # 1. 抓狗狗圖
        dog_url = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://dog.ceo/api/breeds/image/random') as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        dog_url = data['message']
        except Exception as e:
            logger.error(f"抓狗圖失敗: {e}")
        
        if not dog_url: return

        # 2. 叫 AI 毒舌解說
        prompt = (
            "現在是早上 9 點。我給你這張狗狗的照片。\n"
            "請你用 Kobe Bryant 的毒舌語氣，指著這隻狗罵伺服器的成員。\n"
            "內容要是：『看這隻狗，牠都比你們努力/早起/有精神。你們還在幹嘛？』\n"
            "繁體中文，30字內，兇一點。"
        )
        
        # 嘗試用中央大腦傳圖 (如果有的話)，沒有就只傳文字 Prompt
        comment = "這隻狗都比你們努力。快去訓練！"
        if hasattr(self.bot, 'ask_brain'):
             # 這裡暫時只傳文字 Prompt，因為傳 URL 給 AI 需要額外下載處理，為了速度我們先讓 AI「想像」或只針對文字 Prompt 回應
             # 其實不需要真的讓 AI 看圖，只要讓它罵「這隻狗」就可以了，效果一樣好笑
             comment = await self.ask_kobe(prompt) or comment

        embed = discord.Embed(
            title="🐶 每日曼巴精神犬 (Daily Mamba Dog)",
            description=f"**Kobe:** 「{comment}」",
            color=0xe67e22
        )
        embed.set_image(url=dog_url)
        await channel.send(embed=embed)

    # ---------------------------------------------------
    # 🌅 凌晨 4 點點名邏輯 (維持原樣)
    # ---------------------------------------------------
    async def send_motivation(self):
        channel = self.get_target_channel()
        if not channel: return

        guild = self.bot.guilds[0]
        stay_up_late = []
        for member in guild.members:
            if member.bot: continue
            if member.status == discord.Status.online:
                has_real_activity = any(act.type in (discord.ActivityType.playing, discord.ActivityType.streaming, discord.ActivityType.listening, discord.ActivityType.watching) for act in member.activities)
                if has_real_activity or not any(act.type == discord.ActivityType.custom for act in member.activities):
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
            channel = discord.utils.get(guild.text_channels, name="general") or \
                      discord.utils.get(guild.text_channels, name="聊天") or \
                      next((c for c in guild.text_channels if "chat" in c.name.lower()), None) or \
                      guild.system_channel
        return channel

async def setup(bot):
    await bot.add_cog(Daily(bot))

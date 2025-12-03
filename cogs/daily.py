import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random
import logging
import os
import google.generativeai as genai
import asyncio  # 必須在最上面

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_today = False
        
        # 勵志語錄（可持續增加）
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
        
        # Gemini 設定
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel(
                    "gemini-1.5-flash",  # 改用更快更穩的 flash（或留 pro）
                    generation_config={"temperature": 0.9, "max_output_tokens": 60}
                )
                logger.info("✅ Daily Cog - Gemini AI 啟動成功")
            except Exception as e:
                logger.error(f"Gemini 啟動失敗: {e}")
        
        self.morning_call.start()

    def cog_unload(self):
        self.morning_call.cancel()

    # 安全呼叫 Gemini（完全異步）
    async def ask_kobe(self, prompt: str) -> str | None:
        if not self.model:
            return None
            
        full_prompt = (
            "你是 Kobe Bryant，在一個只有 3 人的台灣小 Discord 當嚴格教練。\n"
            "現在是凌晨 4 點，語氣要毒舌、嚴厲但勵志，用繁體中文（台灣腔），"
            "一定要加籃球或蛇相關 emoji (🏀🐍)，控制在 40 字以內。\n\n"
            f"情境：{prompt}"
        )
        
        try:
            response = await self.model.generate_content_async(full_prompt)
            text = response.text.strip()
            return text if text else None
        except Exception as e:
            logger.error(f"AI 生成失敗: {e}")
            return None

    @tasks.loop(seconds=60)
    async def morning_call(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        
        if now.hour == 4 and now.minute == 0 and not self.checked_today:
            await self.send_motivation()
            self.checked_today = True
            logger.info("🕔 凌晨 4 點曼巴點名完成")
        elif now.hour == 4 and now.minute == 1:
            # 過了 4:00 就重置，準備明天
            self.checked_today = False

    @morning_call.error
    async def morning_call_error(self, error):
        logger.error(f"morning_call 任務錯誤: {error}")

    async def send_motivation(self):
        if not self.bot.guilds:
            return
            
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.text_channels, name="general") \
                  or discord.utils.get(guild.text_channels, name="聊天") \
                  or next((c for c in guild.text_channels if "chat" in c.name.lower()), None) \
                  or guild.system_channel
                  
        if not channel or not channel.permissions_for(guild.me).send_messages:
            logger.warning("找不到可發送訊息的頻道")
            return

        # 偵測真正熬夜的人（online + 有活動：遊戲、聽歌、串流等）
        stay_up_late = []
        for member in guild.members:
            if member.bot:
                continue
            # 只要 online 且不是純粹「自訂狀態」，就視為活躍
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

        # 決定要罵還是勵志
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

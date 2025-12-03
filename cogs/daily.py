import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import random
import logging  # 新增：log
import os  # 新增：env
import google.generativeai as genai  # 新增：AI 整合

# 設定 log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Daily(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.checked_today = False
        
        # 擴充勵志語錄（加搜到的 Kobe 名言）
        self.quotes = [
            "你見過凌晨四點的洛杉磯嗎？早安，曼巴們。🏀",
            "每一種負面情緒——壓力、挑戰——都是我崛起的機會。🐍",
            "低頭不是認輸，是要看清自己的路；仰頭不是驕傲，是要看清自己的天空。",
            "休息是為了走更長遠的路，但不是讓你躺在床上滑手機！😤",
            "今天的努力，是為了明天的奇蹟。👑",
            "我不想和別人一樣，即使這個人是喬丹。——Kobe（轉繁）"  # 新增：從網搜
        ]

        # 擴充憤怒罵人（3 人小隊版）
        self.angry_roasts = [
            "😡 **{mention}**！現在凌晨四點你還亮著燈？你的肝是鐵做的嗎？去睡覺！",
            "🏀 **{mention}**，你以為你在練球嗎？不，你在修仙！給我滾去睡覺！",
            "⚠️ **{mention}** 警告！曼巴精神是用來訓練的，不是用來熬夜打遊戲的！",
            "👀 抓到了！**{mention}** 這麼晚還在線上？明天的精神去哪了？",
            "💀 **{mention}**，你是想挑戰人體極限嗎？快去睡，不然沒收你的鍵盤！",
            "3 人小隊裡，就你還醒？**{mention}** 別拖後腿，睡吧！🐍"  # 新增：小伺服器味
        ]
        
        # AI 設定（借 Game 的邏輯，共用 model）
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro")
                logger.info("✅ Daily AI 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")
        
        # 啟動定時任務
        self.morning_call.start()

    def cog_unload(self):
        self.morning_call.cancel()

    # AI Kobe 生成（簡化版 ask_kobe）
    async def ask_kobe(self, prompt, cooldown_time=0):
        if not self.model: return None
        try:
            sys_prompt = "你是 Kobe Bryant，在 3 人小 Discord 伺服器當教練。凌晨 4 點點名，語氣毒舌嚴格但勵志。繁體中文(台灣)，簡短(40字內)，多 emoji (🏀🐍)。"
            contents = [sys_prompt, prompt]
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)  # 需要 import asyncio
            return response.text
        except Exception as e:
            logger.error(f"AI 生成失敗: {e}")
            return None

    # 每 60 秒檢查一次時間
    @tasks.loop(seconds=60)
    async def morning_call(self):
        # 設定台灣時區 (UTC+8)
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)

        # 檢查是否為凌晨 04:00
        if now.hour == 4 and now.minute == 0:
            if not self.checked_today:
                await self.send_motivation()
                self.checked_today = True
                logger.info("凌晨 4 點點名完成")
        else:
            # 過了 4:00 就重置開關，等待明天
            self.checked_today = False

    async def send_motivation(self):
        # 取得頻道（優化：優先 general/chat）
        if not self.bot.guilds:
            return
        guild = self.bot.guilds[0]
        channel = discord.utils.find(lambda c: any(kw in c.name.lower() for kw in ["general", "chat", "聊天"]), guild.text_channels)
        if not channel:
            channel = guild.system_channel
        if not channel or not channel.permissions_for(guild.me).send_messages:
            logger.warning("無可用頻道")
            return

        # --- 掃描熬夜仔邏輯（修：嚴格，只抓線上+活動） ---
        stay_up_late_members = []
        for member in guild.members:
            if member.bot:
                continue
            # 修：只抓 status == online 且有活動（玩遊戲/聽歌等）
            is_active = (member.status == discord.Status.online) and bool([a for a in member.activities if a.type != discord.ActivityType.custom])
            if is_active:
                stay_up_late_members.append(member)
                logger.info(f"偵測熬夜：{member.display_name}")

        # --- 決定發送什麼訊息（加 AI 自訂） ---
        if stay_up_late_members:
            # 憤怒模式：如果 >1 人，群嘲；否則個人
            if len(stay_up_late_members) > 1:
                names = ", ".join([m.display_name for m in stay_up_late_members])
                prompt = f"3 人小隊 {names} 凌晨 4 點還在線，群體毒舌罵他們去睡。"
                ai_msg = await self.ask_kobe(prompt)
                if not ai_msg:
                    ai_msg = f"😡 3 人小隊全體點名！{names} 你們在幹嘛？快睡，明天再戰！🐍"
                await channel.send(f"🌅 **凌晨四點小隊點名！**\n{ai_msg}")
            else:
                target = stay_up_late_members[0]
                prompt = f"個人 {target.display_name} 凌晨 4 點熬夜，毒舌罵他去睡，像 Kobe。"
                ai_msg = await self.ask_kobe(prompt)
                if not ai_msg:
                    msg = random.choice(self.angry_roasts).format(mention=target.mention)
                    ai_msg = msg
                await channel.send(f"🌅 **凌晨四點點名！**\n{ai_msg}")
        else:
            # 勵志模式
            prompt = "凌晨 4 點，大家都睡了，發勵志語錄鼓勵小隊明天訓練。"
            ai_msg = await self.ask_kobe(prompt)
            if not ai_msg:
                ai_msg = random.choice(self.quotes)
            await channel.send(f"🌅 **凌晨四點：曼巴時刻**\n{ai_msg}")

    @morning_call.before_loop
    async def before_morning_call(self):
        await self.bot.wait_until_ready()
        logger.info("Daily Cog 啟動，等待凌晨 4 點")

# 需要 import asyncio 在頂端
import asyncio  # 加這行

async def setup(bot):
    await bot.add_cog(Daily(bot))

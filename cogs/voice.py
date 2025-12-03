import discord
from discord.ext import commands, tasks
import random
import asyncio
import time
import aiosqlite  # 新增：DB
import os  # 新增：env
import google.generativeai as genai  # 新增：AI
import logging  # 新增：log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"  # 借 Game
        self.voice_sessions = {}  # 借 Game：{user_id: {'vc': vc, 'start_time': time, 'last_audio': time}}
        
        # 擴充回嗆（加 Kobe 名言）
        self.aggressive_leave_msgs = [
            "叫我滾？你算老幾？好，我走！但記住：那些殺不死你的，只會讓你更強。🖕😤",
            "軟蛋才叫人滾！曼巴精神是面對挑戰！Mamba Out. 🏀👎",
            "這就是你的態度？難怪你還在打低端局！Soft. 🥚💀",
            "我走不是因為我怕，是因為我不屑！別吵我，正在訓練。😤👋"
        ]

        # 擴充嘲諷（3 人小隊版）
        self.not_in_voice_roasts = [
            "我根本不在語音裡，你對著空氣吼什麼？幻聽了嗎？3 人小隊，去看醫生吧！🏥💊",
            "眼睛不需要可以捐給有需要的人！👀 我哪裡在語音裡了？小隊別浪費時間。",
            "你是在跟鬼說話嗎？👻 這裡只有文字，清醒點！曼巴需要專注。",
            "你的曼巴精神是用來幻想的嗎？🏀 我人都不在，你叫誰滾？軟蛋！"
        ]
        
        # AI 設定（借 Game，簡版）
        api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("gemini-pro")
                logger.info("✅ Voice AI 啟動成功")
            except Exception as e:
                logger.error(f"AI 啟動失敗: {e}")

        # 啟動靜音檢查
        self.voice_check.start()

    async def cog_load(self):
        # 確保 DB 表（借 Game）
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS voice_stats (user_id INTEGER, guild_id INTEGER, duration INTEGER, last_spoke DATE)')
            await db.commit()

    def cog_unload(self):
        self.voice_check.cancel()

    # AI Kobe 生成（借 Game）
    async def ask_kobe(self, prompt, cooldown_time=0):
        if not self.model: return None
        try:
            sys_prompt = "你是 Kobe Bryant，在 3 人小 Discord 語音室當教練。語氣毒舌嚴格勵志，繁體中文(台灣)，簡短(30字內)，多 emoji (🏀🐍)。"
            contents = [sys_prompt, prompt]
            response = await asyncio.to_thread(self.model.generate_content, contents=contents)
            return response.text
        except Exception as e:
            logger.error(f"AI 生成失敗: {e}")
            return None

    # 更新語音 stats（借 update_daily_stats）
    async def update_voice_stats(self, user_id, duration):
        async with aiosqlite.connect(self.db_name) as db:
            now = time.time()
            await db.execute('INSERT INTO voice_stats (user_id, guild_id, duration, last_spoke) VALUES (?, ?, ?, ?)',
                             (user_id, self.bot.guilds[0].id if self.bot.guilds else 0, duration, now))
            await db.commit()
            # 連 lazy_points：長時 +1/min
            if duration > 300:  # 5分
                # 假設有 update_daily_stats
                pass  # await self.update_daily_stats(user_id, 'lazy_points', duration // 60)

    # 監聽：語音狀態改變 (升級：AI 廣播 + 時長記錄)
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        user_id = member.id
        guild = member.guild

        # 情況 A: 加入語音 (非移動)
        if after.channel and before.channel != after.channel:
            # 自動跟隨 (加 timeout)
            if not guild.voice_client:
                try:
                    vc = await after.channel.connect(timeout=10)
                    self.voice_sessions[user_id] = {'vc': vc, 'start_time': time.time(), 'last_audio': time.time()}
                except Exception as e:
                    logger.error(f"連線失敗: {e}")
                    return
            
            # AI 毒舌廣播
            channel = self.get_broadcast_channel(guild)
            if channel:
                prompt = f"{member.display_name} 加入 3 人語音小隊，毒舌歡迎他訓練還是來送分？"
                msg = await self.ask_kobe(prompt) or f"Man, what can I say? {member.mention} 進來了！小隊齊了，準備 Mamba？🐍"
                await channel.send(msg)

        # 情況 B: 離開語音 (記錄時長 + 總結)
        elif before.channel and not after.channel:
            if user_id in self.voice_sessions:
                session = self.voice_sessions.pop(user_id)
                vc = session.get('vc')
                duration = int(time.time() - session['start_time'])
                await self.update_voice_stats(user_id, duration)
                
                # 總結 roast (如果 >10分)
                if duration > 600:
                    channel = self.get_broadcast_channel(guild)
                    if channel:
                        prompt = f"{member.display_name} 語音 {duration//60} 分鐘，質問貢獻什麼？"
                        summary = await self.ask_kobe(prompt) or f"{member.mention} 語音結束！貢獻 {duration//60} 分鐘廢話？Soft. 🥚"
                        await channel.send(summary)
                
                # 空頻斷線
                if vc and len(before.channel.members) == 0:
                    await vc.disconnect()

    # 監聽：文字訊息 (關鍵字「滾」，加上下文)
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        content = message.content.lower()

        # 偵測「滾」且語音相關 (加 "語音" 或 @bot)
        if "滾" in content and (self.bot.user in message.mentions or "語音" in content):
            guild = message.guild
            if guild and guild.voice_client:
                # 在語音：AI 回嗆 + 斷
                prompt = f"用戶叫 {message.author.display_name} 叫 Kobe Bot 滾出語音，反毒舌回嗆。"
                roast = await self.ask_kobe(prompt) or random.choice(self.aggressive_leave_msgs)
                await message.reply(roast)
                await guild.voice_client.disconnect()
            else:
                # 不在：嘲諷
                prompt = f"用戶 {message.author.display_name} 叫不存在的語音 Bot 滾，嘲諷他眼殘。"
                roast = await self.ask_kobe(prompt) or random.choice(self.not_in_voice_roasts)
                await message.reply(roast)

        await self.bot.process_commands(message)  # 修：交還控制

    # 靜音檢查 (借 voice_check，每 5 分)
    @tasks.loop(minutes=5)
    async def voice_check(self):
        for user_id, session in list(self.voice_sessions.items()):
            vc = session.get('vc')
            if vc and vc.is_connected():
                if time.time() - session.get('last_audio', 0) > 300:  # 5分無音
                    member = self.bot.get_user(user_id)
                    if member and member.voice:
                        channel = self.get_broadcast_channel(member.guild)
                        if channel:
                            prompt = f"{member.display_name} 語音靜音太久，毒舌提醒說話！"
                            msg = await self.ask_kobe(prompt) or f"{member.mention} 靜音？說話訓練你的嘴！🐍"
                            await channel.send(msg)
                        # 可斷線：await vc.disconnect(); del self.voice_sessions[user_id]

    @voice_check.before_loop
    async def before_voice_check(self):
        await self.bot.wait_until_ready()

    def get_broadcast_channel(self, guild):
        target = ["chat", "general", "聊天", "公頻"]
        return discord.utils.find(lambda x: any(t in x.name.lower() for t in target), guild.text_channels) or guild.text_channels[0]

async def setup(bot):
    await bot.add_cog(Voice(bot))

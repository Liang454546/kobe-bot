import discord
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import time
from datetime import datetime, timedelta, timezone
import random
import os
import io
import aiohttp
import logging
from PIL import Image
from collections import deque, Counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 請確認這裡填入的是您的「指定頻道 ID」
TARGET_CHANNEL_ID = 1385233731073343498

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"
       
        # 狀態儲存
        self.active_sessions = {}
        self.pending_replies = {}
        self.processed_msg_ids = deque(maxlen=2000)
        self.last_spotify_roast = {}
        self.short_term_memory = {}
        self.last_chat_time = {}
        self.last_music_processed = {}
        self.user_goals = {}
       
        # 任務執行標記
        self._morning_executed = None
        self._4am_executed = None
        self._daily_executed = None
        self._weekly_executed = None
       
        # 冷卻系統
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {}
        self.detail_cooldowns = {}
        self.toxic_cooldowns = {}
       
        # 新功能所需變數（全部補回）
        self.long_term_memory = {}
        self.daily_question_asked = None
        self.daily_question_msg_id = None
        self.pending_daily_answer = set()
        self.daily_question_channel = None
        self.last_daily_summary = None
        self.daily_word_count = {}
        self.spotify_taste = {}
       
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息"]
        self.toxic_words = ["幹", "靠", "爛", "輸"]
        self.nonsense_words = ["哈", "喔", "笑死", "恩", "4", "呵呵", "真假", "確實"]
        self.kobe_quotes = ["Mamba Out.", "別吵我，正在訓練。", "那些殺不死你的，只會讓你更強。", "Soft."]
        
        # 凌晨4點語錄
        self.morning_quotes = [
            "你見過凌晨四點的洛杉磯嗎？早安，曼巴們。",
            "每一種負面情緒——壓力、挑戰——都是我崛起的機會。",
            "低頭不是認輸，是要看清自己的路；仰頭不是驕傲，是要看清自己的天空。",
            "休息是為了走更長遠的路，但不是讓你躺在床上滑手機！",
            "今天的努力，是為了明天的奇蹟。",
            "我不想和別人一樣，即使這個人是喬丹。——Kobe"
        ]
        self.angry_roasts = [
            "{mention}！現在凌晨四點你還亮著燈？你的肝是鐵做的嗎？去睡覺！",
            "{mention}，你以為你在練球嗎？不，你在修仙！給我滾去睡覺！",
            "{mention} 警告！曼巴精神是用來訓練的，不是用來熬夜打遊戲的！",
            "抓到了！{mention} 這麼晚還在線上？明天的精神去哪了？",
            "{mention}，你是想挑戰人體極限嗎？快去睡，不然沒收你的鍵盤！",
            "全隊都睡了，就你還醒？{mention} 別拖後腿，睡吧！"
        ]
        
        self.sys_prompt_template = (
            "你是 Kobe Bryant。個性：真實、不恭維、專業、現實、專注於問題。\n"
            "1. 回答問題給專業、嚴厲但實用的建議。絕對不要硬扯籃球比喻，除非真的貼切。\n"
            "2. 如果是連續對話，參考前文。\n"
            "3. 音樂審判時你是心理學大師，要提歌名。\n"
            "4. 錯字/邏輯嚴厲糾正。\n"
            "5. 繁體中文(台灣)，30字內，多用 emoji (籃球蛇)。"
        )

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.executescript('''
                CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE, PRIMARY KEY(user_id, game_name));
                CREATE TABLE IF NOT EXISTS honor (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, last_vote_date DATE);
                CREATE TABLE IF NOT EXISTS daily_stats (user_id INTEGER PRIMARY KEY, msg_count INTEGER DEFAULT 0, lazy_points INTEGER DEFAULT 0, roasted_count INTEGER DEFAULT 0, last_updated DATE);
                CREATE TABLE IF NOT EXISTS chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS music_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, artist TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS nonsense_stats (user_id INTEGER PRIMARY KEY, count INTEGER DEFAULT 0);
            ''')
            await db.commit()
       
        self.daily_tasks.start()
        self.weekly_tasks.start()
        self.game_check.start()
        self.ghost_check.start()
        self.morning_execution.start()
        self.daily_mamba_question.start()
        self.mood_radar.start()
        self.daily_summary_and_memory.start()
        self.morning_4am_check.start()
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        for t in [self.daily_tasks, self.weekly_tasks, self.game_check, self.ghost_check,
                  self.morning_execution, self.daily_mamba_question, self.mood_radar,
                  self.daily_summary_and_memory, self.morning_4am_check]:
            if t.is_running():
                t.cancel()

    def get_text_channel(self, guild):
        if not guild: return None
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        return discord.utils.find(
            lambda c: any(t in c.name.lower() for t in ["chat", "general", "聊天", "公頻"]) and c.permissions_for(guild.me).send_messages,
            guild.text_channels
        ) or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        if not hasattr(self.bot, 'ask_brain') or not self.bot.ask_brain:
            return None
           
        now = time.time()
        if user_id and cooldown_dict is not None:
            if now - cooldown_dict.get(user_id, 0) < cooldown_time:
                return "COOLDOWN"
            cooldown_dict[user_id] = now
        try:
            final_prompt = f"情境/用戶說：{prompt}"
            history = None
            if use_memory and user_id:
                if now - self.last_chat_time.get(user_id, 0) > 600:
                    self.short_term_memory[user_id] = []
                self.last_chat_time[user_id] = now
                history = self.short_term_memory.get(user_id, [])
            reply_text = await self.bot.ask_brain(final_prompt, image=image, system_instruction=self.sys_prompt_template, history=history)
            if use_memory and user_id and not image and reply_text:
                self.short_term_memory.setdefault(user_id, [])
                self.short_term_memory[user_id].append({'role': 'user', 'parts': [final_prompt]})
                self.short_term_memory[user_id].append({'role': 'model', 'parts': [reply_text]})
                if len(self.short_term_memory[user_id]) > 10:
                    self.short_term_memory[user_id] = self.short_term_memory[user_id][-10:]
            return reply_text
        except Exception as e:
            if "429" in str(e): return "AI 額度滿了 (Rate Limit)，請稍候。"
            logger.error(f"AI 錯誤: {e}")
            return "ERROR"

    # ...（以下所有函式：analyze_image, on_presence_update, on_message, save_to_db, update_daily_stats, add_honor, ghost_check, game_check, send_warning, weekly_tasks, daily_tasks, morning_execution 全保留你原本的）...

    # ==================== 凌晨 4 點點名 ====================
    @tasks.loop(minutes=1)
    async def morning_4am_check(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        
        if now.hour == 4 and now.minute == 0:
            if self._4am_executed != today_str:
                await self.send_4am_motivation()
                self._4am_executed = today_str

    async def send_4am_motivation(self):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild: return
        channel = self.get_text_channel(guild)
        if not channel: return

        stay_up_late = [m for m in guild.members if not m.bot and m.status == discord.Status.online]
        
        if stay_up_late:
            if len(stay_up_late) > 5:
                names = "、".join(m.display_name for m in stay_up_late[:5]) + " 等廢物"
                prompt = f"凌晨4點還有 {len(stay_up_late)} 人醒著，包括 {names}，群體毒舌罵他們去睡覺，語氣要極兇，結尾帶蛇死"
            elif len(stay_up_late) > 1:
                names = "、".join(m.display_name for m in stay_up_late)
                prompt = f"凌晨4點還有 {names} 醒著，群體毒舌罵醒他們，結尾帶蛇死"
            else:
                target = stay_up_late[0]
                prompt = f"只有 {target.display_name} 凌晨4點還醒著，個人罵他去睡覺，結尾帶蛇死"
            
            roast = await self.ask_kobe(prompt, None, {}, 0)
            msg = roast or random.choice(self.angry_roasts).format(mention=" ".join(m.mention for m in stay_up_late[:10]))
            title = "04:00 · 曼巴點名處刑"
            color = 0x8e44ad
        else:
            msg = await self.ask_kobe("凌晨4點全員都睡了，發一條勵志語錄鼓勵明天訓練", None, {}, 0)
            msg = msg or random.choice(self.morning_quotes)
            title = "04:00 · 曼巴時刻"
            color = 0x2c3e50

        embed = discord.Embed(title=title, description=msg, color=color)
        embed.set_footer(text="Mamba Mentality | 凌晨4點的洛杉磯")
        await channel.send(embed=embed)

    # ==================== 每日一問（完整）===================
    @tasks.loop(hours=24)
    async def daily_mamba_question(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if not (now.hour == 9 and now.minute < 5):
            return
        today = now.strftime("%Y-%m-%d")
        if self.daily_question_asked == today:
            return
        self.daily_question_asked = today
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild: return
        channel = self.get_text_channel(guild)
        if not channel: return

        self.pending_daily_answer = set()
        self.daily_question_channel = channel
        self.daily_question_msg_id = None

        active_members = {m.id for m in guild.members if not m.bot and m.status != discord.Status.offline}
        self.pending_daily_answer = active_members.copy()

        embed = discord.Embed(title="【每日曼巴意志測驗】", color=0x000000)
        embed.description = "**今天你要變強還是繼續當廢物？**\n\n1️⃣ 變強　　2️⃣ 當廢物\n\n⏰ **60 秒內不回覆 → 公開處刑 +10 懶惰點**"
        embed.set_footer(text=f"日期：{today} | Mamba is watching")

        try:
            msg = await channel.send("@everyone", embed=embed)
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")
            self.daily_question_msg_id = msg.id

            async def execution():
                await asyncio.sleep(68)
                if self.daily_question_msg_id != msg.id: return
                if not self.pending_daily_answer: return
                losers = [guild.get_member(uid) for uid in self.pending_daily_answer if guild.get_member(uid)]
                if not losers: return
                mentions = " ".join(m.mention for m in losers[:20]) if len(losers) <= 20 else f"{len(losers)}名廢物"
                roast = await self.ask_kobe(f"這{len(losers)}人60秒沒回答，極兇罵醒他們，結尾蛇死", None, {}, 0)
                await channel.send(f"【意志力處刑】 {mentions}\n{roast or '廢物就是廢物。蛇死'}")
                for m in losers:
                    await self.update_daily_stats(m.id, "lazy_points", 10)
                self.pending_daily_answer.clear()
                self.daily_question_msg_id = None
            self.bot.loop.create_task(execution())
        except Exception as e:
            logger.error(f"每日一問失敗: {e}")

    # ==================== 情緒雷達（完整）===================
    @tasks.loop(minutes=15)
    async def mood_radar(self):
        guild = self.bot.guilds[0]
        channel = self.get_text_channel(guild)
        if not channel: return
        async with aiosqlite.connect(self.db_name) as db:
            limit = time.time() - 3600
            cursor = await db.execute("SELECT content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 25", (limit,))
            rows = await cursor.fetchall()
        if len(rows) < 8: return
        text = " | ".join(r[0] for r in rows)
        mood = await self.ask_kobe(f"用一個詞總結這25句話情緒：開心/低落/嗨/憤怒/正常\n內容：{text}", None, {}, 0)
        if not mood: return
        if "低落" in mood or "累" in mood:
            await channel.send("https://youtu.be/V2v5ZsoR1Mk")
            await channel.send("「You don't get better sitting on the bench.」蛇")
        elif "嗨" in mood or "笑死" in mood:
            await channel.send("『你們這叫興奮？我叫這幼稚。去訓練。』死")

    # ==================== 深夜日報（完整）===================
    @tasks.loop(hours=24)
    async def daily_summary_and_memory(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.hour == 0 and now.minute < 10:
            today = now.strftime("%Y-%m-%d")
            if self.last_daily_summary == today: return
            self.last_daily_summary = today
            channel = self.get_text_channel(self.bot.guilds[0])
            if not channel or not self.daily_word_count: return
            all_text = " ".join(self.daily_word_count.values())
            top5 = Counter(all_text.split()).most_common(5)
            words = "、".join(f"{w}({c}次)" for w,c in top5)
            embed = discord.Embed(title="曼巴深夜戰報", color=0x000000)
            embed.description = f"今日最常出現的詞：{words}\n\nMamba never sleeps. 你呢？蛇"
            await channel.send(embed=embed)
            self.daily_word_count.clear()

    # ==================== 所有 before_loop（完整）===================
    @daily_mamba_question.before_loop
    @mood_radar.before_loop
    @daily_summary_and_memory.before_loop
    @morning_4am_check.before_loop
    @game_check.before_loop
    @daily_tasks.before_loop
    @weekly_tasks.before_loop
    @ghost_check.before_loop
    @morning_execution.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))

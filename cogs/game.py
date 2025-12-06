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

TARGET_CHANNEL_ID = 1385233731073343498

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = "mamba_system.db"

        # 狀態儲存
        self.active_sessions = {}
        self.pending_replies = {}
        self.processed_msg_ids = deque(maxlen=2000)
        self.last_music_processed = {}
        self.short_term_memory = {}
        self.last_chat_time = {}
        self.user_goals = {}

        # 任務執行標記（全部補齊！絕對不會再 AttributeError）
        self._morning_executed = None   # 08:00 起床氣
        self._4am_executed = None       # 04:00 點名
        self._daily_executed = None     # 23:59 日報
        self._weekly_executed = None    # 週日 20:00

        # 冷卻系統
        self.ai_roast_cooldowns = {}
        self.ai_chat_cooldowns = {}
        self.image_cooldowns = {}
        self.spotify_cooldowns = {}
        self.detail_cooldowns = {}
        self.toxic_cooldowns = {}

        # 新功能變數
        self.long_term_memory = {}
        self.daily_question_asked = None
        self.daily_question_msg_id = None
        self.pending_daily_answer = set()
        self.daily_question_channel = None
        self.last_daily_summary = None
        self.daily_word_count = {}
        self.spotify_taste = {}

        # 關鍵字
        self.weak_words = ["累", "好累", "想睡", "放棄", "休息", "好睏", "沒力", "廢了"]
        self.toxic_words = ["幹", "靠", "爛", "輸", "垃圾", "廢物"]
        self.nonsense_words = ["哈", "喔", "笑死", "恩", "4", "呵呵", "真假", "確實"]

        # 語錄
        self.kobe_quotes = ["Mamba Out.", "別吵我，正在訓練。", "那些殺不死你的，只會讓你更強。", "Soft."]
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

        # 啟動所有任務（包含凌晨4點點名！）
        self.daily_tasks.start()
        self.weekly_tasks.start()
        self.game_check.start()
        self.ghost_check.start()
        self.morning_execution.start()
        self.daily_mamba_question.start()
        self.mood_radar.start()
        self.daily_summary_and_memory.start()
        self.morning_4am_check.start()  # 凌晨4點點名啟動！

        await self.bot.wait_until_ready()

    async def cog_unload(self):
        tasks_to_cancel = [
            self.daily_tasks, self.weekly_tasks, self.game_check, self.ghost_check,
            self.morning_execution, self.daily_mamba_question, self.mood_radar,
            self.daily_summary_and_memory, self.morning_4am_check
        ]
        for t in tasks_to_cancel:
            if t.is_running():
                t.cancel()

    def get_text_channel(self, guild):
        if not guild:
            return None
        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if channel and channel.permissions_for(guild.me).send_messages:
            return channel
        # 備用搜尋
        return discord.utils.find(
            lambda c: any(t in c.name.lower() for t in ["chat", "general", "聊天", "公頻"]) 
                     and c.permissions_for(guild.me).send_messages,
            guild.text_channels
        ) or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
    async def ask_kobe(self, prompt, user_id=None, cooldown_dict=None, cooldown_time=30, image=None, use_memory=False):
        now = time.time()
        
        # 冷卻保護
        if user_id and cooldown_dict is not None:
            last = cooldown_dict.get(user_id, 0)
            if now - last < cooldown_time:
                return None  # 靜默冷卻
            cooldown_dict[user_id] = now

        # 如果主 AI 沒載入，直接用靜態語錄（永不當機）
        if not hasattr(self.bot, 'ask_brain') or not callable(getattr(self.bot, 'ask_brain', None)):
            return random.choice([
                "Mamba Out.", "Soft.", "去訓練。", "你很弱。",
                "別吵我，正在練球。", "第二名就是第一個輸家。",
                "那些殺不死你的，只會讓你更強。"
            ])

        try:
            final_prompt = f"情境/用戶說：{prompt}"
            history = None
            if use_memory and user_id:
                if now - self.last_chat_time.get(user_id, 0) > 600:
                    self.short_term_memory[user_id] = []
                self.last_chat_time[user_id] = now
                history = self.short_term_memory.get(user_id, [])

            # 15 秒超時保護
            reply = await asyncio.wait_for(
                self.bot.ask_brain(
                    final_prompt,
                    image=image,
                    system_instruction=self.sys_prompt_template,
                    history=history
                ),
                timeout=15.0
            )

            if reply and "⚠️" not in reply and "ERROR" not in reply:
                # 更新記憶
                if use_memory and user_id and not image:
                    self.short_term_memory.setdefault(user_id, [])
                    self.short_term_memory[user_id].extend([
                        {'role': 'user', 'parts': [final_prompt]},
                        {'role': 'model', 'parts': [reply]}
                    ])
                    if len(self.short_term_memory[user_id]) > 10:
                        self.short_term_memory[user_id] = self.short_term_memory[user_id][-10:]
                return reply
            return None

        except asyncio.TimeoutError:
            logger.warning("AI 回應超時，切換靜態模式")
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning("AI 429 額度暫滿，切換靜態模式")
            elif "404" in str(e):
                logger.warning("AI 模型 404（名稱過期），切換靜態模式")
            elif "unauthorized" in str(e).lower():
                logger.warning("API Key 無效，切換靜態模式")
            else:
                logger.error(f"AI 未知錯誤: {e}")

        # 所有失敗的最終保底
        return random.choice([
            "Mamba Out.", "Soft.", "去訓練。", "你很弱。",
            "別吵我，正在練球。", "第二名就是第一個輸家。",
            "那些殺不死你的，只會讓你更強。"
        ])
        # ==================== 凌晨 4 點點名（最終版）===================
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
                prompt = f"凌晨4點還有 {len(stay_up_late)} 人醒著，包括 {names}，群體毒舌罵他們去睡覺，語氣極兇，結尾帶 🐍💀"
            elif len(stay_up_late) > 1:
                names = "、".join(m.display_name for m in stay_up_late)
                prompt = f"凌晨4點還有 {names} 醒著，群體毒舌罵醒他們，結尾帶 🐍💀"
            else:
                target = stay_up_late[0]
                prompt = f"只有 {target.display_name} 凌晨4點還醒著，個人罵他去睡覺，結尾帶 🐍💀"
            
            roast = await self.ask_kobe(prompt, None, {}, 0)
            msg = roast or random.choice(self.angry_roasts).format(mention=" ".join(m.mention for m in stay_up_late[:10]))
            title = "04:00 · 曼巴點名處刑"
            color = 0x8e44ad
        else:
            prompt = "凌晨4點全員都睡了，發一條勵志語錄鼓勵明天訓練"
            msg = await self.ask_kobe(prompt, None, {}, 0)
            msg = msg or random.choice(self.morning_quotes)
            title = "04:00 · 曼巴時刻"
            color = 0x2c3e50

        embed = discord.Embed(title=title, description=msg, color=color)
        embed.set_footer(text="Mamba Mentality | 凌晨4點的洛杉磯")
        await channel.send(embed=embed)

    @morning_4am_check.before_loop
    async def before_4am(self):
        await self.bot.wait_until_ready()

    @morning_4am_check.error
    async def morning_4am_check_error(self, error):
        logger.error(f"凌晨4點點名錯誤: {error}")
        await asyncio.sleep(60)  # 錯誤後等1分鐘再試
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        if not channel: return

        # 遊戲監控
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            msg = roast if roast and roast != "ERROR" else f"玩 {new_game}？去訓練！"
            await channel.send(f"{after.mention} {msg}")

        elif old_game and not new_game and user_id in self.active_sessions:
            session = self.active_sessions.pop(user_id, None)
            if session:
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                if duration > 600:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問收穫。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN":
                        await channel.send(f"賽後採訪 {after.mention}\n{interview}")

        # Spotify 監控 + 長期心理分析
        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        if new_spotify:
            now = time.time()
            if now - self.last_music_processed.get(user_id, 0) < 10: return
            self.last_music_processed[user_id] = now

            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO music_history (user_id, title, artist, timestamp) VALUES (?, ?, ?, ?)",
                                 (user_id, new_spotify.title, new_spotify.artist, now))
                await db.commit()

            # 情緒分類
            title_art = (new_spotify.title + " " + new_spotify.artist).lower()
            mood_map = {
                "sad": ["哭", "雨", "分手", "夜", "slow", "ballad", "lonely"],
                "angry": ["fuck", "shit", "rage", "恨", "幹"],
                "chill": ["lofi", "chill", "relax", "study"],
                "hype": ["gym", "workout", "rap", "rock", "pump"]
            }
            detected = "neutral"
            for mood, keywords in mood_map.items():
                if any(k in title_art for k in keywords):
                    detected = mood
                    break

            # 長期記憶
            self.spotify_taste.setdefault(user_id, {"count": 0, "moods": {}})
            self.spotify_taste[user_id]["count"] += 1
            self.spotify_taste[user_id]["moods"][detected] = self.spotify_taste[user_id]["moods"].get(detected, 0) + 1

            # 每15首深度分析一次
            if self.spotify_taste[user_id]["count"] % 15 == 0:
                total = sum(self.spotify_taste[user_id]["moods"].values())
                dominant = max(self.spotify_taste[user_id]["moods"], key=self.spotify_taste[user_id]["moods"].get)
                pct = self.spotify_taste[user_id]["moods"][dominant] / total * 100
                if pct > 65:
                    roast = await self.ask_kobe(
                        f"用戶最近 {pct:.0f}% 聽 {dominant} 類型歌（共{self.spotify_taste[user_id]['count']}首），分析心理狀態，要毒舌",
                        user_id, self.spotify_cooldowns, 300
                    )
                    if roast and roast != "COOLDOWN":
                        await channel.send(f"深度心理剖析 {after.mention}\n{roast}")

            # 隨機點評（20% 機率）
            if random.random() < 0.2:
                roast = await self.ask_kobe(
                    f"用戶正在聽 {new_spotify.title} - {new_spotify.artist}。用心理學分析品味。",
                    user_id, self.spotify_cooldowns, 180
                )
                if roast and roast != "COOLDOWN":
                    await channel.send(f"DJ Mamba 點評 {after.mention}\n{roast}")
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return
        user_id = after.id
        channel = self.get_text_channel(after.guild)
        if not channel: return

        # 遊戲監控
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game and not old_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time(), "1h_warned": False, "2h_warned": False}
            prompt = f"用戶開始玩 {new_game}。" + ("痛罵他玩2K是垃圾" if "2k" in new_game.lower() else "罵他不去訓練")
            roast = await self.ask_kobe(prompt, user_id, self.ai_roast_cooldowns, 300)
            msg = roast if roast and roast != "ERROR" else f"玩 {new_game}？去訓練！"
            await channel.send(f"{after.mention} {msg}")

        elif old_game and not new_game and user_id in self.active_sessions:
            session = self.active_sessions.pop(user_id, None)
            if session:
                duration = int(time.time() - session["start"])
                await self.save_to_db(user_id, old_game, duration)
                if duration > 600:
                    interview = await self.ask_kobe(f"{after.display_name} 玩了 {duration//60} 分鐘 {old_game}。質問收穫。", user_id, self.ai_chat_cooldowns, 0)
                    if interview and interview != "COOLDOWN":
                        await channel.send(f"賽後採訪 {after.mention}\n{interview}")

        # Spotify 監控 + 長期心理分析
        new_spotify = next((a for a in after.activities if isinstance(a, discord.Spotify)), None)
        if new_spotify:
            now = time.time()
            if now - self.last_music_processed.get(user_id, 0) < 10: return
            self.last_music_processed[user_id] = now

            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO music_history (user_id, title, artist, timestamp) VALUES (?, ?, ?, ?)",
                                 (user_id, new_spotify.title, new_spotify.artist, now))
                await db.commit()

            # 情緒分類
            title_art = (new_spotify.title + " " + new_spotify.artist).lower()
            mood_map = {
                "sad": ["哭", "雨", "分手", "夜", "slow", "ballad", "lonely"],
                "angry": ["fuck", "shit", "rage", "恨", "幹"],
                "chill": ["lofi", "chill", "relax", "study"],
                "hype": ["gym", "workout", "rap", "rock", "pump"]
            }
            detected = "neutral"
            for mood, keywords in mood_map.items():
                if any(k in title_art for k in keywords):
                    detected = mood
                    break

            # 長期記憶
            self.spotify_taste.setdefault(user_id, {"count": 0, "moods": {}})
            self.spotify_taste[user_id]["count"] += 1
            self.spotify_taste[user_id]["moods"][detected] = self.spotify_taste[user_id]["moods"].get(detected, 0) + 1

            # 每15首深度分析一次
            if self.spotify_taste[user_id]["count"] % 15 == 0:
                total = sum(self.spotify_taste[user_id]["moods"].values())
                dominant = max(self.spotify_taste[user_id]["moods"], key=self.spotify_taste[user_id]["moods"].get)
                pct = self.spotify_taste[user_id]["moods"][dominant] / total * 100
                if pct > 65:
                    roast = await self.ask_kobe(
                        f"用戶最近 {pct:.0f}% 聽 {dominant} 類型歌（共{self.spotify_taste[user_id]['count']}首），分析心理狀態，要毒舌",
                        user_id, self.spotify_cooldowns, 300
                    )
                    if roast and roast != "COOLDOWN":
                        await channel.send(f"深度心理剖析 {after.mention}\n{roast}")

            # 隨機點評（20% 機率）
            if random.random() < 0.2:
                roast = await self.ask_kobe(
                    f"用戶正在聽 {new_spotify.title} - {new_spotify.artist}。用心理學分析品味。",
                    user_id, self.spotify_cooldowns, 180
                )
                if roast and roast != "COOLDOWN":
                    await channel.send(f"DJ Mamba 點評 {after.mention}\n{roast}")
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith('!') or message.id in self.processed_msg_ids:
            if message.id not in self.processed_msg_ids:
                self.processed_msg_ids.append(message.id)
            return
        self.processed_msg_ids.append(message.id)
        user_id = message.author.id
        content = message.content.strip()
        lower = content.lower()

        # 記錄聊天 + 每日詞頻統計
        if len(content) > 0:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)", (user_id, content, time.time()))
                if random.random() < 0.05:
                    limit_time = time.time() - 86400
                    await db.execute("DELETE FROM chat_logs WHERE timestamp < ?", (limit_time,))
                await db.commit()
            self.daily_word_count[user_id] = self.daily_word_count.get(user_id, "") + " " + content

            # 黑歷史候選
            if any(w in lower for w in self.weak_words + ["廢", "爛", "不行", "放棄"]) or len(content) < 6:
                if random.random() < 0.1:
                    async with aiosqlite.connect(self.db_name) as db:
                        await db.execute("INSERT INTO chat_logs (user_id, content, timestamp) VALUES (?, ?, ?)",
                                       (user_id, "[黑歷史]" + content, time.time()))

        # 無視傳球檢查（ghosting）
        if user_id in self.pending_replies:
            self.pending_replies.pop(user_id, None)
        if message.mentions:
            for member in message.mentions:
                if not member.bot and member.status == discord.Status.online and member.id != user_id:
                    self.pending_replies[member.id] = {'time': time.time(), 'channel': message.channel, 'mention_by': message.author}

        # 廢話偵測 + 加分
        for word in self.nonsense_words:
            if word in lower:
                async with aiosqlite.connect(self.db_name) as db:
                    await db.execute("INSERT OR IGNORE INTO nonsense_stats (user_id, count) VALUES (?, 0)", (user_id,))
                    await db.execute("UPDATE nonsense_stats SET count = count + 1 WHERE user_id = ?", (user_id,))
                    await db.commit()
                break

        # 隨機加表情
        if random.random() < 0.3:
            emojis = ["FIRE", "BASKETBALL", "SNAKE", "FLEXED_BICEPS", "CLOWN", "POOP", "SKULL", "EYES"]
            try:
                await message.add_reaction(random.choice(emojis))
            except:
                pass

        # 說累自動 @ 最廢的人
        if any(w in lower for w in ["好累", "想睡", "睡了", "累死", "沒力", "廢了", "好睏"]):
            today = datetime.now().strftime("%Y-%m-%d")
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute("SELECT user_id, seconds FROM playtime WHERE last_played = ? ORDER BY seconds DESC LIMIT 1", (today,))
                row = await cursor.fetchone()
            if row and row[0] != user_id:
                loser = self.bot.get_user(row[0])
                if loser:
                    hours = row[1] // 3600
                    mins = (row[1] % 3600) // 60
                    await message.reply(f"{loser.mention} 你今天已經玩了 {hours}小時{mins}分還敢說累？\n你才是最廢的那個")

        # 優先圖片分析
        has_image = message.attachments and any(att.content_type and att.content_type.startswith("image/") for att in message.attachments)
        if has_image:
            if self.bot.user in message.mentions or random.random() < 0.1:
                async with message.channel.typing():
                    reply = await self.analyze_image(message.attachments[0].url, user_id)
                    await message.reply(reply)
            return

        # 優先 Tag / 問號 → AI 回覆
        is_question = content.endswith(("?", "QUESTION_MARK")) and len(content) > 1
        is_mentioned = self.bot.user in message.mentions
        if is_mentioned or is_question:
            if is_mentioned:
                clean_text = content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
                if not clean_text and not is_question: return
            async with message.channel.typing():
                reply = await self.ask_kobe(content, user_id, self.ai_chat_cooldowns, 3, use_memory=True)
                if reply == "COOLDOWN":
                    await message.add_reaction("CLOCK")
                elif reply and "ERROR" not in reply:
                    await message.reply(reply)
            return

        # 負能量 / 毒舌
        has_toxic = any(w in lower for w in self.toxic_words)
        if has_toxic:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"用戶說：'{content}'。散播失敗主義。狠狠罵他。", user_id, self.toxic_cooldowns, 30)
                if roast and "ERROR" not in roast and roast != "COOLDOWN":
                    await message.reply(roast)
            return

        # 細節糾察
        if len(content) > 10 and random.random() < 0.2:
            async with message.channel.typing():
                roast = await self.ask_kobe(f"檢查這句話有無錯字邏輯：'{content}'。若無錯回傳 PASS。", user_id, self.detail_cooldowns, 60)
                if roast and "PASS" not in roast and "ERROR" not in roast and roast != "COOLDOWN":
                    await message.reply(f"細節糾察\n{roast}")
            return

        # 弱者關鍵字
        has_weak = any(w in lower for w in self.weak_words)
        if has_weak:
            await message.channel.send(f"{message.author.mention} 累了？軟蛋！")
            await self.update_daily_stats(user_id, "lazy_points", 2)

        await self.bot.process_commands(message)
    # ==================== 資料庫工具函式 ====================
    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                INSERT INTO playtime (user_id, game_name, seconds, last_played) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, game_name) DO UPDATE SET
                seconds = seconds + excluded.seconds,
                last_played = excluded.last_played
            ''', (user_id, game_name, seconds, today))
            await db.commit()

    async def update_daily_stats(self, user_id, column, value):
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT 1 FROM daily_stats WHERE user_id = ?", (user_id,))
            if not await cursor.fetchone():
                await db.execute("INSERT INTO daily_stats (user_id, last_updated) VALUES (?, ?)", (user_id, today))
            await db.execute(f"UPDATE daily_stats SET {column} = {column} + ? WHERE user_id = ?", (value, user_id))
            await db.commit()

    async def add_honor(self, user_id, amount):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT OR IGNORE INTO honor (user_id, points) VALUES (?, 0)", (user_id,))
            await db.execute("UPDATE honor SET points = points + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    # ==================== Ghost Check（無視傳球 10 分鐘處刑）===================
    @tasks.loop(minutes=1)
    async def ghost_check(self):
        now = time.time()
        for uid, data in list(self.pending_replies.items()):
            if now - data['time'] > 1800:  # 30分鐘自動清除
                self.pending_replies.pop(uid, None)
                continue
            if now - data['time'] > 600:  # 10分鐘未回
                channel = data['channel']
                if not channel: 
                    self.pending_replies.pop(uid, None)
                    continue
                member = channel.guild.get_member(uid)
                if member and member.status == discord.Status.online:
                    roast = await self.ask_kobe(
                        f"{data['mention_by'].display_name} 傳球給 {member.display_name} 10分鐘沒回，罵他",
                        uid, {}, 0
                    )
                    if roast:
                        await channel.send(f"無視傳球 10 分鐘 {member.mention}\n{roast}")
                        await self.update_daily_stats(uid, "lazy_points", 5)
                self.pending_replies.pop(uid, None)

    # ==================== 遊戲時長警告（1小時 / 2小時）===================
    @tasks.loop(minutes=1)
    async def game_check(self):
        now = time.time()
        for user_id, session in list(self.active_sessions.items()):
            duration = int(now - session["start"])
            if duration >= 3600 and not session.get("1h_warned"):
                session["1h_warned"] = True
                await self.send_warning(user_id, session["game"], "1小時", 5)
            if duration >= 7200 and not session.get("2h_warned"):
                session["2h_warned"] = True
                await self.send_warning(user_id, session["game"], "2小時", 10)

    async def send_warning(self, user_id, game, time_str, penalty):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild: return
        member = guild.get_member(user_id)
        channel = self.get_text_channel(guild)
        if not member or not channel: return

        roast = await self.ask_kobe(f"用戶玩 {game} 超過 {time_str}，罵他眼睛瞎了嗎", user_id, self.ai_roast_cooldowns, 300)
        if roast and roast != "COOLDOWN":
            await channel.send(f"{time_str} 警報 {member.mention}\n{roast}")
            await self.update_daily_stats(user_id, "lazy_points", penalty)
        # ==================== 自動任務區 ====================

    @tasks.loop(hours=24)
    async def daily_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        if getattr(self, '_daily_executed', None) == today_str:
            return
        if now.hour == 23 and now.minute >= 50:
            self._daily_executed = today_str
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return

            async with aiosqlite.connect(self.db_name) as db:
                limit = time.time() - 86400
                cursor = await db.execute("SELECT user_id, content FROM chat_logs WHERE timestamp > ? ORDER BY RANDOM() LIMIT 30", (limit,))
                chat_rows = await cursor.fetchall()
                cursor = await db.execute("SELECT user_id, lazy_points FROM daily_stats ORDER BY lazy_points DESC LIMIT 5")
                lazy_rows = await cursor.fetchall()

            report = []
            for uid, points in lazy_rows:
                m = self.bot.get_user(uid)
                name = m.display_name if m else f"用戶{uid}"
                report.append(f"{name}: {points} 懶惰點")

            chat_sample = "\n".join([c for _, c in chat_rows[:10]]) if chat_rows else "今天很安靜"

            prompt = f"今日懶惰榜：{' | '.join(report)}\n今日聊天片段：\n{chat_sample}\n請用 Kobe Bryant 的語氣寫一篇毒舌日報，結尾帶蛇死"
            news = await self.ask_kobe(prompt, None, {}, 0)
            if not news or "⚠️" in news:
                news = f"今日最廢物榜：{'、'.join([r.split(':')[0] for r in report])}\n你們讓我失望。蛇死"

            embed = discord.Embed(title="曼巴日報", description=news, color=0xe74c3c)
            await channel.send(embed=embed)

            # 清空每日統計
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("DELETE FROM daily_stats")
                await db.commit()

    @tasks.loop(hours=1)
    async def weekly_tasks(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.weekday() == 6 and 20 <= now.hour < 21:
            today_str = now.strftime("%Y-%m-%d")
            if getattr(self, '_weekly_executed', None) == today_str:
                return
            self._weekly_executed = today_str

            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel: return

            # 本週廢話王
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute("SELECT user_id, count FROM nonsense_stats ORDER BY count DESC LIMIT 1")
                row = await cursor.fetchone()
                if row:
                    user = self.bot.get_user(row[0])
                    name = user.display_name if user else "神秘廢物"
                    await channel.send(f"本週廢話王：{user.mention if user else name}（{row[1]} 次廢話）\nKobe: 你的存在就是噪音。蛇")
                    await db.execute("DELETE FROM nonsense_stats")
                    await db.commit()

            # 投票 + 最爛歌單（可選）
            embed = discord.Embed(title="本週最廢表情投票", color=0xffd700)
            embed.description = "1️⃣ 2️⃣ 3️⃣ 4️⃣"
            msg = await channel.send(embed=embed)
            for e in ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]:
                await msg.add_reaction(e)

    @tasks.loop(minutes=1)
    async def morning_execution(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        today_str = now.strftime("%Y-%m-%d")
        if getattr(self, '_morning_executed', None) == today_str:
            return
        if now.hour == 8 and now.minute == 0:
            self._morning_executed = today_str
            guild = self.bot.guilds[0] if self.bot.guilds else None
            if not guild: return
            channel = self.get_text_channel(guild)
            if not channel: return

            sleeping = [m for m in guild.members if not m.bot and m.status == discord.Status.offline]
            if not sleeping: return

            names = "、".join(m.display_name for m in sleeping[:10])
            prompt = f"早上8點還有 {len(sleeping)} 個廢物在睡，包括 {names}，用最毒的方式把他們罵醒，結尾帶蛇死"
            roast = await self.ask_kobe(prompt, None, {}, 0)
            msg = roast or f"8點了還在睡？{' '.join(m.mention for m in sleeping[:20])}\n給我起來訓練！蛇死"

            embed = discord.Embed(title="08:00 起床氣處刑名單", description=msg, color=0xff0000)
            embed.set_footer(text="Mamba 在凌晨4點就醒了。你呢？")
            await channel.send(embed=embed)

    # ==================== 每日意志測驗（09:00）===================
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

        self.pending_daily_answer = {m.id for m in guild.members if not m.bot}
        self.daily_question_channel = channel
        self.daily_question_msg_id = None

        embed = discord.Embed(title="【每日曼巴意志測驗】", color=0x000000)
        embed.description = "**今天你要變強還是繼續當廢物？**\n\n1️⃣ 變強　　2️⃣ 當廢物\n\n60 秒內不回 → +10 懶惰點"
        embed.set_footer(text="Mamba is watching")

        try:
            msg = await channel.send("@everyone", embed=embed)
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")
            self.daily_question_msg_id = msg.id

            async def execution():
                await asyncio.sleep(68)
                if self.daily_question_msg_id != msg.id: return
                losers = [guild.get_member(uid) for uid in self.pending_daily_answer if guild.get_member(uid)]
                if losers:
                    mentions = " ".join(m.mention for m in losers[:20]) if len(losers) <= 20 else f"{len(losers)}名廢物"
                    roast = await self.ask_kobe(f"這{len(losers)}人沒回答每日一問，極兇罵醒，結尾蛇死", None, {}, 0)
                    await channel.send(f"【意志力處刑】 {mentions}\n{roast or '廢物就是廢物。蛇死'}")
                    for m in losers:
                        await self.update_daily_stats(m.id, "lazy_points", 10)
                self.pending_daily_answer.clear()
                self.daily_question_msg_id = None
            self.bot.loop.create_task(execution())
        except Exception as e:
            logger.error(f"每日一問失敗: {e}")

    # ==================== 情緒雷達 + 深夜戰報 + before_loop ====================
      @tasks.loop(minutes=15)
    async def mood_radar(self):
        guild = self.bot.guilds[0] if self.bot.guilds else None
        if not guild:
            return
        
        channel = self.get_text_channel(guild)
        if not channel:
            return

        async with aiosqlite.connect(self.db_name) as db:
            limit = time.time() - 3600
            cursor = await db.execute(
                "SELECT content FROM chat_logs WHERE timestamp > ? ORDER BY id DESC LIMIT 25",
                (limit,)
            )
            rows = await cursor.fetchall()

        if len(rows) < 8:
            return

        text = " | ".join(r[0] for r in rows)
        mood = await self.ask_kobe(
            f"用一個詞總結這25句話情緒：開心/低落/嗨/憤怒/正常\n內容：{text}",
            None, {}, 0
        )
        if not mood:
            return

        if any(w in mood for w in ["低落", "難過", "累"]):
            await channel.send("https://youtu.be/V2v5ZsoR1Mk")
            await channel.send("「You don't get better sitting on the bench.」蛇")
        elif any(w in mood for w in ["嗨", "瘋", "笑死", "哈哈"]):
            await channel.send("『你們這叫興奮？我叫這幼稚。去訓練。』死")
    @tasks.loop(hours=24)
    async def daily_summary_and_memory(self):
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        if now.hour == 0 and now.minute < 10:
            today = now.strftime("%Y-%m-%d")
            if self.last_daily_summary == today: return
            self.last_daily_summary = today
            channel = self.get_text_channel(self.bot.guilds[0]) if self.bot.guilds else None
            if not channel or not self.daily_word_count: return

            all_text = " ".join(self.daily_word_count.values())
            top5 = Counter(all_text.split()).most_common(5)
            words = "、".join(f"{w}({c}次)" for w,c in top5)

            embed = discord.Embed(title="曼巴深夜戰報", color=0x000000)
            embed.description = f"今日最常出現的詞：{words}\n\nMamba never sleeps. 你呢？蛇"
            await channel.send(embed=embed)
            self.daily_word_count.clear()

    # ==================== 所有 before_loop（防崩潰必備）===================
    @morning_4am_check.before_loop
    @daily_mamba_question.before_loop
    @mood_radar.before_loop
    @daily_summary_and_memory.before_loop
    @game_check.before_loop
    @daily_tasks.before_loop
    @weekly_tasks.before_loop
    @ghost_check.before_loop
    @morning_execution.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Game(bot))




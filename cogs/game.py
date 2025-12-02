import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime, timedelta
import random
import asyncio

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} 
        self.db_name = "game_stats.db"
        
        # 針對遊戲的罵人清單
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，去努力工作吧！",
            "grand theft auto": "還在 GTA？除了偷車你還會什麼？",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？",
            "league of legends": "又在打 LOL？💀 你的心態炸裂了嗎？",
            "valorant": "特戰英豪？槍法再準，現實生活打不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！"
        }
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS playtime (user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE)')
            await db.execute('CREATE TABLE IF NOT EXISTS economy (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, last_daily_claim DATE)')
            await db.commit()

    # --- 遊戲偵測邏輯 (包含語音突襲) ---
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # 結束舊遊戲 (存檔)
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # 開始新遊戲 (罵人 + 語音突襲)
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 1. 準備罵人的話
            game_lower = new_game.lower()
            roast_content = next((text for kw, text in self.targeted_roasts.items() if kw in game_lower), None)
            if not roast_content:
                roast_content = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
            else:
                # 如果是特定遊戲，加上 Tag
                roast_content = f"{after.mention} {roast_content}"

            # 2. 尋找文字頻道發送
            target_names = ["chat", "general", "聊天", "公頻", "主頻道"]
            text_channel = discord.utils.find(lambda c: any(t in c.name.lower() for t in target_names) and c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            if not text_channel:
                text_channel = discord.utils.find(lambda c: c.permissions_for(after.guild.me).send_messages, after.guild.text_channels)
            
            # 3. 🔥【語音突襲邏輯】🔥
            # 檢查該使用者是否在語音頻道
            if after.voice and after.voice.channel:
                voice_channel = after.voice.channel
                
                # 機器人加入該頻道
                if after.guild.voice_client is None:
                    await voice_channel.connect()
                elif after.guild.voice_client.channel != voice_channel:
                    await after.guild.voice_client.move_to(voice_channel)
                
                # 在文字頻道發送 TTS (文字轉語音) 訊息
                # 這樣所有在語音裡的人都會聽到機器人唸這句話
                if text_channel:
                    # 為了讓 TTS 唸起來順一點，稍微修飾一下語句
                    tts_msg = f"喂！{after.display_name}！我進來是為了告訴你，你在語音裡面玩 {new_game} 的聲音太吵了！專心一點！"
                    await text_channel.send(tts_msg, tts=True)
                    
                    # 同時發送原本的文字版罵人 (不唸出來，單純文字)
                    await text_channel.send(f"🎙️ **語音查哨中...** {roast_content}")
            else:
                # 如果不在語音，就只發普通文字罵人
                if text_channel:
                    await text_channel.send(roast_content)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # --- 💰 經濟指令 ---
    @commands.command()
    async def wallet(self, ctx):
        try:
            user_id = ctx.author.id
            today_str = datetime.now().strftime('%Y-%m-%d')
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("INSERT OR IGNORE INTO economy (user_id, balance) VALUES (?, 0)", (user_id,))
                await db.commit()

                cursor = await db.execute("SELECT balance, last_daily_claim FROM economy WHERE user_id = ?", (user_id,))
                row = await cursor.fetchone()
                balance = row[0]
                last_claim = row[1]

                msg = f"💰 **{ctx.author.display_name} 的錢包**\n目前餘額：`{balance}` 曼巴幣\n"

                if last_claim != today_str:
                    cursor = await db.execute("SELECT SUM(seconds) FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, yesterday_str))
                    play_row = await cursor.fetchone()
                    yesterday_seconds = play_row[0] if play_row[0] else 0
                    
                    if yesterday_seconds < 3600:
                        new_balance = balance + 10
                        await db.execute("UPDATE economy SET balance = ?, last_daily_claim = ? WHERE user_id = ?", (new_balance, today_str, user_id))
                        msg += f"\n🎁 **每日結算：** 昨天很自律！獎勵 `+10` 幣！"
                    else:
                        await db.execute("UPDATE economy SET last_daily_claim = ? WHERE user_id = ?", (today_str, user_id))
                        msg += f"\n❌ **每日結算：** 昨天玩太久了，沒收獎勵！"
                    await db.commit()
                else:
                    msg += "\n✅ 今日已結算。"
                
                await ctx.send(msg)
        except Exception as e:
            print(f"Wallet error: {e}")
            await ctx.send(f"❌ 錢包壞掉了：`{e}`")

    # --- 🛍️ 商店指令 (已補齊) ---
    @commands.command()
    async def buy(self, ctx, item: str = None, target: discord.Member = None):
        if not item:
            embed = discord.Embed(title="🛒 曼巴雜貨店", color=0x00ff00)
            embed.add_field(name="`!buy roast @人` (5幣)", value="花錢請機器人罵他。", inline=False)
            embed.add_field(name="`!buy pardon` (20幣)", value="消除今日遊戲紀錄。", inline=False)
            embed.add_field(name="`!buy rename @人` (50幣)", value="幫對方改羞恥暱稱。", inline=False)
            await ctx.send(embed=embed)
            return

        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            balance = row[0] if row else 0

            # 購買 Roast
            if item == "roast":
                cost = 5
                if not target or balance < cost: return await ctx.send("❌ 錢不夠或沒標記人！")
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()
                roasts = [f"喂 {target.mention}！有人花錢叫我罵你：你是軟蛋！", f"{target.mention}，如果你把打遊戲的時間拿來練球，早就進 NBA 了！"]
                await ctx.send(random.choice(roasts))

            # 購買 Pardon
            elif item == "pardon":
                cost = 20
                if balance < cost: return await ctx.send("❌ 錢不夠！")
                today_str = datetime.now().strftime('%Y-%m-%d')
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.execute("DELETE FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, today_str))
                await db.commit()
                await ctx.send(f"💸 {ctx.author.mention} 買通了裁判，今日紀錄已銷毀！")

            # 購買 Rename
            elif item == "rename":
                cost = 50
                if not target or balance < cost: return await ctx.send("❌ 錢不夠或沒標記人！")
                if target.top_role >= ctx.guild.me.top_role: return await ctx.send("❌ 我無法改他的名 (權限不足)。")
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()
                names = ["我愛打鐵", "我是軟蛋", "20年老替補", "飲水機守護神"]
                try:
                    await target.edit(nick=random.choice(names))
                    await ctx.send(f"💸 交易成功！{target.mention} 被強制改名了！")
                except:
                    await ctx.send("❌ 改名失敗 (權限不足)，但錢已經扣了嘿嘿！")

    # --- 🔥 俄羅斯輪盤 ---
    @commands.command()
    async def roulette(self, ctx, amount: int):
        if amount <= 0: return await ctx.send("❌ 賭注要大於 0！")
        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row or row[0] < amount: return await ctx.send("❌ 錢不夠！")

            await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            await ctx.send(f"🔫 {ctx.author.mention} 轉動了左輪手槍...賭注 `{amount}`...")
            await asyncio.sleep(2)

            if random.randint(1, 6) == 6:
                await db.commit()
                await ctx.send(f"💥 **砰！** {ctx.author.mention} 倒下了！賭金全沒了！")
                if ctx.author.voice: 
                    await ctx.author.move_to(None)
                    await ctx.send("👻 (並被踢出語音)")
            else:
                win = int(amount * 2)
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (win, user_id))
                await db.commit()
                await ctx.send(f"💨 沒事！贏得 `{win}` 幣！")

    # --- 🦹 偷竊系統 ---
    @commands.command()
    async def steal(self, ctx, target: discord.Member):
        if target.bot or target == ctx.author: return await ctx.send("❌ 無效目標！")
        user_id, target_id, cost = ctx.author.id, target.id, 5
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row or row[0] < cost: return await ctx.send(f"❌ 手續費不足 `{cost}`！")
            
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (target_id,))
            t_row = await cursor.fetchone()
            if not t_row or t_row[0] <= 0: return await ctx.send("❌ 對方已經破產了！")

            await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
            
            if random.random() < 0.4: # 40% 成功
                steal_amt = int(t_row[0] * random.uniform(0.1, 0.3))
                if steal_amt < 1: steal_amt = 1
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (steal_amt, user_id))
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (steal_amt, target_id))
                await ctx.send(f"🦹 成功從 {target.mention} 偷走 `{steal_amt}` 幣！")
            else:
                fine = 20
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (fine, user_id))
                await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (fine, target_id))
                await ctx.send(f"👮 失敗！被罰款 `{fine}` 幣給對方！")
            await db.commit()

    # --- 🏀 1 on 1 單挑 ---
    @commands.command()
    async def duel(self, ctx, target: discord.Member, amount: int):
        if target.bot or target == ctx.author or amount <= 0: return await ctx.send("❌ 無效挑戰！")
        user_id, target_id = ctx.author.id, target.id
        async with aiosqlite.connect(self.db_name) as db:
            # 簡化檢查餘額邏輯
            for uid in [user_id, target_id]:
                cur = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (uid,))
                row = await cur.fetchone()
                if not row or row[0] < amount: return await ctx.send(f"❌ 雙方有人錢不夠！")

        await ctx.send(f"🏀 {ctx.author.mention} 挑戰 {target.mention}！賭金 `{amount}`。\n請輸入 `accept` 接受或 `refuse` 拒絕。")
        try:
            msg = await self.bot.wait_for('message', check=lambda m: m.author == target and m.content.lower() in ['accept', 'refuse'], timeout=30.0)
            if msg.content.lower() == 'refuse': return await ctx.send(f"👎 {target.mention} 拒絕了。")
            
            await ctx.send("🏀 比賽開始...")
            await asyncio.sleep(2)
            s1, s2 = random.randint(0, 100), random.randint(0, 100)
            while s1 == s2: s1, s2 = random.randint(0, 100), random.randint(0, 100)
            
            result = f"📊 {ctx.author.name} {s1} : {s2} {target.name}\n"
            async with aiosqlite.connect(self.db_name) as db:
                if s1 > s2:
                    await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, target_id))
                    result += f"🏆 {ctx.author.mention} 獲勝！"
                else:
                    await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
                    await db.execute("UPDATE economy SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
                    result += f"🏆 {target.mention} 獲勝！"
                await db.commit()
            await ctx.send(result)
        except asyncio.TimeoutError:
            await ctx.send("⏳ 比賽取消。")

    # --- 📊 Rank 指令 ---
    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id')
                rows = await cursor.fetchall()
                stats = {row[0]: row[1] for row in rows}
                
                # 加入正在玩的即時時間
                current_time = time.time()
                for uid, session in self.active_sessions.items():
                    stats[uid] = stats.get(uid, 0) + int(current_time - session['start'])
                
                sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
                if not sorted_stats: return await ctx.send("📊 資料庫空空如也！")

                embed = discord.Embed(title="🏆 偷懶排行榜 (即時)", color=0xffd700)
                text = ""
                for idx, (uid, sec) in enumerate(sorted_stats):
                    m = ctx.guild.get_member(uid)
                    name = m.display_name if m else f"用戶({uid})"
                    status = "🎮" if uid in self.active_sessions else ""
                    text += f"{idx+1}. **{name}** {status}: {sec//3600}小時 {(sec%3600)//60}分\n"
                embed.add_field(name="名單", value=text)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(Game(bot))

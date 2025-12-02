import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime, timedelta
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} 
        self.db_name = "game_stats.db"
        
        # 針對遊戲的罵人清單
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，這裡是現實世界！快去努力工作！",
            "nba": "玩 NBA 2K？🏀 手指動得比腳快有什麼用？去球場流汗！",
            "league of legends": "又在打 LOL？💀 心態炸裂了嗎？關掉它！",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！別再抽卡了！"
        }
        
        # 通用罵人清單
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            # 1. 遊戲時間表
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE
                )
            ''')
            # 2. 經濟系統表 (記錄錢包餘額 + 上次領獎勵的時間)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS economy (
                    user_id INTEGER PRIMARY KEY, 
                    balance INTEGER DEFAULT 0,
                    last_daily_claim DATE
                )
            ''')
            await db.commit()

    # --- 遊戲偵測邏輯 (保持不變，已優化偵測) ---
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        if new_game == old_game: return

        # 結束舊遊戲
        if old_game:
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    del self.active_sessions[user_id]

        # 開始新遊戲
        if new_game:
            self.active_sessions[user_id] = {"game": new_game, "start": time.time()}
            
            # 發送罵人訊息
            channel = after.guild.system_channel
            if not channel:
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c; break
            
            if channel:
                game_lower = new_game.lower()
                msg = None
                for kw, text in self.targeted_roasts.items():
                    if kw in game_lower:
                        msg = f"{after.mention} {text}"; break
                if not msg:
                    msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                await channel.send(msg)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    # --- 💰 曼巴經濟系統指令 ---

    # 1. 查詢錢包 & 領取每日獎勵
    @commands.command()
    async def wallet(self, ctx):
        user_id = ctx.author.id
        today_str = datetime.now().strftime('%Y-%m-%d')
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        async with aiosqlite.connect(self.db_name) as db:
            # 取得目前餘額與上次領獎時間
            cursor = await db.execute("SELECT balance, last_daily_claim FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            
            balance = row[0] if row else 0
            last_claim = row[1] if row else None

            msg = f"💰 **{ctx.author.display_name} 的錢包**\n目前餘額：`{balance}` 曼巴幣\n"

            # --- 判斷是否可以領每日獎勵 ---
            if last_claim != today_str:
                # 檢查昨天的遊戲時間
                cursor = await db.execute("SELECT SUM(seconds) FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, yesterday_str))
                play_row = await cursor.fetchone()
                yesterday_seconds = play_row[0] if play_row[0] else 0
                
                # 如果昨天玩少於 1 小時 (3600秒)
                if yesterday_seconds < 3600:
                    reward = 10
                    new_balance = balance + reward
                    
                    # 更新資料庫
                    if row:
                        await db.execute("UPDATE economy SET balance = ?, last_daily_claim = ? WHERE user_id = ?", (new_balance, today_str, user_id))
                    else:
                        await db.execute("INSERT INTO economy (user_id, balance, last_daily_claim) VALUES (?, ?, ?)", (reward, today_str, user_id))
                    
                    await db.commit()
                    msg += f"\n🎁 **每日結算：** 昨天你很自律 (玩遊戲 < 1小時)！\n獲得獎勵：`+10` 曼巴幣 (目前: {new_balance})"
                else:
                    # 昨天玩太久，沒獎勵，但也更新領取狀態以免重複檢查
                    hours = yesterday_seconds // 3600
                    if row:
                        await db.execute("UPDATE economy SET last_daily_claim = ? WHERE user_id = ?", (today_str, user_id))
                    else:
                        await db.execute("INSERT INTO economy (user_id, balance, last_daily_claim) VALUES (?, ?, ?)", (0, today_str, user_id))
                    await db.commit()
                    msg += f"\n❌ **每日結算：** 昨天你玩了 {hours} 小時的遊戲！沒有獎勵！🤬"
            else:
                msg += "\n✅ 今日獎勵已結算過。"
            
            await ctx.send(msg)

    # 2. 商店系統 (!buy)
    @commands.command()
    async def buy(self, ctx, item: str = None, target: discord.Member = None):
        if not item:
            embed = discord.Embed(title="🛒 曼巴雜貨店", color=0x00ff00)
            embed.add_field(name="`!buy roast @人` (5幣)", value="花錢請機器人狠狠罵他一頓。", inline=False)
            embed.add_field(name="`!buy pardon` (20幣)", value="消除自己 **今天** 的所有遊戲紀錄 (買通裁判)。", inline=False)
            embed.add_field(name="`!buy rename @人` (50幣)", value="強制幫對方改一個羞恥暱稱 (需機器人有權限)。", inline=False)
            await ctx.send(embed=embed)
            return

        user_id = ctx.author.id
        async with aiosqlite.connect(self.db_name) as db:
            # 檢查餘額
            cursor = await db.execute("SELECT balance FROM economy WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            balance = row[0] if row else 0

            # --- 商品 1: Roast (罵人) ---
            if item == "roast":
                cost = 5
                if not target:
                    await ctx.send("你要罵誰？請標記他！範例：`!buy roast @小明`")
                    return
                if balance < cost:
                    await ctx.send(f"❌ 餘額不足！你需要 {cost} 幣。")
                    return
                
                # 扣款
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()
                
                # 執行罵人
                roasts = [
                    f"喂 {target.mention}！有人花錢要我告訴你：你打球像蔡徐坤！",
                    f"{target.mention}，聽說你最近很囂張？也不照照鏡子！",
                    f"{target.mention}，如果你把打遊戲的時間拿來練球，早就進 NBA 了，廢物！"
                ]
                await ctx.send(f"💸 交易成功！(餘額剩 {balance - cost})")
                await ctx.send(random.choice(roasts))

            # --- 商品 2: Pardon (消除紀錄) ---
            elif item == "pardon":
                cost = 20
                if balance < cost:
                    await ctx.send(f"❌ 餘額不足！你需要 {cost} 幣。")
                    return
                
                # 扣款並刪除今日紀錄
                today_str = datetime.now().strftime('%Y-%m-%d')
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.execute("DELETE FROM playtime WHERE user_id = ? AND last_played = ?", (user_id, today_str))
                await db.commit()
                
                await ctx.send(f"💸 **裁判已被買通！**\n{ctx.author.mention} 今天的所有遊戲時長紀錄已銷毀... 噓！🤫")

            # --- 商品 3: Rename (改名) ---
            elif item == "rename":
                cost = 50
                if not target:
                    await ctx.send("你要改誰的名？範例：`!buy rename @小明`")
                    return
                if balance < cost:
                    await ctx.send(f"❌ 餘額不足！你需要 {cost} 幣。")
                    return
                
                # 檢查權限
                if not ctx.guild.me.guild_permissions.manage_nicknames:
                    await ctx.send("❌ 機器人沒有「管理暱稱」權限，無法執行！(錢沒扣)")
                    return
                if target.top_role >= ctx.guild.me.top_role:
                    await ctx.send("❌ 我無法修改該成員的暱稱 (他的權限比我高或跟我一樣)。")
                    return

                # 扣款
                await db.execute("UPDATE economy SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
                await db.commit()

                # 執行改名
                shameful_names = ["我愛打鐵", "我是軟蛋", "躺分仔", "飲水機守護神", "20年老替補"]
                new_name = random.choice(shameful_names)
                try:
                    await target.edit(nick=new_name)
                    await ctx.send(f"💸 交易成功！\n**{target.name}** 的名字已經被改成 **「{new_name}」** 了！哈哈哈哈！")
                except Exception as e:
                    await ctx.send(f"改名失敗：{e}")

            else:
                await ctx.send("❌ 沒賣這個東西！請輸入 `!buy` 查看商品列表。")

    # 保留原本的 rank 指令...
    @commands.command()
    async def rank(self, ctx):
        # (這裡不需要改，用您原本的 rank 程式碼即可，或者用我上一篇優化過的)
        # 為節省篇幅，這裡預設保留上一篇的 rank 邏輯
        try:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute('SELECT user_id, SUM(seconds) as total FROM playtime GROUP BY user_id ORDER BY total DESC LIMIT 5')
                rows = await cursor.fetchall()
                if not rows:
                    await ctx.send("目前沒有紀錄！")
                    return
                embed = discord.Embed(title="🏆 偷懶排行榜", color=0xffd700)
                text = ""
                for idx, (uid, sec) in enumerate(rows):
                    m = ctx.guild.get_member(uid)
                    name = m.display_name if m else str(uid)
                    text += f"{idx+1}. **{name}**: {sec//3600}小時 {(sec%3600)//60}分\n"
                embed.add_field(name="名單", value=text)
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Rank Error: {e}")

async def setup(bot):
    await bot.add_cog(Game(bot))

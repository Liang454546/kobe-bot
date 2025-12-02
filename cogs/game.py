import discord
from discord.ext import commands
import aiosqlite
import time
from datetime import datetime
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_sessions = {} # 暫存：{user_id: {'game': '遊戲名', 'start': 時間戳記}}
        self.db_name = "game_stats.db"
        
        # --- 1. 針對特定遊戲的罵人清單 ---
        self.targeted_roasts = {
            "gta": "俠盜獵車手？🚗 這裡不是洛聖都，這裡是現實世界！快去努力工作！",
            "grand theft auto": "還在 Grand Theft Auto？除了偷車你還會什麼？去偷點時間來唸書吧！",
            "nba": "玩 NBA 2K？🏀 你手指動得比腳還快有什麼用？曼巴精神是去球場流汗，不是在螢幕前流口水！",
            "2k": "玩 2K 建球員？不如去建設你自己的人生！別再捏臉了！",
            "league of legends": "又在打 LOL？💀 你的心態炸裂了嗎？還是想讓隊友心態炸裂？關掉它！",
            "valorant": "特戰英豪？槍法再準，考試/工作射不中目標有什麼用？",
            "apex": "APEX？你的肝還好嗎？別再當滋崩狗了！",
            "原神": "啟動？😱 給我把書桌前的燈啟動！別再抽卡了，你的人生抽不到保底！"
        }

        # --- 2. 通用的隨機罵人清單 ---
        self.default_roasts = [
            "抓到了！{member} 竟然在玩 **{game}**！不用唸書/工作嗎？😡",
            "看到 {member} 在玩 **{game}**，曼巴精神去哪了？还不快去努力！🏀",
            "{member} 還有時間玩 **{game}**？凌晨四點的太陽看過了嗎？",
            "嗶嗶！裁判！{member} 在玩 **{game}** 犯規！直接驅逐出場去辦正事！",
            "這時候玩 **{game}**？你的競爭對手正在訓練呢！💪"
        ]

    async def cog_load(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS playtime (
                    user_id INTEGER, game_name TEXT, seconds INTEGER, last_played DATE
                )
            ''')
            await db.commit()

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if after.bot: return

        user_id = after.id

        # 取得遊戲名稱 (如果有的話)
        new_game = next((a.name for a in after.activities if a.type == discord.ActivityType.playing), None)
        old_game = next((a.name for a in before.activities if a.type == discord.ActivityType.playing), None)

        # 如果狀態完全沒變 (例如只是去聽個歌，但遊戲還開著)，就忽略
        if new_game == old_game:
            return

        # --- 邏輯修正：分開處理「結束舊的」與「開始新的」---

        # 1. 處理【結束舊遊戲】 (包含：完全停止玩，或是換成別的遊戲)
        if old_game:
            # 只有當舊遊戲與新遊戲不同時，才需要結算
            # (雖然上面已經擋掉了 same game，但雙重保險)
            if user_id in self.active_sessions:
                session = self.active_sessions[user_id]
                # 確保結算的是對應的遊戲
                if session["game"] == old_game:
                    duration = int(time.time() - session["start"])
                    await self.save_to_db(user_id, old_game, duration)
                    print(f"📝 {after.name} 結束了 {old_game} (玩了 {duration} 秒)")
                    # 移除記憶體中的暫存
                    del self.active_sessions[user_id]

        # 2. 處理【開始新遊戲】 (包含：從沒玩變成有玩，或是從 A 換到 B)
        if new_game:
            # 記錄開始時間
            self.active_sessions[user_id] = {
                "game": new_game,
                "start": time.time()
            }
            
            # --- 發送罵人訊息 (Roast) ---
            # 為了避免換遊戲時太吵，您可以考慮這裡要不要加個冷卻，目前是只要換遊戲就罵
            channel = after.guild.system_channel
            if not channel:
                for c in after.guild.text_channels:
                    if c.permissions_for(after.guild.me).send_messages:
                        channel = c
                        break
            
            if channel:
                game_name_lower = new_game.lower()
                roast_msg = None
                
                # 關鍵字對應
                for keyword, msg in self.targeted_roasts.items():
                    if keyword in game_name_lower:
                        roast_msg = f"{after.mention} {msg}"
                        break
                
                # 沒對應到就隨機
                if not roast_msg:
                    roast_msg = random.choice(self.default_roasts).format(member=after.mention, game=new_game)
                
                await channel.send(roast_msg)

    async def save_to_db(self, user_id, game_name, seconds):
        if seconds < 5: return # 防止誤觸，少於 5 秒不記錄
        today = datetime.now().strftime('%Y-%m-%d')
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("INSERT INTO playtime VALUES (?, ?, ?, ?)", (user_id, game_name, seconds, today))
            await db.commit()

    @commands.command()
    async def rank(self, ctx):
        try:
            async with aiosqlite.connect(self.db_name) as db:
                cursor = await db.execute('''
                    SELECT user_id, SUM(seconds) as total_time 
                    FROM playtime 
                    GROUP BY user_id 
                    ORDER BY total_time DESC 
                    LIMIT 10
                ''')
                rows = await cursor.fetchall()
                
                if not rows:
                    await ctx.send("📊 資料庫空空如也！目前還沒紀錄到任何人玩遊戲 (或是機器人剛醒來)。")
                    return

                embed = discord.Embed(
                    title="🏆 伺服器偷懶排行榜 (總時長)",
                    description="統計機器人上線以來的紀錄：",
                    color=0xffd700
                )

                rank_text = ""
                for index, row in enumerate(rows):
                    u_id, seconds = row
                    member = ctx.guild.get_member(u_id)
                    name = member.display_name if member else f"使用者({u_id})"
                    
                    # 時間換算
                    hours = seconds // 3600
                    mins = (seconds % 3600) // 60
                    
                    medal = "👑" if index == 0 else f"{index+1}."
                    rank_text += f"{medal} **{name}**\n╚ ⏳ {hours} 小時 {mins} 分鐘\n"
                
                embed.add_field(name="名單", value=rank_text, inline=False)
                
                # 顯示目前正在進行的遊戲 (額外資訊)
                if self.active_sessions:
                    current_playing = []
                    for uid, data in self.active_sessions.items():
                        m = ctx.guild.get_member(uid)
                        if m:
                            current_duration = int(time.time() - data['start']) // 60
                            current_playing.append(f"• **{m.display_name}** 正在玩 *{data['game']}* ({current_duration} 分鐘)")
                    
                    if current_playing:
                        embed.add_field(name="🔴 目前正在偷懶中...", value="\n".join(current_playing), inline=False)

                embed.set_footer(text="注意：正在進行中的遊戲時間，需等結束後才會計入排名！")
                await ctx.send(embed=embed)

        except Exception as e:
            print(f"Rank Error: {e}")
            await ctx.send(f"❌ 查詢失敗：{e}")

async def setup(bot):
    await bot.add_cog(Game(bot))

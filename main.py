import os
import discord
from discord import app_commands
from discord.ext import commands
import requests
from datetime import datetime, timezone, timedelta

# =========================================================
# ⚙️ SETTING & CONFIG
# =========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")

AUCTION_CHANNEL_ID = 1234567890123456789
AUCTION_CATEGORY_ID = 1234567890123456789

# 🔑 กำหนด ID ยศที่อนุญาตให้ใช้คำสั่งสำหรับประมูล (ผู้ทุบ)
ALLOWED_AUCTION_ROLES = [
    1512886281405862000,
    1512886112094523543,
    1512886215899222136
]

# 🔑 กำหนด ID ยศที่อนุญาตให้ใช้คำสั่งผู้ดูแล/แอดมิน
ALLOWED_ADMIN_ROLES = [
    1515425186323763230,
    1560690995601875064,
    1530829877576728577
]

ROLE_YELLOW_ID = 1526784433477259406
ROLE_ORANGE_ID = 1528019004713599186
ROLE_RED_ID    = 1535646215469924512

THAI_TZ = timezone(timedelta(hours=7))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  

bot = commands.Bot(command_prefix="!", intents=intents)

# ฟังก์ชันช่วยเช็กสิทธิ์ยศเฉพาะ หรือ แอดมิน
def check_staff_permission(interaction: discord.Interaction) -> bool:
    user_roles = [role.id for role in getattr(interaction.user, "roles", [])]
    has_role = any(role_id in ALLOWED_ADMIN_ROLES for role_id in user_roles)
    is_admin = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    return has_role or is_admin

# =========================================================
# 🔨 UI VIEWS & MODALS (Auction, Giveaway, Ticket)
# =========================================================
class SeparateAuctionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ทุบ", style=discord.ButtonStyle.danger, emoji="🔨", custom_id="separate_buyout_btn")
    async def buyout_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.guild.get_member(interaction.user.id) or interaction.user
        has_role = any(role.id in ALLOWED_AUCTION_ROLES for role in getattr(member, "roles", []))
        is_admin = member.guild_permissions.administrator if hasattr(member, "guild_permissions") else False

        if not has_role and not is_admin:
            await interaction.response.send_message("คุณต้องมีประวัติการจุติ 3-5 ขึ้นไปถึงจะกดทุบประมูลได้", ephemeral=True)
        else:
            button.disabled = True
            await interaction.message.edit(view=self)
            await interaction.response.send_message(f"🎉 **{member.mention}** ใช้สิทธิ์ **ทุบโต๊ะ** ชนะการประมูลรายการนี้ทันที!", ephemeral=False)

class SeparateAuctionModal(discord.ui.Modal, title="📝 กรอกรายละเอียดการลงประมูล"):
    item_name = discord.ui.TextInput(label="ชื่อสินค้า", placeholder="เช่น ดาบ Legend +9", required=True)
    prices = discord.ui.TextInput(label="ราคา (เปิด / บิดขั้นต่ำ / ทุบโต๊ะ)", placeholder="เช่น เปิด 100 / บิด 10 / ทุบ 500", required=True)
    close_time = discord.ui.TextInput(label="เวลาปิดประมูล", placeholder="เช่น 22:00 น.", required=True)
    image_url = discord.ui.TextInput(label="ลิงก์รูปภาพสินค้า (ถ้ามี)", placeholder="วาง URL หรือใส่ -", required=False, default="-")
    target_role_id = discord.ui.TextInput(label="ID ยศที่ต้องการแท็ก (ถ้ามี)", placeholder="ใส่ ID ยศ หรือใส่ -", required=False, default="-")

    async def on_submit(self, interaction: discord.Interaction):
        img_val = self.image_url.value.strip() if self.image_url.value else "-"
        role_val = self.target_role_id.value.strip() if self.target_role_id.value else "-"

        data = {
            "item_name": self.item_name.value,
            "prices": self.prices.value,
            "close_time": self.close_time.value,
            "image_url": img_val,
            "target_role_id": role_val
        }

        embed = discord.Embed(title="📩 คำขอลงประมูลใหม่ (รอแอดมินยืนยัน)", color=discord.Color.orange())
        embed.add_field(name="ผู้ขอลง", value=interaction.user.mention, inline=False)
        embed.add_field(name="ชื่อสินค้า", value=data["item_name"], inline=True)
        embed.add_field(name="ราคา (เปิด/บิด/ทุบ)", value=data["prices"], inline=True)
        embed.add_field(name="เวลาปิด", value=data["close_time"], inline=False)

        if data["image_url"] != "-" and data["image_url"].startswith("http"):
            embed.set_image(url=data["image_url"])

        view = AdminApproveSeparateView(data=data, seller=interaction.user)
        await interaction.response.send_message("✅ ส่งข้อมูลให้แอดมินตรวจสอบแล้ว กรุณารอแอดมินอนุมัติครับ", embed=embed, view=view)

class AdminApproveSeparateView(discord.ui.View):
    def __init__(self, data: dict, seller: discord.Member):
        super().__init__(timeout=None)
        self.data = data
        self.seller = seller

    @discord.ui.button(label="✅ อนุมัติการประมูล", style=discord.ButtonStyle.success, custom_id="approve_sep_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_staff_permission(interaction):
            await interaction.response.send_message("❌ เฉพาะยศผู้ดูแลที่ได้รับอนุญาตเท่านั้นที่กดอนุมัติได้", ephemeral=True)
            return

        await interaction.response.defer()
        guild = interaction.guild
        auction_channel = guild.get_channel(AUCTION_CHANNEL_ID)

        role_tag = f"<@&{self.data['target_role_id']}> " if self.data.get('target_role_id') and self.data['target_role_id'] != "-" else ""
        formatted_description = (
            f"// 「MsL Community┘\n\n"
            f"// ˖✦ **ชื่อสินค้า :** `{self.data['item_name']}`\n\n"
            f"// ˖✦ **รายละเอียดราคา :** `{self.data['prices']}`\n\n"
            f"// ˖✦ **เวลาปิด :** `{self.data['close_time']}`\n"
            f"-----------------------------------------\n"
            f"Tag : {role_tag}{self.seller.mention}"
        )

        embed = discord.Embed(description=formatted_description, color=discord.Color.from_rgb(47, 49, 54))
        if self.data.get('image_url') and self.data['image_url'] != "-" and self.data['image_url'].startswith("http"):
            embed.set_image(url=self.data['image_url'])

        if auction_channel:
            await auction_channel.send(embed=embed, view=SeparateAuctionView())

        category = guild.get_channel(AUCTION_CATEGORY_ID) if AUCTION_CATEGORY_ID != 0 else None
        clean_name = "".join(e for e in self.data['item_name'] if e.isalnum() or e in ("-", "_")).lower() or "auction"
        room_name = f"🟢-{clean_name}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.seller: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        new_room = await guild.create_text_channel(name=room_name, category=category, overwrites=overwrites)
        await new_room.send(content=f"{role_tag}{self.seller.mention}", embed=embed, view=SeparateAuctionView())

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(f"✅ อนุมัติเรียบร้อย! โพสต์รายการประมูลแล้ว และสร้างห้อง {new_room.mention} สำเร็จ!", ephemeral=False)

    @discord.ui.button(label="❌ ปฏิเสธ", style=discord.ButtonStyle.danger, custom_id="reject_sep_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_staff_permission(interaction):
            await interaction.response.send_message("❌ เฉพาะยศผู้ดูแลที่ได้รับอนุญาตเท่านั้นที่กดได้", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("❌ ปฏิเสธการลงประมูลรายการนี้เรียบร้อยแล้ว", ephemeral=False)

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = set()

    @discord.ui.button(label="เข้าร่วมกิจกรรม", style=discord.ButtonStyle.success, emoji="🎉", custom_id="giveaway_join_btn")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.participants:
            await interaction.response.send_message("❌ คุณได้เข้าร่วมกิจกรรมนี้ไปแล้ว!", ephemeral=True)
        else:
            self.participants.add(interaction.user.id)
            await interaction.response.send_message(f"✅ **{interaction.user.mention}** เข้าร่วมกิจกรรมเรียบร้อยแล้ว!", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 ปิด Ticket", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 กำลังลบห้องนี้ภายใน 5 วินาที...", ephemeral=False)
        try:
            await interaction.channel.delete(delay=5.0)
        except Exception:
            pass

class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 สร้าง Ticket แจ้งเรื่อง", style=discord.ButtonStyle.primary, custom_id="create_ticket_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        channel_name = f"ticket-{user.name}"
        
        existing_channel = discord.utils.get(guild.channels, name=channel_name)
        if existing_channel:
            await interaction.response.send_message(f"⚠️ คุณมีห้อง Ticket อยู่แล้วที่ {existing_channel.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
        embed = discord.Embed(
            title="📩 ระบบสนับสนุนสมาชิก (Ticket)",
            description=f"สวัสดีครับคุณ {user.mention}!\nทีมงานได้รับเรื่องของคุณแล้ว โปรดพิมพ์รายละเอียดหรือปัญหาที่ต้องการแจ้งทิ้งไว้ได้เลยครับ",
            color=discord.Color.blue()
        )
        embed.set_footer(text="เมื่อเสร็จสิ้นการสนทนา สามารถกดปุ่มด้านล่างเพื่อปิดห้องได้ครับ")
        await ticket_channel.send(content=f"{user.mention}", embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ สร้างห้อง Ticket เรียบร้อยแล้ว: {ticket_channel.mention}", ephemeral=True)

# =========================================================
# 💬 SLASH COMMANDS
# =========================================================
@bot.tree.command(name="auction", description="[Staff] เปิดแบบฟอร์มลงประมูลสินค้า")
async def auction_cmd(interaction: discord.Interaction):
    if not check_staff_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มียศที่ได้รับอนุญาตให้ใช้คำสั่งนี้!", ephemeral=True)
        return
    await interaction.response.send_modal(SeparateAuctionModal())

@bot.tree.command(name="warn", description="[Staff] ประกาศออกใบเตือนสมาชิกพร้อมยัดยศอัตโนมัติ")
@app_commands.describe(
    warn_type="เลือกระดับใบเตือน",
    user="สมาชิกที่ต้องการออกใบเตือน",
    reason="สาเหตุการออกใบเตือน",
    note="หมายเหตุเพิ่มเติม",
    action_by="ผู้ดำเนินการ"
)
@app_commands.choices(warn_type=[
    app_commands.Choice(name="🟨 ใบเหลือง", value="yellow"),
    app_commands.Choice(name="🟧 ใบส้ม", value="orange"),
    app_commands.Choice(name="🟥 ใบแดง", value="red")
])
async def warn(
    interaction: discord.Interaction,
    warn_type: app_commands.Choice[str],
    user: discord.Member,
    reason: str,
    note: str = "-",
    action_by: discord.Member = None
):
    if not check_staff_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มียศที่ได้รับอนุญาตให้ใช้คำสั่งนี้!", ephemeral=True)
        return

    admin_user = action_by.mention if action_by else interaction.user.mention
    if warn_type.value == "yellow":
        title_text = "🟨🟨🟨 ใบเหลือง 🟨🟨🟨"
        target_role_id = ROLE_YELLOW_ID
    elif warn_type.value == "orange":
        title_text = "🟧🟧🟧 ใบส้ม 🟧🟧🟧"
        target_role_id = ROLE_ORANGE_ID
    else:
        title_text = "🟥🟥🟥 ใบแดง 🟥🟥🟥"
        target_role_id = ROLE_RED_ID

    role_given_msg = ""
    role = interaction.guild.get_role(target_role_id)
    if role:
        try:
            await user.add_roles(role)
            role_given_msg = f" (มอบยศ {role.mention} เรียบร้อย)"
        except Exception as e:
            role_given_msg = f" (❌ ไม่สามารถมอบยศได้: {e})"

    warn_text = (
        f"{title_text}\n"
        f"--------------------------------------------------\n"
        f"**Discord :** {user.mention} ({user.name})\n"
        f"**Reason :** {reason}\n"
        f"**Note :** {note}\n"
        f"**Action By :** {admin_user}\n"
        f"--------------------------------------------------"
    )
    await interaction.channel.send(content=warn_text, allowed_mentions=discord.AllowedMentions(users=True))
    await interaction.response.send_message(f"✅ ประกาศใบเตือนสำเร็จ{role_given_msg}!", ephemeral=True)

@bot.tree.command(name="giveaway", description="[Staff] สร้างโพสต์กิจกรรม Giveaway")
@app_commands.describe(prize="ของรางวัล", description="รายละเอียดกิจกรรม")
async def giveaway(interaction: discord.Interaction, prize: str, description: str):
    if not check_staff_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มียศที่ได้รับอนุญาตให้ใช้คำสั่งนี้!", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🎉 GIVEAWAY: {prize}",
        description=f"{description}\n\nกดปุ่มด้านล่างเพื่อเข้าร่วมกิจกรรม!",
        color=discord.Color.gold()
    )
    embed.set_footer(text="MsL Community - Giveaway System")
    await interaction.channel.send(embed=embed, view=GiveawayView())
    await interaction.response.send_message("✅ สร้างกิจกรรม Giveaway เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="setup_ticket", description="[Staff] ส่งปุ่มสร้าง Ticket ลงในช่องนี้")
async def setup_ticket(interaction: discord.Interaction):
    if not check_staff_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มียศที่ได้รับอนุญาตให้ใช้คำสั่งนี้!", ephemeral=True)
        return

    embed = discord.Embed(
        title="🎫 ศูนย์ช่วยเหลือและติดต่อสอบถาม",
        description="หากพบปัญหาหรือต้องการติดต่อทีมงาน กดปุ่มด้านล่างเพื่อเปิด Ticket ได้เลยครับ!",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=TicketCreateView())
    await interaction.response.send_message("✅ ติดตั้งแผงควบคุม Ticket เรียบร้อย!", ephemeral=True)

@bot.tree.command(name="roblox", description="เช็กข้อมูลและไอดี Roblox จาก Username")
@app_commands.describe(username="พิมพ์ Username ของ Roblox")
async def roblox_check(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    try:
        with requests.Session() as session:
            user_req = session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": False},
                timeout=5
            )
            data = user_req.json()
            if not data.get("data"):
                await interaction.followup.send(f"❌ ไม่พบผู้ใช้ Roblox ชื่อ **{username}**")
                return

            user_id = data["data"][0]["id"]
            display_name = data["data"][0]["name"]
            requested_username = data["data"][0]["requestedUsername"]
            
            avatar_req = session.get(
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false",
                timeout=5
            )
            avatar_data = avatar_req.json()
            avatar_url = avatar_data["data"][0]["imageUrl"] if avatar_data.get("data") else None

            embed = discord.Embed(title="🔎 Roblox ID Check", color=discord.Color.blue(), timestamp=datetime.now(THAI_TZ))
            embed.add_field(name="🆔 UserId", value=f"`{user_id}`", inline=True)
            embed.add_field(name="🧾 Username", value=f"`{requested_username}`", inline=True)
            embed.add_field(name="🪪 Display Name", value=f"`{display_name}`", inline=False)
            embed.add_field(name="🔗 Profile", value=f"[Open Profile](https://www.roblox.com/users/{user_id}/profile)", inline=False)
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
            embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.display_avatar.url)
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ เกิดข้อผิดพลาด: {e}")

# =========================================================
# 🔄 BOT EVENTS
# =========================================================
@bot.event
async def on_ready():
    bot.add_view(SeparateAuctionView())
    bot.add_view(GiveawayView())
    bot.add_view(CloseTicketView())
    bot.add_view(TicketCreateView())
        
    activity = discord.Game(name="MSL COMMUNITY | /setup_ticket")
    await bot.change_presence(status=discord.Status.online, activity=activity)
        
    print(f"✅ บอทออนไลน์เรียบร้อยแล้ว: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ ซิงค์คำสั่งสำเร็จทั้งหมด {len(synced)} คำสั่ง!")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

# =========================================================
# ⚡ RUN BOT
# =========================================================
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        print("❌ ERROR: ไม่พบ BOT_TOKEN ใน Environment Variables")
        
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web
import sys
import os
import asyncio

TOKEN = os.environ.get("DISCORD_TOKEN", "MTU2NjUwMTQwNTQyNTEzOTg4Mw.GX14Ac.Cbu3yERkRYQTBiMJmX_jOaCQ0li0AhHNENgilk")
GUILD_ID = 1566487806082162758
VOICE_CATEGORY_ID = 1567263077592866928    # VOICE CHATS
MANAGER_CHANNEL_ID = 1567263079064928442   # ⌨️│voice-manager
CREATE_CHANNEL_ID = 1567263080449319022    # create-создать
LFG_ROLE_ID = 1566507072193962045          # @🎮 Ищу пати

active_rooms = {}

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

def get_user_room(guild: discord.Guild, user_id: int):
    for ch_id, owner_id in list(active_rooms.items()):
        if owner_id == user_id:
            ch = guild.get_channel(ch_id)
            if ch:
                return ch
    return None

# ==========================================
# 1. МОДАЛЬНЫЕ ОКНА И МЕНЮ ВЫБОРА
# ==========================================

class RenameModal(discord.ui.Modal, title="Сменить название комнаты"):
    new_name = discord.ui.TextInput(
        label="Новое название",
        placeholder="Например: Катка в рейтинг / +1 на мид",
        min_length=2,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в канал **create-создать**.", ephemeral=True)
            return
        await room.edit(name=f"🎮・{self.new_name.value}")
        await interaction.response.send_message(f"✅ Название комнаты изменено на: **{self.new_name.value}**", ephemeral=True)

class LimitModal(discord.ui.Modal, title="Установить лимит мест"):
    limit = discord.ui.TextInput(
        label="Количество мест (0 - без лимита)",
        placeholder="Например: 2, 3, 5",
        min_length=1,
        max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в канал **create-создать**.", ephemeral=True)
            return
        try:
            val = int(self.limit.value)
            if 0 <= val <= 99:
                await room.edit(user_limit=val)
                limit_text = "без ограничений" if val == 0 else f"{val} чел."
                await interaction.response.send_message(f"👥 Лимит мест установлен: **{limit_text}**", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Введите число от 0 до 99.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Пожалуйста, введите корректное число.", ephemeral=True)

class KickSelect(discord.ui.Select):
    def __init__(self, room: discord.VoiceChannel, members: list[discord.Member]):
        options = [
            discord.SelectOption(
                label=m.display_name[:100],
                value=str(m.id),
                emoji="👤",
                description=f"Ник: {m.name}"[:100]
            )
            for m in members[:25]
        ]
        super().__init__(placeholder="Выберите, кого выгнать...", min_values=1, max_values=1, options=options)
        self.room = room

    async def callback(self, interaction: discord.Interaction):
        target_id = int(self.values[0])
        target = interaction.guild.get_member(target_id)
        if not target:
            await interaction.response.edit_message(content="❌ Участник уже покинул сервер.", view=None)
            return

        try:
            await target.move_to(None)
            await self.room.set_permissions(target, connect=False)
            await interaction.response.edit_message(
                content=f"👢 **{target.display_name}** выгнан из вашей комнаты и заблокирован!",
                view=None
            )
        except Exception as e:
            await interaction.response.edit_message(content=f"❌ Ошибка при исключении: {e}", view=None)

class KickSelectView(discord.ui.View):
    def __init__(self, room: discord.VoiceChannel, members: list[discord.Member]):
        super().__init__(timeout=60)
        self.add_item(KickSelect(room, members))

# ==========================================
# 2. ПОСТОЯННАЯ ПАНЕЛЬ VOICE-MANAGER
# ==========================================

class PersistentVoiceManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="vm_lock")
    async def btn_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в **create-создать**.", ephemeral=True)
            return
        everyone = interaction.guild.default_role
        await room.set_permissions(everyone, connect=False)
        await interaction.response.send_message("🔒 Ваша комната **закрыта** для посторонних!", ephemeral=True)

    @discord.ui.button(label="Открыть", style=discord.ButtonStyle.success, emoji="🔓", custom_id="vm_unlock")
    async def btn_unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в **create-создать**.", ephemeral=True)
            return
        everyone = interaction.guild.default_role
        await room.set_permissions(everyone, connect=True)
        await interaction.response.send_message("🔓 Ваша комната **открыта** для всех!", ephemeral=True)

    @discord.ui.button(label="Сменить имя", style=discord.ButtonStyle.primary, emoji="✏️", custom_id="vm_rename")
    async def btn_rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в **create-создать**.", ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal())

    @discord.ui.button(label="Лимит мест", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="vm_limit")
    async def btn_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в **create-создать**.", ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal())

    @discord.ui.button(label="Кикнуть", style=discord.ButtonStyle.danger, emoji="🚫", custom_id="vm_kick")
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = get_user_room(interaction.guild, interaction.user.id)
        if not room:
            await interaction.response.send_message("❌ У вас нет активной комнаты! Зайдите сначала в **create-создать**.", ephemeral=True)
            return
        other_members = [m for m in room.members if m.id != interaction.user.id]
        if not other_members:
            await interaction.response.send_message("❌ В вашей комнате сейчас никого нет, кроме вас!", ephemeral=True)
            return
        await interaction.response.send_message(
            "👢 Выберите игрока, которого хотите выгнать из своей комнаты:",
            view=KickSelectView(room, other_members),
            ephemeral=True
        )

# ==========================================
# 3. HTTP HEALTHCHECK СЕРВЕР ДЛЯ ОБЛАКА
# ==========================================

async def health_check(request):
    return web.Response(text="Dota Party Bot is alive 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[+] HTTP Healthcheck сервер запущен на порту {port}")

# ==========================================
# 4. СОБЫТИЯ И ГОЛОСОВАЯ ЛОГИКА
# ==========================================

@bot.event
async def on_ready():
    print(f"\n[+] Бот {bot.user} успешно подключился в облаке!")
    bot.add_view(PersistentVoiceManagerView())
    bot.loop.create_task(start_web_server())

    mgr_channel = bot.get_channel(MANAGER_CHANNEL_ID)
    if mgr_channel:
        try:
            async for m in mgr_channel.history(limit=10):
                if m.author == bot.user:
                    await m.delete()

            control_embed = discord.Embed(
                title="🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ ГОЛОСОВЫМ КАНАЛОМ",
                description=(
                    "Добро пожаловать в менеджер личных войс-комнат!\n\n"
                    "👉 **Как создать комнату:**\n"
                    "Просто зайдите в голосовой канал **`create-создать`** ниже.\n"
                    "Бот сразу создаст вашу комнату и перенесет вас туда.\n\n"
                    "⚙️ **Кнопки управления (нажимайте ниже):**\n"
                    "• 🔒 **Закрыть** — закрыть комнату от посторонних\n"
                    "• 🔓 **Открыть** — открыть доступ для всех игроков\n"
                    "• ✏️ **Сменить имя** — задать кастомное название комнаты\n"
                    "• 👥 **Лимит мест** — изменить количество слотов (по умолч. 5)\n"
                    "• 🚫 **Кикнуть** — выгнать нежелательного игрока и заблокировать вход\n\n"
                    "💡 *Когда все участники покинут комнату, она автоматически удалится.*"
                ),
                color=0x3498DB
            )
            control_embed.set_footer(text="dota party • Voice Manager 24/7 (Cloud)")
            await mgr_channel.send(embed=control_embed, view=PersistentVoiceManagerView())
        except Exception as e:
            print(f"[!] Ошибка отправки панели: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and after.channel.id == CREATE_CHANNEL_ID:
        guild = member.guild
        category = guild.get_channel(VOICE_CATEGORY_ID)
        channel_name = f"🎮・Пати {member.display_name}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            member: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True)
        }
        new_voice = await guild.create_voice_channel(
            name=channel_name,
            category=category,
            user_limit=5,
            overwrites=overwrites
        )
        active_rooms[new_voice.id] = member.id
        try:
            await member.move_to(new_voice)
        except Exception as e:
            print(f"[!] Ошибка перемещения: {e}")

    if before.channel and before.channel.id in active_rooms:
        channel = before.channel
        if len(channel.members) == 0:
            del active_rooms[channel.id]
            try:
                await channel.delete()
            except Exception as e:
                print(f"[!] Ошибка удаления канала: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)

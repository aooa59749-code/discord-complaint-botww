# bot.py — Красивая приватная система жалоб с закреплённой кнопкой и автоудалением результатов

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
REVIEW_CHANNEL_ID = int(os.getenv("REPORT_REVIEW_CHANNEL_ID", "0"))
PUBLIC_CHANNEL_ID = int(os.getenv("PUBLIC_RESULTS_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ==================== КРАСИВАЯ ПОСТОЯННАЯ КНОПКА (для закреплённого сообщения) ====================
class ComplaintButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Подать жалобу", 
        style=discord.ButtonStyle.primary, 
        emoji="📋",
        custom_id="persistent_complaint_button"
    )
    async def open_modal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ComplaintModal()
        await interaction.response.send_modal(modal)


# ==================== КРАСИВАЯ АНКЕТА ====================
class ComplaintModal(discord.ui.Modal, title="📋 Подача жалобы"):
    def __init__(self):
        super().__init__()

        self.offender_nick = discord.ui.TextInput(
            label="Ник нарушителя (или ID)",
            style=discord.TextStyle.short,
            placeholder="Напиши точный ник или ID нарушителя",
            required=True,
            max_length=100
        )

        self.what_happened = discord.ui.TextInput(
            label="Что он нарушил",
            style=discord.TextStyle.paragraph,
            placeholder="Подробно опиши нарушение...",
            required=True,
            max_length=1500
        )

        self.evidence = discord.ui.TextInput(
            label="Доказательства",
            style=discord.TextStyle.paragraph,
            placeholder="Ссылки на скрины, видео, сообщения, описания...",
            required=False,
            max_length=1500
        )

        self.add_item(self.offender_nick)
        self.add_item(self.what_happened)
        self.add_item(self.evidence)

    async def on_submit(self, interaction: discord.Interaction):
        nick = self.offender_nick.value.strip()
        reason = self.what_happened.value.strip()
        evidence = self.evidence.value.strip() if self.evidence.value else "Не предоставлены"

        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        if review_channel is None:
            await interaction.response.send_message("❌ Ошибка: канал модераторов не настроен.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚨 НОВАЯ ЖАЛОБА",
            description=f"**Нарушитель:** {nick}",
            color=discord.Color.from_rgb(255, 100, 100),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f"Жалоба от {interaction.user}", icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="📝 Что нарушил", value=reason, inline=False)
        embed.add_field(name="📎 Доказательства", value=evidence, inline=False)
        embed.set_footer(text="Используй кнопки ниже для вынесения решения")

        view = ResolutionView(offender_nick=nick, reporter=interaction.user)
        await review_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            "✅ Жалоба успешно отправлена модераторам!\nРезультат появится в канале итогов.",
            ephemeral=True
        )

        print(f"📩 Новая жалоба от {interaction.user} на {nick}")


# ==================== КНОПКИ РЕШЕНИЯ + ПУБЛИЧНЫЙ РЕЗУЛЬТАТ + АВТОУДАЛЕНИЕ ЧЕРЕЗ 7 ДНЕЙ ====================
class ResolutionView(discord.ui.View):
    def __init__(self, offender_nick: str, reporter: discord.User):
        super().__init__(timeout=None)
        self.offender_nick = offender_nick
        self.reporter = reporter

    async def check_mod(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Только модераторы могут нажимать эти кнопки.", ephemeral=True)
            return False
        return True

    async def post_result_and_schedule_delete(self, interaction: discord.Interaction, status_text: str, color: discord.Color, extra: str = ""):
        mod_embed = interaction.message.embeds[0]
        mod_embed.color = color
        mod_embed.add_field(name="✅ Решение", value=f"{status_text}\n**Рассмотрел:** {interaction.user.mention}", inline=False)
        if extra:
            mod_embed.add_field(name="📌 Примечание", value=extra, inline=False)

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=mod_embed, view=self)

        public_channel = bot.get_channel(PUBLIC_CHANNEL_ID)
        if public_channel:
            public_embed = discord.Embed(
                title="📢 Результат рассмотрения жалобы",
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            public_embed.set_author(name="Система жалоб", icon_url=bot.user.display_avatar.url)
            public_embed.add_field(name="Нарушитель", value=f"`{self.offender_nick}`", inline=True)
            public_embed.add_field(name="Статус", value=status_text, inline=True)
            public_embed.add_field(name="Рассмотрел", value=interaction.user.mention, inline=True)
            if extra:
                public_embed.add_field(name="Примечание", value=extra, inline=False)
            public_embed.set_footer(text="Этот результат будет автоматически удалён через 7 дней")

            public_msg = await public_channel.send(embed=public_embed)

            # Автоудаление через 7 дней
            asyncio.create_task(self.delete_after_days(public_msg, 7))

    async def delete_after_days(self, message, days: int):
        await asyncio.sleep(days * 24 * 60 * 60)
        try:
            await message.delete()
        except:
            pass

    @discord.ui.button(label="✅ Рассмотрено", style=discord.ButtonStyle.green, emoji="✅")
    async def reviewed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_mod(interaction):
            return
        await self.post_result_and_schedule_delete(interaction, "✅ Рассмотрено", discord.Color.green())

    @discord.ui.button(label="❌ Отклонено", style=discord.ButtonStyle.red, emoji="❌")
    async def rejected(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_mod(interaction):
            return
        await self.post_result_and_schedule_delete(interaction, "❌ Отклонено", discord.Color.light_grey())

    @discord.ui.button(label="🔨 Забанить", style=discord.ButtonStyle.danger, emoji="🔨")
    async def ban_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_mod(interaction):
            return

        guild = interaction.guild
        if not guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ У бота нет прав на бан.", ephemeral=True)
            return

        member = None
        if self.offender_nick.isdigit():
            member = guild.get_member(int(self.offender_nick))
        if not member:
            member = guild.get_member_named(self.offender_nick)

        if member:
            try:
                await member.ban(reason=f"Жалоба от {self.reporter}", delete_message_days=0)
                await self.post_result_and_schedule_delete(interaction, "🔨 Забанен", discord.Color.dark_red(), extra=f"Пользователь {member.mention} был забанен.")
            except Exception as e:
                await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ Пользователь `{self.offender_nick}` не найден.", ephemeral=True)
            await self.post_result_and_schedule_delete(interaction, "✅ Рассмотрено (пользователь не найден)", discord.Color.green())


# ==================== КОМАНДЫ ====================

@bot.tree.command(name="жалоба", description="Открыть анкету для подачи жалобы")
async def open_complaint_modal(interaction: discord.Interaction):
    modal = ComplaintModal()
    await interaction.response.send_modal(modal)


@bot.tree.command(name="create-complaint-button", description="Создать закреплённое сообщение с кнопкой (только админы)")
@app_commands.default_permissions(administrator=True)
async def create_button(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Подача жалобы",
        description=(
            "Нажми кнопку ниже, чтобы открыть анкету.\n\n"
            "**В анкете укажи:**\n"
            "• Ник нарушителя (или ID)\n"
            "• Что он нарушил\n"
            "• Доказательства\n\n"
            "Результат рассмотрения появится в канале итогов и будет удалён через 7 дней."
        ),
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.set_footer(text="Система жалоб • Результаты хранятся 7 дней")

    view = ComplaintButtonView()
    await interaction.channel.send(embed=embed, view=view)

    await interaction.response.send_message(
        "✅ Сообщение создано! Теперь закрепи его в этом канале (правой кнопкой → Закрепить сообщение).",
        ephemeral=True
    )


@bot.event
async def on_ready():
    print(f"✅ Бот запущен: {bot.user}")
    bot.add_view(ComplaintButtonView())  # Регистрируем постоянную кнопку

    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(e)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ Нет DISCORD_TOKEN")
    elif REVIEW_CHANNEL_ID == 0 or PUBLIC_CHANNEL_ID == 0:
        print("⚠️ Укажи оба канала в .env")
    bot.run(TOKEN)
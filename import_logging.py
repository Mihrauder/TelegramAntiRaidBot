import logging
import sys
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Set
from dataclasses import dataclass
from telegram import Update, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ChatMemberHandler,
    CallbackQueryHandler,
    filters
)


@dataclass
class BotConfig:
    TOKEN: str = ""
    ADMIN_IDS: List[int] = None
    VERSION: str = "4.0"
    
    RAID_THRESHOLD: int = 4
    TIME_WINDOW: int = 1
    
    CHECK_USERNAME: bool = True
    CHECK_PROFILE_PHOTO: bool = False
    MIN_ACCOUNT_AGE_DAYS: int = 0
    
    AUTO_DELETE_JOIN_MESSAGES: bool = True
    BAN_DURATION: int = 0
    CAPTCHA_ENABLED: bool = False
    CAPTCHA_TIMEOUT: int = 60
    
    WHITELIST_ENABLED: bool = False
    WHITELISTED_USERS: Set[int] = None
    
    def __post_init__(self):
        if self.ADMIN_IDS is None:
            self.ADMIN_IDS = []
        if self.WHITELISTED_USERS is None:
            self.WHITELISTED_USERS = set()


config = BotConfig()


def setup_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    try:
        file_handler = logging.FileHandler('antiraid_bot.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Не удалось создать файл логов: {e}")
    
    return logger


logger = setup_logger()

for log_name in ['httpx', 'httpcore', 'telegram', 'asyncio']:
    logging.getLogger(log_name).setLevel(logging.WARNING)


class DataStorage:
    def __init__(self):
        self.entry_times: Dict[int, List[datetime]] = defaultdict(list)
        self.pending_captcha: Dict[int, Set[int]] = defaultdict(set)
        self.chat_settings: Dict[int, dict] = defaultdict(dict)
        self.ban_stats: Dict[int, int] = defaultdict(int)
        
    def add_entry(self, chat_id: int):
        self.entry_times[chat_id].append(datetime.now())
        
    def get_recent_entries(self, chat_id: int, window_seconds: int) -> int:
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)
        self.entry_times[chat_id] = [t for t in self.entry_times[chat_id] if t > cutoff]
        return len(self.entry_times[chat_id])
    
    def clear_old_entries(self, chat_id: int, max_age_seconds: int = 3600):
        now = datetime.now()
        cutoff = now - timedelta(seconds=max_age_seconds)
        self.entry_times[chat_id] = [t for t in self.entry_times[chat_id] if t > cutoff]


storage = DataStorage()


class SecurityChecks:
    
    @staticmethod
    def is_whitelisted(user_id: int) -> bool:
        return config.WHITELIST_ENABLED and user_id in config.WHITELISTED_USERS
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in config.ADMIN_IDS
    
    @staticmethod
    async def check_username(member) -> bool:
        if not config.CHECK_USERNAME:
            return True
        return member.username is not None
    
    @staticmethod
    async def check_profile_photo(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
        if not config.CHECK_PROFILE_PHOTO:
            return True
        try:
            photos = await context.bot.get_user_profile_photos(user_id, limit=1)
            return photos.total_count > 0
        except:
            return False
    
    @staticmethod
    def check_account_age(member) -> bool:
        if config.MIN_ACCOUNT_AGE_DAYS == 0:
            return True
        return member.id < 1000000000


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = SecurityChecks.is_admin(user_id)
    
    text = (
        f"<b>Антирейд Бот v{config.VERSION}</b>\n\n"
        f"<b>Текущие настройки:</b>\n"
        f"├ Порог срабатывания: {config.RAID_THRESHOLD} входов\n"
        f"├ Временное окно: {config.TIME_WINDOW} сек\n"
        f"├ Проверка username: {'Да' if config.CHECK_USERNAME else 'Нет'}\n"
        f"├ Проверка фото: {'Да' if config.CHECK_PROFILE_PHOTO else 'Нет'}\n"
        f"└ Капча: {'Да' if config.CAPTCHA_ENABLED else 'Нет'}\n\n"
    )
    
    if is_admin:
        text += (
            "<b>Команды администратора:</b>\n"
            "/stats - Статистика банов\n"
            "/settings - Настройки чата\n"
            "/whitelist - Управление белым списком\n"
            "/clear - Очистить историю входов\n"
        )
    else:
        text += "Бот активен и защищает чат от рейдов"
    
    await update.message.reply_text(text, parse_mode='HTML')


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not SecurityChecks.is_admin(user_id):
        await update.message.reply_text("Эта команда доступна только администраторам")
        return
    
    chat_id = update.effective_chat.id
    total_bans = storage.ban_stats[chat_id]
    recent_entries = storage.get_recent_entries(chat_id, 3600)
    
    text = (
        f"<b>Статистика чата</b>\n\n"
        f"Всего банов: {total_bans}\n"
        f"Входов за час: {recent_entries}\n"
        f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(text, parse_mode='HTML')


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not SecurityChecks.is_admin(user_id):
        await update.message.reply_text("Эта команда доступна только администраторам")
        return
    
    keyboard = [
        [InlineKeyboardButton("Изменить порог", callback_data="set_threshold")],
        [InlineKeyboardButton("Изменить окно времени", callback_data="set_window")],
        [InlineKeyboardButton(
            f"{'Да' if config.CHECK_USERNAME else 'Нет'} Проверка username",
            callback_data="toggle_username"
        )],
        [InlineKeyboardButton(
            f"{'Да' if config.CAPTCHA_ENABLED else 'Нет'} Капча",
            callback_data="toggle_captcha"
        )],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "<b>Настройки антирейда</b>\n\nВыберите параметр:",
        parse_mode='HTML',
        reply_markup=reply_markup
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not SecurityChecks.is_admin(user_id):
        await update.message.reply_text("Эта команда доступна только администраторам")
        return
    
    chat_id = update.effective_chat.id
    storage.entry_times[chat_id].clear()
    await update.message.reply_text("История входов очищена")
    logger.info(f"История входов очищена в чате {chat_id}")


async def whitelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not SecurityChecks.is_admin(user_id):
        await update.message.reply_text("Эта команда доступна только администраторам")
        return
    
    if not context.args:
        text = (
            "<b>Белый список</b>\n\n"
            f"Статус: {'Включен' if config.WHITELIST_ENABLED else 'Выключен'}\n"
            f"Пользователей: {len(config.WHITELISTED_USERS)}\n\n"
            "<b>Использование:</b>\n"
            "/whitelist add [ID] - Добавить\n"
            "/whitelist remove [ID] - Удалить\n"
            "/whitelist toggle - Вкл/Выкл\n"
            "/whitelist list - Показать список"
        )
        await update.message.reply_text(text, parse_mode='HTML')
        return
    
    action = context.args[0].lower()
    
    if action == "toggle":
        config.WHITELIST_ENABLED = not config.WHITELIST_ENABLED
        status = "включен" if config.WHITELIST_ENABLED else "выключен"
        await update.message.reply_text(f"Белый список {status}")
        
    elif action == "add" and len(context.args) > 1:
        try:
            user_to_add = int(context.args[1])
            config.WHITELISTED_USERS.add(user_to_add)
            await update.message.reply_text(f"Пользователь {user_to_add} добавлен в белый список")
        except ValueError:
            await update.message.reply_text("Неверный формат ID")
            
    elif action == "remove" and len(context.args) > 1:
        try:
            user_to_remove = int(context.args[1])
            config.WHITELISTED_USERS.discard(user_to_remove)
            await update.message.reply_text(f"Пользователь {user_to_remove} удален из белого списка")
        except ValueError:
            await update.message.reply_text("Неверный формат ID")
            
    elif action == "list":
        if config.WHITELISTED_USERS:
            users_list = "\n".join([f"├ {uid}" for uid in config.WHITELISTED_USERS])
            text = f"<b>Пользователи в белом списке:</b>\n\n{users_list}"
        else:
            text = "Белый список пуст"
        await update.message.reply_text(text, parse_mode='HTML')


async def anti_raid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.new_chat_members:
            return

        chat_id = update.effective_chat.id
        bot_id = context.bot.id
        now = datetime.now()
        
        logger.info(f"Новые участники в чате {update.effective_chat.title} (ID: {chat_id})")
        
        targets = [
            member for member in update.message.new_chat_members
            if member.id != bot_id 
            and not SecurityChecks.is_admin(member.id)
            and not SecurityChecks.is_whitelisted(member.id)
        ]
        
        if not targets:
            if config.AUTO_DELETE_JOIN_MESSAGES:
                await update.message.delete()
            return
        
        for member in targets:
            user_info = f"@{member.username}" if member.username else f"ID:{member.id}"
            logger.info(f"  └─ {user_info} ({member.full_name})")
        
        for _ in targets:
            storage.add_entry(chat_id)
        
        recent_count = storage.get_recent_entries(chat_id, config.TIME_WINDOW)
        
        if recent_count >= config.RAID_THRESHOLD:
            logger.warning(f"РЕЙД ОБНАРУЖЕН! {recent_count} входов за {config.TIME_WINDOW}с")
            
            for member in targets:
                try:
                    await context.bot.ban_chat_member(
                        chat_id=chat_id,
                        user_id=member.id,
                        revoke_messages=True,
                        until_date=config.BAN_DURATION if config.BAN_DURATION > 0 else None
                    )
                    
                    user_info = f"@{member.username}" if member.username else f"ID:{member.id}"
                    logger.warning(f"  Забанен: {user_info}")
                    storage.ban_stats[chat_id] += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка при бане пользователя {member.id}: {e}")
            
            alert_text = (
                f"<b>ОБНАРУЖЕН РЕЙД!</b>\n\n"
                f"Забанено: {len(targets)} пользователей\n"
                f"Входов за {config.TIME_WINDOW}с: {recent_count}"
            )
            
            try:
                alert_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=alert_text,
                    parse_mode='HTML'
                )
                await asyncio.sleep(10)
                await alert_msg.delete()
            except:
                pass
        
        else:
            for member in targets:
                should_ban = False
                ban_reason = []
                
                if not await SecurityChecks.check_username(member):
                    should_ban = True
                    ban_reason.append("нет username")
                
                if not await SecurityChecks.check_profile_photo(context, member.id):
                    should_ban = True
                    ban_reason.append("нет фото")
                
                if not SecurityChecks.check_account_age(member):
                    should_ban = True
                    ban_reason.append("новый аккаунт")
                
                if should_ban:
                    try:
                        await context.bot.ban_chat_member(
                            chat_id=chat_id,
                            user_id=member.id,
                            revoke_messages=True
                        )
                        user_info = f"@{member.username}" if member.username else f"ID:{member.id}"
                        logger.warning(f"Бан по проверкам: {user_info} - {', '.join(ban_reason)}")
                        storage.ban_stats[chat_id] += 1
                    except Exception as e:
                        logger.error(f"Ошибка при бане: {e}")
        
        if config.AUTO_DELETE_JOIN_MESSAGES:
            try:
                await update.message.delete()
            except:
                pass
        
        storage.clear_old_entries(chat_id)
        
    except Exception as e:
        logger.error(f"Критическая ошибка в anti_raid_handler: {e}", exc_info=True)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "toggle_username":
        config.CHECK_USERNAME = not config.CHECK_USERNAME
        status = "включена" if config.CHECK_USERNAME else "выключена"
        await query.edit_message_text(f"Проверка username {status}")
        
    elif query.data == "toggle_captcha":
        config.CAPTCHA_ENABLED = not config.CAPTCHA_ENABLED
        status = "включена" if config.CAPTCHA_ENABLED else "выключена"
        await query.edit_message_text(f"Капча {status}")


def main():
    
    if not config.TOKEN:
        logger.error("Не указан TOKEN бота! Укажите его в переменной TOKEN")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info(f"Запуск Антирейд Бота v{config.VERSION}")
    logger.info(f"Порог: {config.RAID_THRESHOLD}+ входов за {config.TIME_WINDOW}с")
    logger.info(f"Админов: {len(config.ADMIN_IDS)}")
    logger.info(f"Проверка username: {config.CHECK_USERNAME}")
    logger.info(f"Капча: {config.CAPTCHA_ENABLED}")
    logger.info("=" * 60)
    
    application = Application.builder().token(config.TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("whitelist", whitelist_command))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        anti_raid_handler
    ))
    
    try:
        logger.info("Бот запущен и готов к работе!\n")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("\nБот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()


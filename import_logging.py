import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


TOKEN = ""  
ADMIN_IDS = []  
BOT_VERSION = "3.2"
RAID_THRESHOLD = 4
TIME_WINDOW = 1     


def setup_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    
    logger.handlers.clear()
    
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()


logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)


entry_times = defaultdict(list)

async def anti_raid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not update.message or not update.message.new_chat_members:
            return

        chat_id = update.effective_chat.id
        bot_id = context.bot.id
        now = datetime.now()

      
        print("\n" + "="*50)
        print(f"Новые участники в чате: {update.effective_chat.title}")
        print(f"Время: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print("Список новых пользователей:")
        
        for member in update.message.new_chat_members:
            user_info = f"@{member.username}" if member.username else f"ID:{member.id}"
            print(f"- {user_info} ({member.full_name})")

      
        targets = [
            member for member in update.message.new_chat_members
            if member.id != bot_id and member.id not in ADMIN_IDS
        ]

     
        for _ in targets:
            entry_times[chat_id].append(now)

        
        recent_entries = [
            t for t in entry_times[chat_id]
            if t > now - timedelta(seconds=TIME_WINDOW)
        ]

        if len(recent_entries) >= RAID_THRESHOLD:
            print("\n ОБНАРУЖЕН РЕЙД! Бан всех новых участников:")
            for member in targets:
                await context.bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=member.id,
                    revoke_messages=True
                )
                user_info = f"@{member.username}" if member.username else f"ID:{member.id}"
                print(f" Забанен: {user_info}")
                logger.warning(f"БАН: {user_info} в чате {chat_id}")

        await update.message.delete()
        print("="*50 + "\n")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {str(e)}\n")
        logger.error(f"Ошибка: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🛡️ Антирейд v{BOT_VERSION}\n"
        f"Режим: бан всех при {RAID_THRESHOLD}+ входах за {TIME_WINDOW} сек"
    )
    print("\n✅ Бот запущен и готов к работе\n")

def main():

    print("\n" + "="*50)
    print(f"🚀 Запуск антирейд-бота v{BOT_VERSION}")
    print(f"⚙️ Настройки: {RAID_THRESHOLD}+ пользователей за {TIME_WINDOW} сек")
    print(f"👑 Админы: {ADMIN_IDS}")
    print("="*50 + "\n")
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters=filters.StatusUpdate.NEW_CHAT_MEMBERS,
        callback=anti_raid
    ))
    
    try:
        application.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен вручную\n")
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {str(e)}\n")

if __name__ == '__main__':
    main()
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from database import Base, get_engine, get_sessionmaker, AnonUser, AnonMessage, get_or_create_anon_user, select, func
import config

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

engine = get_engine(config.DATABASE_URL)
async_session = get_sessionmaker(engine)

ANONS_PER_PAGE = 5
MESSAGES_PER_PAGE = 2

def build_anon_list_text(anon_list, page):
    start = page * ANONS_PER_PAGE
    end = start + ANONS_PER_PAGE
    sublist = anon_list[start:end]
    if not sublist:
        return "Нет данных для отображения"
    return "\n".join([f"{i+1+start}. {anon_id} (id: {dbid})\t— сообщений: {count}" for i, (dbid, anon_id, count) in enumerate(sublist)])

def build_pagination_kb(page, max_page):
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"al_page_{page-1}"))
    else:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"al_page_end"))
    if page < max_page:
        buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"al_page_{page+1}"))
    else:
        buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"al_page_end"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

def build_am_text(messages, page, anon_user):
    start = page * MESSAGES_PER_PAGE
    end = start + MESSAGES_PER_PAGE
    sublist = messages[start:end]
    if not sublist:
        return "Нет сообщений для отображения"
    lines = [f"{m.id}:\t{m.message}" for m in sublist]
    head = f"Сообщения {anon_user.anon_id} (id: {anon_user.id}):"
    return head + "\n\n" + "\n\n".join(lines)

def build_am_pagination_kb(page, max_page, anon_db_id):
    buttons = [
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"am_page_{anon_db_id}_{page-1}"
        ) if page > 0 else InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"am_page_{anon_db_id}_end"
        ),
        InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data=f"am_page_{anon_db_id}_{page+1}"
        ) if page < max_page else InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data=f"am_page_{anon_db_id}_end"
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])

@dp.message(Command(commands=["start"]))
async def start_handler(message: Message):
    await message.answer("Привет, отправь своё анонимное сообщение.")

@dp.message(lambda m: not m.text.startswith("/"))
async def save_message(message: Message):
    async with async_session() as session:
        anon_user = await get_or_create_anon_user(session, message.from_user.id)
        anon_msg = AnonMessage(anon_user_id=anon_user.id, message=message.text)
        session.add(anon_msg)
        await session.commit()
        await session.refresh(anon_msg)
    await bot.send_message(
        config.OWNER_USER_ID,
        f"ID: {anon_msg.id}\nОт: {anon_user.anon_id}\nСообщение: {anon_msg.message}"
    )
    await message.answer("Сообщение отправлено анонимно.")

@dp.message(Command(commands=["help"]))
async def help_command(message: Message):
    if message.from_user.id != config.OWNER_USER_ID:
        return
    await message.answer(
        "/al — список анонимов с постраничной навигацией\n"
        "/am <ID в базе> — сообщения анонима с постраничной навигацией\n"
        "/r <ID сообщения> <текст> — ответ анонимно\n"
        "/help — информация для владельца\n"
    )

@dp.message(Command(commands=["al"]))
async def anon_list(message: Message):
    if message.from_user.id != config.OWNER_USER_ID:
        return
    async with async_session() as session:
        stmt = await session.execute(
            select(AnonUser.id, AnonUser.anon_id, func.count(AnonMessage.id)).join(AnonMessage).group_by(AnonUser.id)
        )
        anon_list = stmt.all()
    if not anon_list:
        await message.answer("Список анонимов пуст.")
        return
    page, max_page = 0, max(0, (len(anon_list)-1) // ANONS_PER_PAGE)
    text = build_anon_list_text(anon_list, page)
    kb = build_pagination_kb(page, max_page)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("al_page_"))
async def anon_pagination(callback_query):
    if callback_query.from_user.id != config.OWNER_USER_ID:
        await callback_query.answer()
        return
    page_str = callback_query.data.split("_")[-1]
    async with async_session() as session:
        stmt = await session.execute(
            select(AnonUser.id, AnonUser.anon_id, func.count(AnonMessage.id)).join(AnonMessage).group_by(AnonUser.id)
        )
        anon_list = stmt.all()
    max_page = max(0, (len(anon_list)-1) // ANONS_PER_PAGE)
    if not page_str.isdigit():
        await callback_query.answer("Достигнуты границы списка.")
        return
    page = int(page_str)
    if page < 0 or page > max_page:
        await callback_query.answer("Достигнуты границы списка.")
        return
    text = build_anon_list_text(anon_list, page)
    kb = build_pagination_kb(page, max_page)
    await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()

@dp.message(Command(commands=["am"]))
async def anon_messages(message: Message):
    if message.from_user.id != config.OWNER_USER_ID:
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Используйте: /am {ID анонима из базы}")
        return
    anon_db_id = int(args[1])
    async with async_session() as session:
        stmt = await session.execute(select(AnonUser).where(AnonUser.id == anon_db_id))
        anon_user = stmt.scalar_one_or_none()
        if not anon_user:
            await message.answer("Аноним с таким ID не найден.")
            return
        stmt = await session.execute(
            select(AnonMessage).where(AnonMessage.anon_user_id == anon_db_id).order_by(AnonMessage.id)
        )
        messages = stmt.scalars().all()
    if not messages:
        await message.answer(f"У {anon_user.anon_id} (id: {anon_user.id}) нет сообщений.")
        return
    page, max_page = 0, max(0, (len(messages)-1) // MESSAGES_PER_PAGE)
    text = build_am_text(messages, page, anon_user)
    kb = build_am_pagination_kb(page, max_page, anon_db_id)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("am_page_"))
async def am_pagination(callback_query):
    if callback_query.from_user.id != config.OWNER_USER_ID:
        await callback_query.answer()
        return
    parts = callback_query.data.split("_")
    anon_db_id = int(parts[2])
    page = parts[3]
    async with async_session() as session:
        stmt = await session.execute(select(AnonUser).where(AnonUser.id == anon_db_id))
        anon_user = stmt.scalar_one_or_none()
        if not anon_user:
            await callback_query.message.edit_text("Аноним с таким ID не найден.")
            await callback_query.answer()
            return
        stmt = await session.execute(
            select(AnonMessage).where(AnonMessage.anon_user_id == anon_db_id).order_by(AnonMessage.id)
        )
        messages = stmt.scalars().all()
    if not messages:
        await callback_query.message.edit_text(f"У {anon_user.anon_id} (id: {anon_user.id}) нет сообщений.")
        await callback_query.answer()
        return
    max_page = max(0, (len(messages)-1) // MESSAGES_PER_PAGE)
    if not page.isdigit():
        await callback_query.answer("Достигнуты границы списка.")
        return
    page = int(page)
    if page < 0 or page > max_page:
        await callback_query.answer("Достигнуты границы списка.")
        return
    text = build_am_text(messages, page, anon_user)
    kb = build_am_pagination_kb(page, max_page, anon_db_id)
    await callback_query.message.edit_text(text, reply_markup=kb)
    await callback_query.answer()

@dp.message(Command(commands=["r"]))
async def reply_command(message: Message):
    if message.from_user.id != config.OWNER_USER_ID:
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Используйте: /r {ID} {текст ответа}")
        return
    msg_id = args[1]
    reply_text = args[2]
    async with async_session() as session:
        stmt = await session.execute(
            select(AnonMessage).where(AnonMessage.id == int(msg_id))
        )
        anon_msg = stmt.scalar_one_or_none()
        if anon_msg:
            user_stmt = await session.execute(
                select(AnonUser.user_id).where(AnonUser.id == anon_msg.anon_user_id)
            )
            user_row = user_stmt.first()
            if user_row:
                user_id = user_row[0]
                await bot.send_message(user_id, f"Ответ от администратора: {reply_text}")
                await message.answer("Ответ отправлен.")
            else:
                await message.answer("Не найден пользователь для данного сообщения.")
        else:
            await message.answer("Сообщение с таким ID не найдено.")


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

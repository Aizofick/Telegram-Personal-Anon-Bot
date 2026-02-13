from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker, mapped_column, relationship
from sqlalchemy.future import select
from sqlalchemy import Integer, String, ForeignKey, func

Base = declarative_base()

class AnonUser(Base):
    __tablename__ = "anon_users"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(Integer, unique=True, nullable=False)
    anon_id = mapped_column(String, unique=True, nullable=False)
    messages = relationship("AnonMessage", back_populates="anon_user")

class AnonMessage(Base):
    __tablename__ = "anon_messages"
    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    anon_user_id = mapped_column(Integer, ForeignKey("anon_users.id"), nullable=False)
    message = mapped_column(String, nullable=False)
    anon_user = relationship("AnonUser", back_populates="messages")

def get_engine(db_url: str):
    return create_async_engine(db_url, echo=False)

def get_sessionmaker(engine):
    return sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_or_create_anon_user(session: AsyncSession, user_id: int) -> AnonUser:
    stmt = select(AnonUser).where(AnonUser.user_id == user_id)
    result = await session.execute(stmt)
    anon_user = result.scalar_one_or_none()
    if anon_user is None:
        count_stmt = select(func.count(AnonUser.id))
        count_result = await session.execute(count_stmt)
        count = count_result.scalar() or 0
        anon_id = f"Аноним_{count + 1}"
        anon_user = AnonUser(user_id=user_id, anon_id=anon_id)
        session.add(anon_user)
        await session.commit()
        await session.refresh(anon_user)
    return anon_user

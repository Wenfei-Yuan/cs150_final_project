"""One-shot script to create all database tables."""
import asyncio
from app.db.session import engine
from app.db.base import Base
from app.db.models import Document, Chunk, ReadingSession, Interaction, UserProfileMemory

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("All tables created!")

asyncio.run(create_tables())

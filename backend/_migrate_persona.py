"""
One-off migration: add columns to reading_sessions that were added to the
ORM model after the table was first created.
Run once with:  python3.13 _migrate_persona.py
"""
import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import engine
from sqlalchemy import text


NEEDED = [
    # (column_name, column_definition)
    ("persona",             "VARCHAR(32)"),
    ("llm_suggested_mode",  "VARCHAR(32)"),
    ("reading_purpose",     "INTEGER"),
    ("available_time",      "INTEGER"),
    ("support_needed",      "INTEGER"),
    ("user_goal",           "TEXT"),
    ("current_section_index", "INTEGER DEFAULT 0"),
    ("marked_for_retry",    "JSON"),
    ("reading_order",       "JSON"),
    ("jump_return_index",   "INTEGER"),
    ("mode",                "VARCHAR(32)"),
]


async def main():
    async with engine.begin() as conn:
        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'reading_sessions'"
        ))
        existing = {row[0] for row in r}
        print("Existing columns:", sorted(existing))

        for col, defn in NEEDED:
            if col not in existing:
                await conn.execute(text(
                    f"ALTER TABLE reading_sessions ADD COLUMN IF NOT EXISTS {col} {defn}"
                ))
                print(f"  + Added:  {col} {defn}")
            else:
                print(f"  ✓ Exists: {col}")

    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())

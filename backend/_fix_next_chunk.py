"""One-time patch: fix next_chunk to re-join reading_order after a jump."""
import sys

filepath = "app/agents/reading_agent.py"

with open(filepath, "r") as f:
    content = f.read()

old = (
    "        if reading_order:\n"
    "            # Follow the reading order\n"
    "            try:\n"
    "                current_pos = reading_order.index(session.current_chunk_index)\n"
    "                if current_pos + 1 < len(reading_order):\n"
    "                    next_idx = reading_order[current_pos + 1]\n"
    "                    session.current_chunk_index = next_idx\n"
    "                    # Keep unlocked_chunk_index in sync so the lock check passes\n"
    "                    session.unlocked_chunk_index = max(\n"
    "                        session.unlocked_chunk_index, next_idx\n"
    "                    )\n"
    "                else:\n"
    '                    session.status = "completed"\n'
    "            except ValueError:\n"
    "                # Current chunk not in reading order \u2014 advance normally\n"
    "                session = await self.memory_svc.advance_current_chunk(session_id)\n"
    "        else:\n"
    "            session = await self.memory_svc.advance_current_chunk(session_id)"
)

new = (
    "        if reading_order:\n"
    "            # Follow the reading order\n"
    "            try:\n"
    "                current_pos = reading_order.index(session.current_chunk_index)\n"
    "            except ValueError:\n"
    "                # Current chunk is not in reading_order (e.g. after a jump).\n"
    "                # Find the next entry in reading_order that comes after the\n"
    "                # current chunk index so we re-join the curated path.\n"
    "                current_pos = None\n"
    "                cur = session.current_chunk_index\n"
    "                for i, ro_idx in enumerate(reading_order):\n"
    "                    if ro_idx > cur:\n"
    "                        current_pos = i - 1  # so +1 below lands on i\n"
    "                        break\n"
    "                if current_pos is None:\n"
    "                    # Past all entries in reading_order \u2014 mark completed\n"
    '                    session.status = "completed"\n'
    "\n"
    '            if session.status != "completed" and current_pos is not None:\n'
    "                if current_pos + 1 < len(reading_order):\n"
    "                    next_idx = reading_order[current_pos + 1]\n"
    "                    session.current_chunk_index = next_idx\n"
    "                    # Keep unlocked_chunk_index in sync so the lock check passes\n"
    "                    session.unlocked_chunk_index = max(\n"
    "                        session.unlocked_chunk_index, next_idx\n"
    "                    )\n"
    "                else:\n"
    '                    session.status = "completed"\n'
    "        else:\n"
    "            session = await self.memory_svc.advance_current_chunk(session_id)"
)

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w") as f:
        f.write(content)
    print("SUCCESS: next_chunk fixed")
else:
    print("ERROR: could not find the old text to replace", file=sys.stderr)
    sys.exit(1)

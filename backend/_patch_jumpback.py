"""Patch reading_agent.py: add jump_return_index to packet + jump_back method."""
import os

p = os.path.join(os.path.dirname(__file__), 'app', 'agents', 'reading_agent.py')
with open(p) as f:
    content = f.read()

# ── Patch 1: Add jump_return_index to get_chunk_packet ──
old_return = ('        if strategy and strategy.retell_required:\n'
              '            packet["retell_required"] = True\n'
              '        else:\n'
              '            packet["retell_required"] = False\n'
              '\n'
              '        return packet')

new_return = ('        if strategy and strategy.retell_required:\n'
              '            packet["retell_required"] = True\n'
              '        else:\n'
              '            packet["retell_required"] = False\n'
              '\n'
              '        # Expose jump-return info so frontend can show "Return" button\n'
              '        reading_order = session.reading_order\n'
              '        on_reading_line = (\n'
              '            reading_order is None\n'
              '            or chunk.chunk_index in reading_order\n'
              '        )\n'
              '        packet["jump_return_index"] = (\n'
              '            session.jump_return_index\n'
              '            if not on_reading_line and session.jump_return_index is not None\n'
              '            else None\n'
              '        )\n'
              '\n'
              '        return packet')

if old_return not in content:
    print("ERROR: Patch 1 old text not found")
    exit(1)
content = content.replace(old_return, new_return, 1)
print("Patch 1 OK: jump_return_index in packet")

# ── Patch 2: Add jump_back method before next_chunk ──
marker = '    # \u2500\u2500 Advance to next chunk'
idx = content.find(marker)
if idx == -1:
    print("ERROR: Patch 2 marker not found")
    exit(1)

jump_back_method = (
    '    # \u2500\u2500 Jump back to reading line \u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\n'
    '\n'
    '    async def jump_back(self, session_id: str) -> dict:\n'
    '        """Return to the position saved before the last jump."""\n'
    '        session = await self.memory_svc.get_session(session_id)\n'
    '\n'
    '        if session.jump_return_index is None:\n'
    '            return {"error": "No jump to return from."}\n'
    '\n'
    '        # Check if already on the reading line\n'
    '        reading_order = session.reading_order\n'
    '        if reading_order and session.current_chunk_index in reading_order:\n'
    '            return {"error": "Already on the reading line."}\n'
    '\n'
    '        target = session.jump_return_index\n'
    '        session.current_chunk_index = target\n'
    '        session.jump_return_index = None  # Clear after use\n'
    '        await self.db.commit()\n'
    '        await self.db.refresh(session)\n'
    '\n'
    '        return {\n'
    '            "session_id": str(session.id),\n'
    '            "returned_to_chunk": target,\n'
    '        }\n'
    '\n'
)

content = content[:idx] + jump_back_method + content[idx:]
print("Patch 2 OK: jump_back method added")

with open(p, 'w') as f:
    f.write(content)
print("SUCCESS: all patches applied")

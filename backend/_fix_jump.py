"""Temporary script to replace jump_to_section method."""
import os

p = os.path.join(os.path.dirname(__file__), 'app', 'agents', 'reading_agent.py')
with open(p) as f:
    content = f.read()

# Find start: the comment line before jump_to_section
start_marker = content.find('Jump to section (skim / goal-directed)')
if start_marker == -1:
    print("ERROR: Could not find marker")
    exit(1)

# Go back to beginning of that comment line
start = content.rfind('\n', 0, start_marker) + 1

# Find end: the comment line for next method ("Advance to next chunk")
end_marker = content.find('Advance to next chunk', start)
if end_marker == -1:
    print("ERROR: Could not find end marker")
    exit(1)

# Go back to beginning of that comment line
end = content.rfind('\n', 0, end_marker) + 1
# Skip the preceding blank line
if end > 1 and content[end - 2] == '\n':
    end = end - 1

old_block = content[start:end]
print("OLD BLOCK found, length:", len(old_block))

new_block = (
    '    # \u2500\u2500 Jump to section / chunk \u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500'
    '\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n'
    '\n'
    '    async def jump_to_section(\n'
    '        self,\n'
    '        session_id: str,\n'
    '        section_index: int,\n'
    '        *,\n'
    '        chunk_index: int | None = None,\n'
    '    ) -> dict:\n'
    '        """\n'
    '        Jump navigation \u2014 behaviour varies by mode:\n'
    '        \u2022 skim / goal_directed: can jump to any chunk within any section\n'
    '          (if chunk_index is given, jump there; otherwise first chunk)\n'
    '        \u2022 deep_comprehension: always jumps to the first chunk of the section\n'
    '          (chunk_index is ignored)\n'
    '        """\n'
    '        session = await self.memory_svc.get_session(session_id)\n'
    '\n'
    '        # Save current position for potential return\n'
    '        session.jump_return_index = session.current_chunk_index\n'
    '\n'
    '        sections_meta = await self._get_sections_meta(session)\n'
    '        target_section = next(\n'
    '            (sec for sec in sections_meta if sec["section_index"] == section_index),\n'
    '            None,\n'
    '        )\n'
    '        if not target_section or not target_section.get("chunk_indices"):\n'
    '            return {"error": f"No chunks found for section {section_index}."}\n'
    '\n'
    '        is_deep = session.mode == "deep_comprehension"\n'
    '\n'
    '        if chunk_index is not None and not is_deep:\n'
    '            # skim / goal-directed: jump to the requested chunk\n'
    '            if chunk_index not in target_section["chunk_indices"]:\n'
    '                return {\n'
    '                    "error": f"Chunk {chunk_index} does not belong to section {section_index}.",\n'
    '                }\n'
    '            target_chunk_index = chunk_index\n'
    '        else:\n'
    '            # deep mode or no chunk specified: always first chunk of section\n'
    '            target_chunk_index = target_section["chunk_indices"][0]\n'
    '\n'
    '        chunk = await self.chunk_svc.get_chunk_by_index(\n'
    '            session.document_id, target_chunk_index\n'
    '        )\n'
    '\n'
    '        session.current_chunk_index = chunk.chunk_index\n'
    '        session.current_section_index = section_index\n'
    '        session.unlocked_chunk_index = max(\n'
    '            session.unlocked_chunk_index, chunk.chunk_index\n'
    '        )\n'
    '        await self.db.commit()\n'
    '        await self.db.refresh(session)\n'
    '\n'
    '        return {\n'
    '            "session_id": str(session.id),\n'
    '            "jumped_to_chunk": chunk.chunk_index,\n'
    '            "section_index": section_index,\n'
    '        }\n'
    '\n'
)

content = content[:start] + new_block + content[end:]
with open(p, 'w') as f:
    f.write(content)
print("SUCCESS: replacement done")

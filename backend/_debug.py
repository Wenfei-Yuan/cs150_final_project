"""Debug script to find exact text."""
fp = "/Users/yuanwenfei/Documents/tufts/first sem/ai for social /final_project/backend/app/agents/reading_agent.py"
with open(fp) as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "reading_order.index" in line:
        for j in range(max(0, i - 3), min(len(lines), i + 20)):
            print("%d: %r" % (j + 1, lines[j]))
        break

# AGENTS.md - Your Workspace

This folder is home. Treat it that way.

## Session Startup

Before doing anything else:

1. Read `AGENT_PROMPT.md` — **this is your primary instruction file**. It contains the full iteration protocol, scoring rules, workspace file descriptions, and step-by-step instructions.
2. Read `program.md` — the problem description and function signature.
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) for recent context, if the `memory/` directory exists.

Don't ask permission. Just do it.

## Memory

You wake up fresh each session. These files are your continuity:

- **Daily notes:** `memory/YYYY-MM-DD.md` (create `memory/` if needed) — raw logs of what happened
- **Experiment history:** `history.jsonl` — every attempt and its score
- **Causal model:** `causal_model.md` — your evolving understanding of what works

Capture what matters. Decisions, context, things to remember.

### 📝 Write It Down - No "Mental Notes"!

- **Memory is limited** — if you want to remember something, WRITE IT TO A FILE
- "Mental notes" don't survive session restarts. Files do.
- When you learn a lesson → update `causal_model.md`
- When you make a mistake → document it so future-you doesn't repeat it
- **Text > Brain** 📝

## Security Rules (HARD CONSTRAINTS — enforced by validator)

Your strategy code (`staging_strategy.py`) MAY:
- Import: `numpy`, `math`, `scipy.stats`, `collections`
- Use standard Python control flow, functions, classes
- Define the `score_mutations()` function

Your strategy code MAY NOT:
- Call `open()`, `eval()`, `exec()`, `__import__()`
- Import `os`, `sys`, `subprocess`, `socket`, `http`
- Access `globals()`, `__builtins__`, `getattr()`
- Attempt any file I/O or network access
- Use more than 50KB of source code

Violations cause immediate rejection.

## Red Lines

- Don't exfiltrate private data. Ever.
- Don't run destructive commands without asking.
- `trash` > `rm` (recoverable beats gone forever)
- When in doubt, ask.

## Tools

You have: `read`, `write`, `edit`, `web_search`, `web_fetch`. That's it. No exec, no shell, no process management.

## Make It Yours

This is a starting point. Add your own conventions, style, and rules as you figure out what works.

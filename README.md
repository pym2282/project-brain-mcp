# Project Brain MCP

Engineering memory for Claude Code — prevents re-investigating solved problems and repeating rejected architectural decisions across sessions and projects.

## What it does

- **Prevent re-investigating**: Answered questions are recorded as findings. Future sessions skip re-investigation.
- **Prevent repeating rejected architectures**: `validate_plan` checks your proposal against past decisions and mistakes before you proceed.
- **Cross-project learning**: Decisions from other projects appear as soft references, not hard blocks.
- **Persistent memory**: Survives across sessions, stored in `~/.project-brain/memory.json`.

## Installation

```bash
pip install git+https://github.com/pym2282/project-brain-mcp
claude mcp add project-brain project-brain-mcp --scope user
```

Restart Claude Code. The MCP server is now active in all your projects.

## Memory location

Memory is stored at `~/.project-brain/memory.json` — shared across all projects, never committed to any repo.

To use a custom path:

```bash
export PROJECT_BRAIN_MEMORY_PATH=/path/to/memory.json
```

## Tools

| Tool | When to call |
|------|-------------|
| `get_context()` | Session start — returns slim index |
| `get_context(focus=[...])` | When index shows relevant entries — returns full content |
| `validate_plan(plan, current_project)` | Before any architectural proposal |
| `add_decision(title, reason, tags, project)` | When a decision is confirmed |
| `add_finding(question, conclusion, tags, project)` | When an investigation question is answered |
| `add_mistake(description, lesson, tags, project)` | When a wrong approach is identified |
| `update_entry(id, updates)` | To correct an existing entry |
| `delete_entry(id)` | To remove an outdated entry |
| `update_open_questions(questions)` | To track unresolved questions |

## How `validate_plan` works

```
validate_plan("use sqlite for storage", current_project="my-app")
→ conflicts:  [entries from "my-app" that match — must resolve]
→ references: [entries from other projects — consider as context]
```

Same project matches are hard conflicts. Other project matches are soft references.

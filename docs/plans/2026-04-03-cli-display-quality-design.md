# CLI Display Quality Improvements Design

## Goal

Improve the CLI streaming display so tool calls, tool results, and todo updates render cleanly instead of dumping raw JSON/dict repr.

## Background

The monolith Amplifier CLI proves that suppressing tool details works — the LLM narrates what it's doing. The current multi-service CLI dumps raw data for tool events, which is noisy and hard to read. Only a few things matter to the user: which tool ran, key context for a few tools, whether it succeeded, and the todo progress box.

## Approach

Minimal polish — fix three handlers in the existing `display.py`. No new files, no new abstractions. ~50 lines of changes to existing handler methods.

## File Changed

`amplifier-cli/src/amplifier_cli/display.py` — the `StreamingDisplay` class that receives SSE events and renders them to the terminal with Rich.

## Components

### 1. Tool Call Start (`_handle_tool_call_start`)

Print `🔧 tool_name` on a single line in dim style. Just the name, no args. This fires first and gives immediate feedback that a tool is running.

### 2. Tool Call Args (`_handle_tool_call`)

This event carries the full args. For most tools, no-op. But for three specific tools, print a one-line detail indented below:

- **bash**: Extract `command` from args, truncate to ~120 chars. Format: `   $ find ./docs -name "*.md" | sort`
- **read_file**: Extract `file_path` from args. Format: `   ./docs/specs/amplifier-spec.md`
- **todo**: Extract action + first item description, truncate. Format: `   create: "Identify all spec files in docs directory"`
- **All other tools**: No-op (suppress args entirely)

### 3. Tool Results (`_handle_tool_result`)

Tool-specific compact output on success. Clean error message on failure.

| Tool | Success | Failure |
|------|---------|---------|
| bash | `✅ bash` + indented truncated stdout (max ~3 lines) | `✗ bash` + indented truncated stderr in red |
| read_file | `✅ read_file` + indented first ~3 lines of file content | `✗ read_file` + error message in red |
| todo | `✅ todo` + summary like "created 6 items" | `✗ todo: error message` in red |
| Everything else | Just `✅ tool_name` | `✗ tool_name: error message` in red |

For error extraction: use tool-specific fields (`output.stderr` for bash, `error` for others). Fall back to generic "failed" if a clean message can't be extracted.

### 4. Todo Display Box (`_handle_todo_update`)

The existing handler code has a bordered box with colored status icons and a progress bar for >7 items. The only issue is a data parsing bug: the session-service relay may pass data as a raw JSON string rather than a parsed dict.

**Fix**: Add a defensive JSON parse at the top of `_handle_todo_update` — if `data` is a string, `json.loads()` it. Keep the existing bordered box rendering unchanged.

## Data Flow

SSE events arrive in this order per tool call:

1. `tool_call_start` → `_handle_tool_call_start` → prints `🔧 name`
2. `tool_call` → `_handle_tool_call` → prints indented detail (bash/read_file/todo only)
3. `tool_result` → `_handle_tool_result` → prints `✅`/`✗` + tool-specific output
4. `todo_update` (if tool was todo) → `_handle_todo_update` → prints bordered task box

## Example Full Sequence

```
🔧 todo
   create: "Identify all spec files in docs directory"
✅ todo
   created 6 items
┌─ Tasks ──────────────────────────────────────────┐
│ → Identifying spec files                         │
│ ○ Read and analyze amplifier-spec.md             │
│ ○ Read and analyze AMPLIFIER_HOME.md             │
│ ○ Read and analyze definition-files.md           │
│ ○ Summarize findings                             │
│ ○ Present summary to user                        │
└──────────────────────────────────────────────────┘

🔧 bash
   $ find ./docs -name "*.md" -path "*/specs/*" | sort
✅ bash
   ./docs/specs/AMPLIFIER_HOME.md
   ./docs/specs/amplifier-spec.md
   ./docs/specs/definition-files.md

🔧 read_file
   ./docs/specs/amplifier-spec.md
✅ read_file
   # Amplifier IPC Specification
   ## Overview
   This document describes the...

🔧 edit_file
✅ edit_file
```

## Error Handling

```
🔧 bash
   $ rm /nonexistent
✗ bash
   rm: cannot remove '/nonexistent': No such file or directory

🔧 read_file
   ./missing.md
✗ read_file
   File not found: ./missing.md
```

Error messages are extracted from tool-specific result fields. If no clean message can be extracted, fall back to a generic "failed" rather than dumping raw JSON.

## Testing Strategy

Update existing CLI display tests to verify:

- Tool call start shows just the name
- Tool call args show tool-specific detail for bash/read_file/todo, nothing for others
- Tool results show tool-specific compact output for bash/read_file/todo, just name for others
- Error results show clean error messages
- Todo update handles both dict and string data input

## Open Questions

None — design is fully specified.

# `.agents/in_flight/` — background subagent task tracking

Each `<task-id>.md` file in this directory represents an in-flight background subagent task. The file is written **before** the agent is spawned, so if the main session is compacted and the background agent dies silently, the work can be recovered by reading these files.

## Lifecycle

1. **Spawn:** main agent writes `<YYYY-MM-DD>_<short-id>.md` here with `status: queued` → `running`
2. **Complete:** when agent returns, main agent either:
   - moves the file to `./done/<task-id>.md` with `status: completed` (success), or
   - updates `status: failed` in place and logs the error
3. **After session resume:** main agent lists this directory, reconciles each `status: running` entry against actual repo state (`git status`, tests), and re-dispatches if work is incomplete.

## File schema

```markdown
---
task_id: <agent tool id or local short id>
status: queued | running | completed | failed
agent_type: general-purpose | Explore | Plan | refactor-tracker | ...
target_files:
  - path/to/file/a.py
  - path/to/file/b.py
started_at: YYYY-MM-DD HH:MM
completed_at: YYYY-MM-DD HH:MM  # only on completion
---

## Brief
<exact prompt sent to the agent>

## Expected artifacts
- file edits: ...
- tests: ...

## Notes
<post-hoc notes during/after run>
```

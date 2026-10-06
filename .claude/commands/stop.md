---
description: Stop the connector (backend + frontend). Args - [--docker]
argument-hint: "[--docker]"
allowed-tools: Bash(scripts/launch.sh:*), Bash(bash scripts/launch.sh:*)
---

Stop the project services and report the result in one or two lines.

```
bash scripts/launch.sh stop $ARGUMENTS
```

Rules:
- Run `bash scripts/launch.sh status` afterwards and confirm both services report `stopped`.
- On success, say which services were stopped.
- If a service still reports `running`, quote the status line and do not kill processes by hand.
- Do not edit `.env` or any source file.

---
description: Launch the connector (backend + frontend). Args - start|stop|restart|status|logs [--docker]
argument-hint: "[start|stop|restart|status|logs] [--docker]"
allowed-tools: Bash(scripts/launch.sh:*), Bash(bash scripts/launch.sh:*)
---

Run the project launcher and report the result in two or three lines.

```
bash scripts/launch.sh $ARGUMENTS
```

Rules:
- No argument means `start`.
- On success, print the UI URL (http://localhost:5173/) and the API docs URL (http://localhost:8000/docs).
- On failure, run `bash scripts/launch.sh logs` and quote the shortest decisive error line.
- Do not edit `.env` or any source file. If `.env` is missing, tell the user to run `cp .env.example .env`.

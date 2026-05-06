# Orchestrator Bridge

When orchestrator returns a handoff object like:

```json
{
  "action": "douyin_publish",
  "payload": { ... }
}
```

main should:
1. POST payload to `http://127.0.0.1:8787/publish/douyin`
2. read `job_id`
3. poll `GET http://127.0.0.1:8787/jobs/<job_id>` until `done` or `failed`
4. return final result to user

This bridge replaces direct orchestrator-side publish execution.

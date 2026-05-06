# BROWSER.md — Browser Invocation Protocol

`browser` runs on the **Windows node** (same machine as WSL). WSL cannot use a browser directly.

## Invocation

Always use explicit node targeting with the `openclaw` profile:

```
browser(target="node", profile="openclaw", ...)
```

## Error Handling

If you receive any of the following:
- `No connected browser-capable nodes`
- `capabilities=none`
- gateway timeout

**Do not retry with a different profile.** Stop and report the exact failure message to the caller.

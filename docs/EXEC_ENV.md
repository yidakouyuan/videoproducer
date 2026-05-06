# exec Environment

`exec` runs on Windows cmd.exe (NOT bash). Workdir is already set to your workspace.

## Do NOT do

- `pwd` to "verify" cwd — cmd.exe doesn't have it. Your workdir is already correct.
- `ls`, `cat`, `grep`, `which`, `rm -rf` — none exist in cmd.
- `wsl.exe pwd`, `powershell -Command pwd`, `host=sandbox` workarounds — your env is plain cmd.exe; trust it.

## cmd.exe equivalents

| Unix         | cmd.exe                            |
| ------------ | ---------------------------------- |
| `pwd`        | `echo %CD%`                        |
| `ls`         | `dir`                              |
| `cat f`      | `type f`                           |
| `mkdir -p X` | `if not exist "X" mkdir "X"`       |
| `rm f`       | `del f`                            |
| `rm -rf D`   | `rmdir /s /q D`                    |

## Bash escape hatch

For real unix pipelines (jq / find / grep / mkdir -p / chained pipes), wrap the whole thing
with `bash -lc`. cmd.exe forwards the call into WSL bash, which sees `/home/administrator/...`
paths natively:

```
bash -lc 'jq .grounded_tag /home/administrator/.openclaw/runs/$RUN/brief.json'
bash -lc 'mkdir -p ~/.openclaw/runs/<run_id>/raw'
bash -lc 'find ~/.openclaw/runs/<run_id> -name "*.json" | head'
```

Single-quote the inner command. Do not try `wsl.exe --cd ...` or `wsl sh -c '...'` — `bash -lc`
is the only escape you need.

## Path forms

- cmd.exe natively reads Windows paths: `C:\Users\Administrator\.openclaw\runs\<run_id>` (or
  forward slashes `C:/Users/...`).
- WSL paths `/home/administrator/...` only resolve **inside** `bash -lc '...'`. If you pass
  them to cmd.exe directly, native Windows tools won't find the file.
- The two map onto each other:
  - WSL form: `~/.openclaw/runs/<run_id>/`
  - Windows form: `C:\Users\Administrator\.openclaw\runs\<run_id>\`
- runs root is the most common: pick the form that matches the shell you're calling.

## Quick recipes

- Create a run dir: `bash -lc 'mkdir -p ~/.openclaw/runs/<run_id>/raw'`
- Print current dir (sanity, rarely needed): `echo %CD%`
- Read a small JSON: `type C:\Users\Administrator\.openclaw\runs\<run_id>\brief.json`
- jq a value: `bash -lc 'jq -r .grounded_tag ~/.openclaw/runs/<run_id>/brief.json'`

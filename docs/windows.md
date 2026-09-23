# Windows support

candid is Windows-compatible out of the box: stdlib only, no admin rights,
no WSL required.

## Install

1. Install Python 3.11+ from python.org and check **"Add python.exe to PATH"**
   during setup.
2. Clone the repo and install requirements:
   ```powershell
   pip install -r requirements.txt
   python -m candid --help
   ```

## What candid does on Windows

- **Console**: stdout/stderr are switched to UTF-8 and ANSI color support is
  enabled via the Win32 console API (`candid/console.py`). Set `NO_COLOR=1`
  to disable colors.
- **Paths**: per-user config lives under `%APPDATA%\candid`. CLI path
  arguments accept `~`, `$VAR`, and `%VAR%` (`candid/platform.py`
  `normalize_path`). Very long absolute paths get the `\\?\` prefix
  automatically.
- **Saves**: tracker/profile JSON writes go through temp-file + `os.replace`
  (`candid/atomic.py`), so a crash mid-write cannot corrupt your data.
  Advisory file locks use `msvcrt` on Windows.
- **Mock judge**: `subprocess` runs with `shell=False` and `CREATE_NO_WINDOW`
  (no console popups). Note: bubblewrap/firejail sandboxing is POSIX-only;
  on Windows the judge runs code directly in a subprocess guarded by the
  per-test timeout. Do not run untrusted code.
- **Exports**: markdown/text exports pin LF line endings; CSV uses the csv
  module's `newline=""` convention; JSON is UTF-8.
- **Dashboard**: binds `127.0.0.1` only and never exposes your machine to the
  network. If the browser does not auto-open, visit the printed
  `http://127.0.0.1:<port>/` URL manually.

## PowerShell tips

- Quote paths with spaces using **double** quotes:
  ```powershell
  python -m candid gmail import "C:\Users\you\Downloads\takeout.mbox"
  ```
- Single quotes and `~` expansion do not work in PowerShell/cmd.exe the way
  they do in bash; candid expands `~` and `%VAR%` itself for its path
  arguments.

## Known limitations

- The mock judge sandbox (bubblewrap/firejail) is POSIX-only; Windows uses
  timeout-guarded subprocesses instead.
- CI runs the test suite on `windows-latest`, `ubuntu-latest`, and
  `macos-latest` (see `.github/workflows/ci.yml`).

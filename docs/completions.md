# Shell completions

`python -m candid completions bash|zsh|fish` prints a completion script to
stdout. The script is **generated from the live CLI parser** (single source
of truth), so it always matches the candid you have installed - including
any new commands. After upgrading candid, re-run the command and reinstall.

What you get: top-level commands, subcommands (e.g. `track` ->
`add`/`list`/`update`/...), and per-command options. In bash, options that
take a value (like `--jd`) fall back to normal file completion.

## Install

### bash

```bash
# try it for this shell session:
eval "$(python -m candid completions bash)"

# or install persistently:
python -m candid completions bash >> ~/.bash_completion
# then restart your shell (or: source ~/.bash_completion)
```

Completes both `candid ...` and `python -m candid ...` /
`python3 -m candid ...`.

### zsh

```bash
mkdir -p ~/.zsh/completions
python -m candid completions zsh > ~/.zsh/completions/_candid
```

Then in `~/.zshrc`, **before** `compinit`:

```zsh
fpath=(~/.zsh/completions $fpath)
```

Restart your shell. Tip: add `alias candid='python -m candid'` and the
completion fires for that form too.

### fish

```bash
mkdir -p ~/.config/fish/completions
python -m candid completions fish > ~/.config/fish/completions/candid.fish
```

Restart your shell (or run `exec fish`). Covers `candid ...` and
`python -m candid ...`.

## Regenerating

The scripts embed the command list at generation time. After a candid
upgrade (or if a command seems missing), regenerate with the same command
you used to install and replace the old file.

## Notes for contributors

- The generators live in `candid/completions.py`:
  `generate_bash(parser)`, `generate_zsh(parser)`, `generate_fish(parser)`.
- They walk `candid.__main__.build_parser()` via `command_tree()` - no
  hardcoded command lists. If you add a command or option to the parser,
  completions pick it up automatically.
- The command function imports `build_parser` lazily (inside
  `cmd_completions`) so `candid/__main__.py` can import this module without
  an import cycle.
- Scripts are dependency-free: only shell builtins plus the shell's own
  completion helpers (`compgen`, `_arguments`/`_describe`,
  `commandline`/`string`). No external tools, no network.

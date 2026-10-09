# Set up a headless machine

Use this on servers, containers or over SSH without an interactive terminal UI.

## 1. Log in to GitHub

flakipype shares `gh`'s login. On a machine without a browser, log in with a
token:

```bash
gh auth login --hostname github.com --with-token < token.txt
```

A classic token or `gh`'s own OAuth login needs the scopes `repo`,
`workflow` and `read:org`. A fine-grained token needs read and write access
to Actions, Contents, Pull requests and Workflows on the repositories you
scan; GitHub does not report these, so `doctor` shows a warning instead of a
check mark.

If `gh` is not installed yet, step 2 downloads it; you can run the login
afterwards with `~/.local/share/flakipype/bin/gh`.

## 2. Save the configuration

```bash
printf '%s' "$ANTHROPIC_KEY" | flakipype setup --non-interactive \
  --base-url https://api.anthropic.com \
  --model <model> \
  --owner <user-or-org> \
  --api-key-stdin
```

- Options you leave out keep their saved value (or the default).
- The key is read from standard input so it never appears in the process
  list or shell history. Without `--api-key-stdin` the stored key is kept.
- On machines without a system keyring the key goes to
  `~/.config/flakipype/secrets.json` with mode `0600`.
- If no suitable `gh` is found, setup downloads and verifies it.

Setup finishes with the same checks as `flakipype doctor` and exits with code
1 if one fails, or 2 if the input was invalid.

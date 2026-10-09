# Configuration

## Files

| Path | Content |
| --- | --- |
| `$XDG_CONFIG_HOME/flakipype/config.toml` (default `~/.config/flakipype/config.toml`) | Settings below; never contains secrets |
| `$XDG_CONFIG_HOME/flakipype/secrets.json` | Only on machines without a system keyring; mode `0600` |
| `$XDG_DATA_HOME/flakipype/bin/gh` (default `~/.local/share/flakipype/bin/gh`) | `gh` downloaded by flakipype |
| `$XDG_DATA_HOME/flakipype/cache.sqlite3` | Scan cache (jobs of finished attempts, log signatures, verdicts) and chat sessions; deleting it also deletes the sessions |

Relative `XDG_*` values are ignored, as the XDG specification requires.

## `config.toml`

```toml
[llm]
base_url = "https://api.anthropic.com"
model = "claude-sonnet-4-5"

[github]
host = "github.com"
owner = "octo-org"

[scan]
window_days = 30
max_log_downloads = 50
min_flaky_runs = 2

[agent]
max_rounds = 12
max_tokens_per_investigation = 200000
max_seconds_per_investigation = 300
max_tokens_per_run = 1000000
parallel = 3
max_output_tokens = 16000
thinking = "adaptive"
thinking_budget = 8000
excerpt_lines = 120
```

| Key | Default | Rules |
| --- | --- | --- |
| `llm.base_url` | `https://api.anthropic.com` | `https://`; `http://` only for `localhost`, `127.0.0.1`, `::1`. A host ending in `.services.ai.azure.com` uses the Azure AI Foundry client. A trailing slash is removed. |
| `llm.model` | — (required) | Model name; on Foundry the deployment name |
| `github.host` | `github.com` | Host name without scheme, e.g. `github.example.com` for GitHub Enterprise Server |
| `github.owner` | — (required) | GitHub user or organisation name |
| `scan.window_days` | `30` | 1–400 days to look back (GitHub keeps run history for 400 days, logs usually 90) |
| `scan.max_log_downloads` | `50` | 0–1000; hard limit of job logs read per scan. Read logs are cached, so later scans continue |
| `scan.min_flaky_runs` | `2` | 1–100; runs with proven flaky events before a job counts as flaky (and before an error counts as recurring). With `1` every single event counts |

| `agent.max_rounds` | `12` | 1–50 model calls per investigation |
| `agent.max_tokens_per_investigation` | `200000` | 10k–2M tokens (input, output, cache, thinking) per investigation |
| `agent.max_seconds_per_investigation` | `300` | 30–3600 |
| `agent.max_tokens_per_run` | `1000000` | 10k–20M for all investigations of one `investigate` run; reaching it stops starting new ones |
| `agent.parallel` | `3` | 1–8 investigations at once (GitHub calls still go one at a time) |
| `agent.max_output_tokens` | `16000` | 1k–64k per model call |
| `agent.thinking` | `adaptive` | `adaptive`, `enabled` (uses `thinking_budget`) or `off`. Newer models only accept `adaptive`; the others are for older models |
| `agent.thinking_budget` | `8000` | 1,024–60k; only with `thinking = "enabled"`, must be below `max_output_tokens` |
| `agent.excerpt_lines` | `120` | 20–400 lines in a log excerpt |

Unknown keys are an error, so a typo never goes unnoticed. `flakipype setup`
does not edit `[scan]` and `[agent]` and keeps whatever the file has.

## Secrets

| Name | Where |
| --- | --- |
| LLM API key (`llm-api-key`, service `flakipype`) | System keyring via `keyring` (Secret Service, KWallet, …); without one, `secrets.json` |
| GitHub token | Not stored by flakipype: it is `gh`'s own login (`gh auth login`) |

## gh

flakipype uses, in order:

1. `gh` on `PATH`, if it is version 2.97.0 or newer;
2. its own copy in `$XDG_DATA_HOME/flakipype/bin/gh`.

2.97.0 is the first version that neutralises terminal escape sequences in
`gh api` output and offers `--allow-escape-sequences`, which the scan needs to
read raw job logs (flakipype then strips them itself).

flakipype runs `gh` without WSL's mounted Windows folders (`/mnt/c/…`) on
`PATH`: searching them made every `gh` start about a second slower.

If neither exists, `flakipype setup` downloads the latest `cli/cli` release
for the machine (`amd64`, `arm64`, `armv6`, `386`), verifies the tarball
against the release's `gh_<version>_checksums.txt` and installs it
atomically. A mismatch aborts and installs nothing.

The download uses only `github.com` URLs, never `api.github.com`: the latest
version is read from the redirect of `github.com/cli/cli/releases/latest`.
Unauthenticated API calls are limited to 60 per hour per IP address, which
users behind a shared company address exhaust quickly. If GitHub still
refuses (HTTP 403 or 429), setup says so and suggests installing `gh` from
<https://cli.github.com> instead.

Required token scopes for classic and OAuth tokens: `repo`, `workflow`,
`read:org` (`write:org` or `admin:org` also satisfy `read:org`).

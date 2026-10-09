# Getting started

This walks you from installation to a healthy `flakipype doctor`. You need a
Linux machine, an Anthropic API key (or a Claude deployment on Azure AI
Foundry) and a GitHub account with access to the repositories you want to
scan.

## 1. Install

```bash
uv tool install git+https://github.com/besessener/flakipype
flakipype --version
```

## 2. Run the setup wizard

```bash
flakipype setup
```

The wizard is a full-screen form with two sections.

**1 Model**

- **Base URL**: `https://api.anthropic.com`, your Foundry endpoint
  (`https://<resource>.services.ai.azure.com/anthropic`) or a proxy. See
  [connect a model](../how-to/connect-a-model.md).
- **API key**: stored in the system keyring, never in the config file.
- **Model**: the model name, or on Foundry the deployment name.

Press **Test connection**. flakipype sends one tiny request (a single output
token) and shows the model that answered, or what went wrong and what to do.

**2 GitHub**

- **Host**: `github.com`, or your GitHub Enterprise Server host.
- **User or organisation to scan**.
- **gh**: if no `gh` 2.40 or newer is on your `PATH`, press **Download gh**.
  flakipype fetches the latest release for your architecture, checks its
  SHA-256 against the release's checksum file and installs it to
  `~/.local/share/flakipype/bin/gh`.
- **Login**: flakipype shares your normal `gh` login. If you are not logged
  in, press **Log in with browser** (the wizard hands the terminal to
  `gh auth login`) or paste a token and press **Use token**.

Press **Save** (or `Ctrl+S`). `Esc` cancels without saving.

## 3. Check everything

After saving, and any time later:

```bash
flakipype doctor
```

```text
 ✔  Configuration              ~/.config/flakipype/config.toml
 ✔  Model (Anthropic API)      claude-… at https://api.anthropic.com, key in system keyring (SecretService)
 ✔  gh CLI                     2.102.0 at /usr/bin/gh
 ✔  GitHub login (github.com)  octocat, scopes read:org, repo, workflow
 ✔  Scan target                octo-org on github.com
```

Every failed line has an arrow with the next step. `doctor` exits with code
1 when a check fails, so it also works in scripts.

On a server without a terminal UI, see
[set up a headless machine](../how-to/set-up-headless.md).

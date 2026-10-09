# Run CI locally with act

flakipype targets Linux only. When you develop on Windows (or macOS), the
native `uv run poe check` is the fast loop, and [act](https://nektosact.com/)
runs the real `.github/workflows/ci.yml` jobs in Linux containers as the Linux
gate. There is no separate dev container: the workflow is the single source
of truth for what Linux has to pass.

## Prerequisites

- A running Docker engine with Linux containers (Docker Desktop, Rancher
  Desktop, or Docker in WSL).
- act. On Windows without winget, download `act_Windows_x86_64.zip` from the
  [act releases](https://github.com/nektos/act/releases), verify it against
  the release's `checksums.txt`, and unpack `act.exe` into a directory on your
  `PATH`.

The repository's `.actrc` selects the `catthehacker/ubuntu:act-latest` runner
image (close to GitHub's `ubuntu-latest`) and `linux/amd64`. The first run
pulls the image (several GB).

## Run the jobs

```bash
act pull_request -j test       # quality gates on Python 3.12 and 3.14
act pull_request -j hygiene    # gitleaks over the history, prek hooks, zizmor
act -l                         # list all jobs
```

Uncommitted changes are included: act copies the working tree. New files must
at least be staged (`git add`) to be picked up reliably.

## Update TUI snapshots on Linux

Snapshots of the Textual screens must be generated on Linux, where CI
compares them. In WSL, copy the working tree to `/tmp`, update the
snapshots there and copy only the `__snapshots__` folder back:

```bash
rm -rf /tmp/fpcopy && mkdir /tmp/fpcopy
tar --exclude=.venv --exclude=.git -C /mnt/c/path/to/flakipype -cf - . | tar -xf - -C /tmp/fpcopy
cd /tmp/fpcopy
UV_PROJECT_ENVIRONMENT=/tmp/fp-venv uv run --python 3.12 pytest tests/tui -p no:cacheprovider --snapshot-update
cp -r /tmp/fpcopy/tests/tui/__snapshots__/. /mnt/c/path/to/flakipype/tests/tui/__snapshots__/
```

Run these lines inside a WSL shell, not through PowerShell: PowerShell
expands `$…` itself, and an empty variable in a `cp -r` source path copies
the wrong directory.

## Limits

- act is an emulation. GitHub-hosted CI on the pull request stays the
  authority.
- CodeQL (`codeql.yml`) needs GitHub's code scanning backend and does not run
  under act.
- `uv` may print "Failed to hardlink files" inside act; that is harmless.

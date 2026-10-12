#!/bin/sh
# Installs flakipype for the current user: uv first if there is none (checksum verified),
# then flakipype with `uv tool install`. Needs no root.
#
#   curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.1.0/install.sh
#   sh install.sh
#
# FLAKIPYPE_SOURCE installs from somewhere else, e.g. a local checkout (used by the smoke tests).
set -eu

FLAKIPYPE_VERSION="v0.1.0"
UV_VERSION="0.13.0"
REPOSITORY="https://github.com/besessener/flakipype"
BIN_DIR="${HOME}/.local/bin"

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'install.sh: %s\n' "$*" >&2
    exit 1
}

need() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is missing; install the package $2 and run this again"
}

check_system() {
    [ "$(uname -s)" = "Linux" ] || fail "flakipype runs on Linux only"
    case "$(uname -m)" in
        x86_64 | amd64) TARGET="x86_64-unknown-linux-gnu" ;;
        aarch64 | arm64) TARGET="aarch64-unknown-linux-gnu" ;;
        *) fail "the architecture $(uname -m) is not supported (x86_64 and aarch64 are)" ;;
    esac
    getconf GNU_LIBC_VERSION >/dev/null 2>&1 || fail "glibc is required (musl, e.g. Alpine, is not supported)"
    need curl curl
    need tar tar
    need sha256sum coreutils
    need git git
}

download() {
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --output "$2" "$1"
}

install_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV="$(command -v uv)"
        return
    fi
    if [ -x "${BIN_DIR}/uv" ]; then
        UV="${BIN_DIR}/uv"
        return
    fi
    url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TARGET}.tar.gz"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    say "Downloading uv ${UV_VERSION} ..."
    download "$url" "${work}/uv.tar.gz"
    download "${url}.sha256" "${work}/uv.tar.gz.sha256"
    expected="$(cut -d ' ' -f 1 "${work}/uv.tar.gz.sha256")"
    actual="$(sha256sum "${work}/uv.tar.gz" | cut -d ' ' -f 1)"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
        fail "the uv download does not match its published SHA-256; nothing was installed"
    fi
    tar -xzf "${work}/uv.tar.gz" -C "$work"
    mkdir -p "$BIN_DIR"
    cp "${work}/uv-${TARGET}/uv" "${work}/uv-${TARGET}/uvx" "$BIN_DIR/"
    chmod 0755 "${BIN_DIR}/uv" "${BIN_DIR}/uvx"
    UV="${BIN_DIR}/uv"
    say "Installed uv to ${BIN_DIR} (SHA-256 verified)."
}

install_flakipype() {
    source="${FLAKIPYPE_SOURCE:-git+${REPOSITORY}@${FLAKIPYPE_VERSION}}"
    say "Installing flakipype from ${source} ..."
    "$UV" tool install --force "$source"
}

next_steps() {
    case ":${PATH}:" in
        *":${BIN_DIR}:"*) ;;
        *) say "Add ${BIN_DIR} to your PATH, e.g. in ~/.profile: export PATH=\"${BIN_DIR}:\$PATH\"" ;;
    esac
    say "Done. Next: flakipype setup"
}

check_system
install_uv
install_flakipype
next_steps

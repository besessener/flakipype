#!/bin/sh
# Smoke test of a fresh install on a Linux distribution, as a user without root:
# install.sh from a checkout, then the commands that need neither GitHub nor a model.
#
#   sh tests/smoke/smoke.sh <checkout> <expected version>
set -eu

checkout="$1"
expected="$2"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
    printf 'smoke: %s\n' "$*" >&2
    exit 1
}

FLAKIPYPE_SOURCE="$checkout" sh "${checkout}/install.sh"
PATH="${HOME}/.local/bin:${PATH}"
export PATH

version="$(flakipype --version)"
[ "$version" = "flakipype ${expected}" ] || fail "flakipype --version says '${version}'"

code=0
flakipype doctor >"${work}/doctor.txt" 2>&1 || code=$?
[ "$code" -eq 1 ] || fail "doctor without a configuration exited with ${code}, not 1"
grep -q "flakipype setup" "${work}/doctor.txt" || fail "doctor does not point to flakipype setup"

flakipype daemon install --print >"${work}/units.txt"
awk -v dir="$work" '/^# --- / { file = dir "/" $3; next } { print > file }' "${work}/units.txt"
grep -q "^ExecStart=${HOME}/.local/bin/flakipype run --mode auto$" "${work}/flakipype.service" ||
    fail "ExecStart does not start the installed flakipype"
systemd-analyze verify "${work}/flakipype.service" "${work}/flakipype.timer"

printf 'smoke: flakipype %s installs and starts on %s\n' "$expected" \
    "$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release)"

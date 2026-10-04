#!/bin/sh
# UnlimitedPipe installer: installs the `unlimited` command, then runs `unlimited setup`,
# which asks before each step. Read it first if you like:
#   curl -fsSL https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/install.sh | less
#
#   curl -fsSL https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --yes      # accept every setup step
set -eu

# The latest release; set UNLIMITEDPIPE_SPEC to install something else (a path, a branch).
SPEC="${UNLIMITEDPIPE_SPEC:-unlimitedpipe==0.10.52}"

say() { printf '\033[1m%s\033[0m\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

python=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    python="$candidate"
    break
  fi
done

say "Installing UnlimitedPipe"
if command -v uv >/dev/null 2>&1; then
  uv tool install --force --python ">=3.11" "$SPEC"
  bindir="$(uv tool dir --bin)"
elif command -v pipx >/dev/null 2>&1; then
  [ -n "$python" ] || fail "UnlimitedPipe needs Python 3.11 or newer (https://www.python.org/downloads/)"
  pipx install --force --python "$python" "$SPEC"
  bindir="$(pipx environment --value PIPX_BIN_DIR)"
elif [ -n "$python" ]; then
  "$python" -m pip install --user --upgrade "$SPEC" ||
    fail "pip could not install it; install uv (https://docs.astral.sh/uv/) and run this again"
  bindir="$("$python" -m site --user-base)/bin"
else
  # A new Mac has only Python 3.9: uv (https://docs.astral.sh/uv/) brings its own Python and
  # installs into your home folder, without an admin password.
  say "Python 3.11 or newer was not found: installing uv, which brings its own Python"
  command -v curl >/dev/null 2>&1 || fail "UnlimitedPipe needs Python 3.11 or newer, or uv (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >&2 ||
    fail "uv could not be installed; install Python 3.11 or newer (https://www.python.org/downloads/) and run this again"
  uv="$HOME/.local/bin/uv"
  [ -x "$uv" ] || uv="$(command -v uv || true)"
  [ -n "$uv" ] || fail "uv was installed but not found; run this again in a new terminal"
  "$uv" tool install --force --python 3.12 "$SPEC"
  bindir="$("$uv" tool dir --bin)"
fi

# The command just installed, even if an older one comes first on the PATH.
unlimited="$bindir/unlimited"
[ -x "$unlimited" ] || unlimited="$(command -v unlimited || true)"
[ -n "$unlimited" ] || fail "installed, but \`unlimited\` was not found; add $bindir to your PATH"

say "Setting up"
if (exec < /dev/tty) 2>/dev/null; then
  "$unlimited" setup "$@" < /dev/tty    # piped from curl: ask the questions on the terminal
else
  "$unlimited" setup "$@"
fi
case ":$PATH:" in
  *":$(dirname "$unlimited"):"*) ;;
  *) say "Add $(dirname "$unlimited") to your PATH to use \`unlimited\` in new terminals." ;;
esac

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       lint.sh
# \brief      Lint modified/added Verilog/SystemVerilog sources with Verible.
# \author     Kawanami
# \version    1.1
# \date       30/04/2026
#
# \details
#   Discovers modified/added HDL sources (*.sv, *.svh, *.v) in the given Git
#   repository and runs `verible-verilog-lint` with the repository rule
#   configuration.
#
# \remarks
#   - Requires `verible-verilog-lint` to be available either:
#       - in the Git repository under `scripts/verible-verilog-lint`,
#       - or in the user's PATH.
#   - Rules are configured via `scripts/verible_lint.rules`.
#   - The first argument must be the Git repository directory.
#
# \usage
#   ./lint.sh <git-dir>
#
# \section lint_sh_version_history Version history
# | Version | Date       | Author   | Description              |
# |:-------:|:----------:|:---------|:-------------------------|
# | 1.0     | 19/12/2025 | Kawanami | Initial version.         |
# | 1.1     | 30/04/2026 | Kawanami | Add Git directory input. |
# ********************************************************************************
# */

set -euo pipefail

function usage() {
  echo "Usage: $0 <git-dir>"
  echo
  echo "Arguments:"
  echo "  <git-dir>   Path to the Git repository to lint."
}

function err() {
  echo "❌ Error: $*" >&2
  exit 1
}

if [ "$#" -ne 1 ]; then
  usage
  exit 1
fi

GIT_DIR="$1"

if [ ! -d "$GIT_DIR" ]; then
  err "Git directory does not exist: $GIT_DIR"
fi

RULES_FILE="$GIT_DIR/sv-tools/verible_lint.rules"

if [ ! -f "$RULES_FILE" ]; then
  err "Verible lint rules file does not exist: $RULES_FILE"
fi

if [ -x "$GIT_DIR/sv-tools/verible-verilog-lint" ]; then
  VERIBLE_LINT="$GIT_DIR/sv-tools/verible-verilog-lint"
elif command -v verible-verilog-lint >/dev/null 2>&1; then
  VERIBLE_LINT="verible-verilog-lint"
else
  err "verible-verilog-lint not found in '$GIT_DIR/sv-tools/' or in PATH"
fi

mapfile -d '' -t FILES < <(
  git -C "$GIT_DIR" ls-files -z -m -o --exclude-standard -- '*.sv' '*.svh' '*.v'
)

if (( ${#FILES[@]} == 0 )); then
  echo "No modified/untracked Verilog/SystemVerilog files to lint."
  exit 0
fi

echo "Linting Verilog/SystemVerilog files in: $GIT_DIR"
echo "Using rules: $RULES_FILE"
echo

(
  cd "$GIT_DIR"

  "$VERIBLE_LINT" \
    --rules_config="$RULES_FILE" \
    --parse_fatal \
    "${FILES[@]}"
)

echo
echo "✅ HDL lint done."

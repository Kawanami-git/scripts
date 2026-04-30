#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       format_hdl.sh
# \brief      Format Verilog/SystemVerilog modified/added sources with Verible.
# \author     Kawanami
# \version    1.1
# \date       30/04/2026
#
# \details
#   Discovers modified/added HDL sources (*.sv, *.svh, *.v) in the given Git
#   repository and formats them in-place using `verible-verilog-format` with the
#   provided flag file.
#
# \remarks
#   - Requires `verible-verilog-format` to be available either:
#       - in the Git repository under `scripts/verible-verilog-format`,
#       - or in the user's PATH.
#   - The first argument must be the Git repository directory.
#   - The second argument must be the Verible format flag file.
#
# \usage
#   ./format_hdl.sh <git-dir> <verible-format-flags>
#
# \section format_hdl_sh_version_history Version history
# | Version | Date       | Author   | Description                         |
# |:-------:|:----------:|:---------|:------------------------------------|
# | 1.0     | 19/12/2025 | Kawanami | Initial version.                    |
# | 1.1     | 30/04/2026 | Kawanami | Add Git directory and flags inputs. |
# ********************************************************************************
# */

set -euo pipefail

function usage() {
  echo "Usage: $0 <git-dir> <verible-format-flags>"
  echo
  echo "Arguments:"
  echo "  <git-dir>                Path to the Git repository to format."
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
FORMAT_FLAGS="$GIT_DIR/sv-tools/verible_format.flags"

if [ ! -d "$GIT_DIR" ]; then
  err "Git directory does not exist: $GIT_DIR"
fi

if [ -x "$GIT_DIR/sv-tools/verible-verilog-format" ]; then
  VERIBLE_FORMAT="$GIT_DIR/sv-tools/verible-verilog-format"
elif command -v verible-verilog-format >/dev/null 2>&1; then
  VERIBLE_FORMAT="verible-verilog-format"
else
  err "verible-verilog-format not found in '$GIT_DIR/sv-tools/' or in PATH"
fi

mapfile -d '' -t FILES < <(
  git -C "$GIT_DIR" ls-files -z -m -o --exclude-standard -- '*.sv' '*.svh' '*.v'
)

if (( ${#FILES[@]} == 0 )); then
  echo "No modified/untracked Verilog/SystemVerilog files to format."
  exit 0
fi

echo "Formatting Verilog/SystemVerilog files in: $GIT_DIR"
echo "Using flags: $FORMAT_FLAGS"
echo

(
  cd "$GIT_DIR"

  "$VERIBLE_FORMAT" \
    --flagfile="$FORMAT_FLAGS" \
    --inplace \
    --failsafe_success \
    "${FILES[@]}"
)

echo
echo "✅ HDL formatting done."

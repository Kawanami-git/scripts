#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       lint.sh
# \brief      Lint Verilog/SystemVerilog sources with Verible.
# \author     Kawanami
# \version    1.0
# \date       19/12/2025
#
# \details
#   Discovers repository-tracked HDL sources (*.sv, *.svh, *.v) and runs
#   `verible-verilog-lint` with the project rule configuration.
#
# \remarks
#   - Requires `verible-verilog-lint` to be available (invoked via ./scripts/).
#   - Rules are configured via `.verible_lint.rules` at the repo root.
#
# \section lint_sh_version_history Version history
# | Version | Date       | Author   | Description      |
# |:-------:|:----------:|:---------|:-----------------|
# | 1.0     | 19/12/2025 | Kawanami | Initial version. |
# ********************************************************************************
# */

set -euo pipefail
# Lint Verilog/SystemVerilog sources with Verible.
# Requires: verible-verilog-lint in PATH.

RULES_FILE="scripts/verible_lint.rules"

mapfile -t FILES < <(
  git ls-files -m -o --exclude-standard -- '*.sv' '*.svh' '*.v'
)

if (( ${#FILES[@]} == 0 )); then
  echo "No modified/untracked Verilog/SystemVerilog files to lint."
  exit 0
fi

./scripts/verible-verilog-lint \
  --rules_config="${RULES_FILE}" \
  --parse_fatal \
  "${FILES[@]}"

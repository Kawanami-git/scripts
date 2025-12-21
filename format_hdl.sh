#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       format_hdl.sh
# \brief      Format Verilog/SystemVerilog modified/added sources deterministically with Verible.
# \author     Kawanami
# \version    1.0
# \date       19/12/2025
#
# \details
#   Discovers modified/added HDL sources (*.sv, *.svh, *.v) and formats them
#   in-place using `verible-verilog-format` with the project’s flagfile.
#
# \remarks
#   - Requires `verible-verilog-format` to be available (invoked via ./scripts/).
#   - Uses `.verible-format` for consistent style across the repo.
#
# \section format_hdl_sh_version_history Version history
# | Version | Date       | Author   | Description      |
# |:-------:|:----------:|:---------|:-----------------|
# | 1.0     | 19/12/2025 | Kawanami | Initial version. |
# ********************************************************************************
# */

set -euo pipefail

mapfile -t FILES < <(
  git ls-files -m -o --exclude-standard -- '*.sv' '*.svh' '*.v'
)

if (( ${#FILES[@]} == 0 )); then
  echo "No modified/untracked Verilog/SystemVerilog files to format."
  exit 0
fi

./scripts/verible-verilog-format \
  --flagfile=./scripts/verible_format.flags \
  --inplace \
  --failsafe_success \
  "${FILES[@]}"

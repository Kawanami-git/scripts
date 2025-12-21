#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       format_cxx.sh
# \brief      Format modified/added C/C++ files with clang-format.
# \author     Kawanami
# \version    1.0
# \date       19/12/2025
#
# \details
#   Finds files currently modified or added in Git whose extensions match common C/C++
#   suffixes and applies `clang-format -i` to them.
#
# \remarks
#   - Operates only on **modified** or **added** files.
#   - Requires `clang-format` to be available in PATH.
#
# \section format_cxx_sh_version_history Version history
# | Version | Date       | Author   | Description         |
# |:-------:|:----------:|:---------|:--------------------|
# | 1.0     | 19/12/2025 | Kawanami | Initial version.    |
# ********************************************************************************
# */

set -euo pipefail

mapfile -t FILES < <(
  git ls-files -m -o --exclude-standard -- '*.c' '*.cpp' '*.h' '*.hpp'
)

if (( ${#FILES[@]} == 0 )); then
  echo "No modified/untracked C/C++ files to format."
  exit 0
fi

clang-format -i -style=file:scripts/clang-format.flags "${FILES[@]}"



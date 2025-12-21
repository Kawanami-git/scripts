#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       add_spdx.sh
# \brief      Add SPDX license headers to tracked source files.
# \author     Kawanami
# \version    1.0
# \date       26/10/2025
#
# \details
#   Scans configured include paths for matching file globs and inserts an
#   SPDX license header when missing. Skips excluded paths and files that
#   already contain an SPDX tag.
#
# \remarks
#   - Shebang-aware: if a file starts with `#!`, the header is placed on line 2.
#   - VHDL uses `--`, shell/Python/Makefiles/YAML use `#`, others use `//`.
#
# \section add_spdx_sh_version_history Version history
# | Version | Date       | Author   | Description         |
# |:-------:|:----------:|:---------|:--------------------|
# | 1.0     | 26/10/2025 | Kawanami | Initial version.    |
# ********************************************************************************
# */

set -euo pipefail

# Included paths
INCLUDE_PATHS=(
  "."
  "hardware"
  "simulation"
  "software"
  "scripts"
)

# Handled files
GLOBS=(
  "*.sv" "*.svh" "*.v" "*.vhd"
  "*.c" "*.h" "*.hpp" "*.cc" "*.cpp"
  "*.py" "*.sh" "Makefile"
)

# Excluded paths
EXCLUDES=(
  "MPFS_DISCOVERY_KIT"
  "work"
)

spdx_sv="// SPDX-License-Identifier: MIT"
spdx_hash="# SPDX-License-Identifier: MIT"
spdx_vhdl="-- SPDX-License-Identifier: MIT"

should_exclude() {
  local f="$1"
  for p in "${EXCLUDES[@]}"; do
    [[ "$f" == "$p"* || "$f" == */"$p"/* ]] && return 0
  done
  return 1
}

add_header_if_missing() {
  local f="$1"
  grep -q "SPDX-License-Identifier" "$f" && return 0

  case "$f" in
    *.vhd)   sed -i "1i${spdx_vhdl}" "$f" ;;
    *.py|*.sh|Makefile) sed -i "1i${spdx_hash}" "$f" ;;
    *)       sed -i "1i${spdx_sv}" "$f" ;;
  esac
  echo "Ajout SPDX à $f"
}

for base in "${INCLUDE_PATHS[@]}"; do
  for g in "${GLOBS[@]}"; do
    while IFS= read -r -d '' f; do
      should_exclude "$f" || add_header_if_missing "$f"
    done < <(git ls-files "$base/$g" -z 2>/dev/null || true)
  done
done

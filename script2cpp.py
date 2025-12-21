#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       script2cpp.py
# \brief      Extract header from '#'-commented files and convert to C++/Doxygen format.
# \author     Kawanami
# \version    1.0
# \date       02/11/2025
#
# \details
#   This script extracts the SPDX-License-Identifier and the Doxygen-style header
#   from files using the '#' comment style (e.g., Bash, Python, YAML).
#   It converts the extracted comments into a valid C++-style Doxygen block.
#   The content after the header is ignored.
#
#   The script processes the following:
#     - Extracts and reformats the SPDX-License-Identifier as a C++ comment.
#     - Extracts Doxygen-style comments and converts them into a valid Doxygen block.
#     - Ignores all other content in the file.
#     - Supports files with '#' comments (such as Bash, Python, YAML).
#
# \remarks
#   - Intended for use with header files or scripts with a Doxygen header.
#   - Handles common comment formats with 'SPDX' and Doxygen-style headers.
#   - Outputs the transformed header, suitable for inclusion in C++ projects.
#
# \section script2cpp_py_version_history Version history
# | Version | Date       | Author     | Description                               |
# |:-------:|:----------:|:-----------|:------------------------------------------|
# | 1.0     | 03/11/2025 | Kawanami   | Initial version.                          |
# ********************************************************************************
# */

import sys, re

# Regular expression to match the SPDX-License-Identifier line
RE_SPDX = re.compile(r'^\s*#\s*SPDX-License-Identifier:\s*(.+)\s*$')

# Regular expression to detect the start of a Doxygen comment block
RE_START = re.compile(r'^\s*#\s*/\*{1,2}!')   # Matches lines like "# /*!" or "# /**!"
RE_END_ANY = re.compile(r'\*/')               # Matches lines containing "*/"

# Regular expression to match any line starting with a '#'
RE_HASHLINE = re.compile(r'^\s*#\s?(.*)$')

# Regular expression to match shebangs at the beginning of a file (#!/bin/bash, etc.)
RE_SHEBANG = re.compile(r'^\s*#!')

def dehash(line: str) -> str:
    """
    Remove a single leading '# ' from a comment line (with optional spaces).

    Args:
        line (str): The line starting with a comment '#'.

    Returns:
        str: The line with the '#' removed.
    """
    return RE_HASHLINE.sub(r'\1', line.rstrip('\n'))

def read_input() -> list[str]:
    """
    Read the input file either from command-line argument or standard input.

    Returns:
        list[str]: A list of lines read from the input file or stdin.
    """
    if len(sys.argv) > 1:
        # Open file given as command-line argument
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            return f.readlines()
    return sys.stdin.read().splitlines(True)

def extract_header(lines: list[str]) -> str:
    """
    Extract the header section from the input lines, including the SPDX comment and
    the Doxygen header block (if present), and convert them into C++/Doxygen format.

    Args:
        lines (list[str]): List of lines from the input file.

    Returns:
        str: The converted header in C++/Doxygen format.
    """
    out = []
    n = len(lines)
    i = 0

    # Skip any shebang lines at the very top (e.g., "#!/bin/bash", "#!/usr/bin/env python3")
    while i < n and (RE_SHEBANG.match(lines[i]) or lines[i].strip() == ""):
        i += 1

    # Look for SPDX in the first 80 lines
    spdx_done = False
    for j in range(i, min(n, i + 80)):
        m = RE_SPDX.match(lines[j])
        if m:
            # If SPDX is found, convert it to C++ comment format
            out.append("// SPDX-License-Identifier: " + m.group(1) + "\n")
            spdx_done = True
            break

    # Try to find the start of a Doxygen comment block
    k = i
    while k < n and not RE_START.match(lines[k]):
        # Stop early if we encounter non-comment or non-empty content
        if not lines[k].lstrip().startswith('#') and lines[k].strip() != "":
            break
        k += 1

    if k < n and RE_START.match(lines[k]):
        # Doxygen comment block found, process it
        out.append(dehash(lines[k]) + "\n")
        k += 1
        while k < n:
            out.append(dehash(lines[k]) + "\n")
            if RE_END_ANY.search(lines[k]):
                break
            k += 1
        return "".join(out)

    # If no Doxygen block found, process the top '#' block and convert to Doxygen block
    block = []
    k = i
    while k < n:
        ln = lines[k]
        if ln.strip() == "":
            block.append("")  # Keep blank lines in the header
        elif ln.lstrip().startswith('#'):
            block.append(dehash(ln))
        else:
            break
        k += 1

    if block:
        # If SPDX is not already added, add it here
        if not spdx_done and block and block[0].startswith("SPDX-License-Identifier:"):
            out.append("// " + block[0] + "\n")
            block = block[1:]

        # Convert the block into a Doxygen comment
        out.append("/*!\n")
        for b in block:
            out.append(b + "\n")
        out.append("*/\n")
        return "".join(out)

    # If no valid header found, just return SPDX (if present)
    return "".join(out)

def main():
    """
    Main function to execute the script: reads input, processes it, and writes output.
    """
    lines = read_input()
    sys.stdout.write(extract_header(lines))

if __name__ == "__main__":
    main()

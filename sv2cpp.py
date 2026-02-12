
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       sv2cpp.py
# \brief      Convert SystemVerilog to C++-like code for Doxygen documentation.
# \author     Kawanami
# \version    1.1
# \date       12/02/2026
#
# \details
#   This script converts SystemVerilog code into a C++-like format suitable for
#   Doxygen. It preserves Doxygen comments, translates preprocessor directives,
#   normalizes declarations, wraps always/initial/generate blocks into functions,
#   converts typedef enums to C++ enum classes, captures assign statements, and
#   renders module instantiations as C++-like function stubs.
#
# \remarks
#
# \section sv2cpp_py_version_history Version history
# | Version | Date       | Author   | Description                                |
# |:-------:|:----------:|:--------:|:-------------------------------------------|
# | 1.0     | 03/11/2025 | Kawanami | Initial version.                           |
# | 1.1     | 12/02/2026 | Author   | Improve generated documentation.           |
# ********************************************************************************
# */

"""
sv2cpp_doxygen_filter.py

SystemVerilog -> C++-like "pseudo" translation intended for Doxygen parsing.

Main goals:
  - Preserve existing Doxygen comments verbatim.
  - Convert `import pkg::sym;` into C++ `#include "pkg::sym"`.
  - Convert port / signal declarations into pseudo C++ variable declarations.
  - Convert `assign lhs = rhs;` into:
        ///assign lhs = rhs;
        void assign_<lhs>();
  - Convert behavioral blocks (always_ff/always_comb/always_latch/always) into:
        /*!
         * <full original block text>
         */
        void always_ff_<label-or-N>();
  - Convert `typedef enum` and `typedef struct` into C++-like `enum` / `struct`,
    while also keeping the full original construct in a Doxygen block comment.
  - Convert `function` / `task` into a C++-like prototype, while also keeping the
    full original function/task text in a Doxygen block comment.

Notes / limitations:
  - This is NOT a SystemVerilog compiler or a complete parser.
  - The produced output is "Doxygen-friendly" pseudo C++ and may not compile.
  - The filter intentionally drops unhandled SV statements to keep output clean.
  - If you need stronger disambiguation (to avoid name collisions between files),
    consider enabling --wrap-namespace.

Typical Doxygen usage:
  - EXTENSION_MAPPING = sv=cpp svh=cpp
  - FILTER_PATTERNS   = *.sv=python3 sv2cpp_doxygen_filter.py *.svh=python3 sv2cpp_doxygen_filter.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional


def split_top_level_commas(s: str) -> List[str]:
    """Split by commas that are not inside (), [], {} or quotes."""
    parts: List[str] = []
    cur: List[str] = []
    depth_paren = depth_brack = depth_brace = 0
    in_str = False
    str_ch = ""
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str:
            cur.append(ch)
            if ch == str_ch and (i == 0 or s[i - 1] != "\\"):
                in_str = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
            cur.append(ch)
            i += 1
            continue

        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_brack += 1
        elif ch == "]":
            depth_brack = max(0, depth_brack - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)

        if ch == "," and depth_paren == 0 and depth_brack == 0 and depth_brace == 0:
            parts.append("".join(cur).strip())
            cur = []
            i += 1
            continue

        cur.append(ch)
        i += 1

    if cur:
        parts.append("".join(cur).strip())
    return parts


def compact_brackets(s: str) -> str:
    """Remove whitespace inside [...] ranges and remove space before '['."""
    def repl(m: re.Match) -> str:
        inner = re.sub(r"\s+", "", m.group(1))
        return "[" + inner + "]"

    s2 = re.sub(r"\[([^\]]+)\]", repl, s)
    s2 = re.sub(r"\s+\[", "[", s2)
    return s2


def sanitize_identifier(s: str) -> str:
    """Make a safe C/C++-like identifier from an SV LHS expression."""
    s2 = re.sub(r"[^0-9A-Za-z_]+", "_", s)
    s2 = re.sub(r"_+", "_", s2).strip("_")
    if not s2:
        s2 = "unnamed"
    if re.match(r"^\d", s2):
        s2 = "_" + s2
    return s2


def normalize_decl_text(text: str) -> str:
    """Normalize a declaration: compact whitespace and brackets."""
    t = text.strip()
    t = re.sub(r"//.*$", "", t).rstrip()
    t = re.sub(r"\s+", " ", t)
    t = compact_brackets(t)
    return t.strip()


def make_doxygen_block(lines: List[str], indent: str = "  ") -> List[str]:
    out = [f"{indent}/*!"]
    for ln in lines:
        out.append(f"{indent} * {ln.rstrip()}")
    out.append(f"{indent} */")
    return out

def make_doxygen_code_block(code_lines: List[str], indent: str = "  ") -> List[str]:
    """
    Wrap raw code lines inside a Doxygen \\code / \\endcode block.

    This is important because Doxygen's Markdown renderer collapses single newlines
    inside normal comment paragraphs. A \\code block preserves formatting exactly.
    """
    out = [f"{indent}/*!",
           f"{indent} * \\code"]
    for ln in code_lines:
        out.append(f"{indent} * {ln.rstrip()}")
    out.append(f"{indent} * \\endcode")
    out.append(f"{indent} */")
    return out


def sv_pretty_format(block_lines: List[str]) -> List[str]:
    """
    Best-effort pretty printer for SV snippets (for readability inside Doxygen).
    - Inserts newlines after ';' outside (), [], {}.
    - Splits lines that contain trailing code after 'begin' or 'end'.
    - Applies indentation based on begin/end and case/endcase.

    This is heuristic on purpose: the goal is readable docs, not perfect parsing.
    """
    text = "\n".join(block_lines).replace("\r\n", "\n").replace("\r", "\n")

    # 1) Insert newlines after ';' (but not inside parentheses/brackets/braces or strings)
    out_chars: List[str] = []
    depth_paren = depth_brack = depth_brace = 0
    in_str = False
    str_ch = ""

    i = 0
    while i < len(text):
        ch = text[i]

        if in_str:
            out_chars.append(ch)
            if ch == str_ch and (i == 0 or text[i - 1] != "\\"):
                in_str = False
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
            out_chars.append(ch)
            i += 1
            continue

        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "[":
            depth_brack += 1
        elif ch == "]":
            depth_brack = max(0, depth_brack - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)

        out_chars.append(ch)

        if ch == ";" and depth_paren == 0 and depth_brack == 0 and depth_brace == 0:
            # Avoid inserting multiple blank lines if next is already newline
            if i + 1 < len(text) and text[i + 1] != "\n":
                out_chars.append("\n")

        i += 1

    text2 = "".join(out_chars)

    # 2) Split after 'begin' or 'end' if there's trailing code on the same line
    def split_begin_end(line: str) -> List[str]:
        s = line.strip()
        if not s:
            return [""]

        pieces: List[str] = []
        while True:
            m_begin = re.search(r"\bbegin\b(?:\s*:\s*\w+)?", s)
            if m_begin and re.search(r"\S", s[m_begin.end():]):
                pieces.append(s[:m_begin.end()].rstrip())
                s = s[m_begin.end():].lstrip()
                continue

            m_end = re.search(r"\bend\b(?:\s*:\s*\w+)?", s)
            if m_end and re.search(r"\S", s[m_end.end():]):
                pieces.append(s[:m_end.end()].rstrip())
                s = s[m_end.end():].lstrip()
                continue

            break

        pieces.append(s.strip())
        return [p for p in pieces if p != ""]

    raw_lines: List[str] = []
    for ln in text2.splitlines():
        raw_lines.extend(split_begin_end(ln))

    # 3) Indent (begin/end + case/endcase)
    pretty: List[str] = []
    indent_level = 0

    def is_case_start(s: str) -> bool:
        return bool(re.match(r"^(unique\s+|priority\s+)?(case|casez|casex)\b", s))

    for ln in raw_lines:
        s = ln.strip()
        if s == "":
            pretty.append("")
            continue

        # decrease before printing closing keywords
        if re.match(r"^(end|endcase|endfunction|endtask|join|join_any|join_none)\b", s):
            indent_level = max(0, indent_level - 1)

        pretty.append(("  " * indent_level) + s)

        # increase after printing opening keywords
        if re.search(r"\bbegin\b(?:\s*:\s*\w+)?\s*$", s):
            indent_level += 1
        elif is_case_start(s):
            indent_level += 1

    return pretty


def strip_line_comment(s: str) -> str:
    """Remove // comments (best-effort, no string awareness)."""
    return re.sub(r"//.*$", "", s)


def parse_instance_header(stmt: str) -> Optional[tuple[str, str]]:
    """
    Parse the beginning of a SystemVerilog module instantiation statement.

    Supported forms (whitespace/newlines irrelevant):
      mod_t inst ( ... );
      mod_t #( .P(1) ) inst ( ... );
      mod_t #(... ) inst[3:0] ( ... );

    Returns:
      (module_type, instance_name)

    This is a heuristic parser (not a full SV grammar).
    """
    s = stmt.strip().rstrip(";").strip()

    # Fast reject: must start with an identifier.
    m0 = re.match(r"^([A-Za-z_]\w*)\b", s)
    if not m0:
        return None

    mod_type = m0.group(1)

    # Exclude common SV keywords that also look like identifiers.
    if mod_type in {
        "if", "for", "foreach", "while", "do", "case", "casez", "casex",
        "unique", "priority", "return", "break", "continue", "disable",
        "begin", "end", "assign", "always", "always_ff", "always_comb", "always_latch",
        "function", "task", "typedef", "module", "package",
    }:
        return None

    # Walk the string to extract: [mod_type] [#(params)] [inst_name [dims]] (
    i = len(mod_type)

    def skip_ws(j: int) -> int:
        while j < len(s) and s[j].isspace():
            j += 1
        return j

    def consume_balanced_parens(j: int) -> Optional[int]:
        """Consume a balanced (...) starting at s[j] == '(' and return index after it."""
        if j >= len(s) or s[j] != "(":
            return None
        depth = 0
        in_str = False
        str_ch = ""
        while j < len(s):
            ch = s[j]
            if in_str:
                if ch == str_ch and (j == 0 or s[j - 1] != "\\"):
                    in_str = False
                j += 1
                continue
            if ch in ("\"", "'"):
                in_str = True
                str_ch = ch
                j += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    i = skip_ws(i)

    # Optional parameterization: # ( ... )
    if i < len(s) and s[i] == "#":
        i += 1
        i = skip_ws(i)
        i2 = consume_balanced_parens(i)
        if i2 is None:
            return None
        i = skip_ws(i2)

    # Instance identifier
    m1 = re.match(r"([A-Za-z_]\w*)\b", s[i:])
    if not m1:
        return None
    inst_name = m1.group(1)
    i += len(inst_name)
    i = skip_ws(i)

    # Optional instance array dimensions
    while i < len(s) and s[i] == "[":
        endb = s.find("]", i + 1)
        if endb < 0:
            return None
        i = skip_ws(endb + 1)

    # Must be followed by port list '('
    if i >= len(s) or s[i] != "(":
        return None

    return (mod_type, inst_name)


def collect_statement_until_semicolon(lines: List[str], start: int) -> tuple[List[str], int]:
    """Collect lines until a top-level ';' is reached (paren/brack/brace balanced)."""
    stmt_lines: List[str] = [lines[start]]
    depth_paren = depth_brack = depth_brace = 0
    in_str = False
    str_ch = ""

    def scan_chunk(chunk: str) -> bool:
        nonlocal depth_paren, depth_brack, depth_brace, in_str, str_ch
        j = 0
        while j < len(chunk):
            ch = chunk[j]
            if in_str:
                if ch == str_ch and (j == 0 or chunk[j - 1] != "\\"):
                    in_str = False
                j += 1
                continue
            if ch in ("\"", "'"):
                in_str = True
                str_ch = ch
                j += 1
                continue
            if ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren = max(0, depth_paren - 1)
            elif ch == "[":
                depth_brack += 1
            elif ch == "]":
                depth_brack = max(0, depth_brack - 1)
            elif ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace = max(0, depth_brace - 1)
            elif ch == ";" and depth_paren == 0 and depth_brack == 0 and depth_brace == 0:
                return True
            j += 1
        return False

    idx = start
    while True:
        chunk = strip_line_comment(lines[idx])
        if scan_chunk(chunk):
            break
        if idx + 1 >= len(lines):
            break
        idx += 1
        stmt_lines.append(lines[idx])

    return stmt_lines, idx



def parse_sv_function_signature(header: str, kind: str = "function") -> Optional[str]:
    """
    Parse an SV function/task header (up to ';') and return a C++-like prototype.

    Examples:
      function automatic logic [3:0] foo(input logic [1:0] a, input logic b);
      task automatic bar(input int x);

    Output:
      logic[3:0] foo(logic[1:0] a, logic b);
      void bar(int x);
    """
    h = header.strip()
    if h.endswith(";"):
        h = h[:-1].strip()

    h = re.sub(rf"^{kind}\b", "", h).strip()
    h = re.sub(r"\bautomatic\b", "", h)
    h = re.sub(r"\bstatic\b", "", h)
    h = re.sub(r"\bvirtual\b", "", h)
    h = re.sub(r"\s+", " ", h).strip()

    rtype = "void"
    name: Optional[str] = None
    args = ""

    m = re.match(r"(?P<before>\S.*)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<args>.*)\)\s*$", h)
    if m:
        before = m.group("before").strip()
        name = m.group("name")
        args = m.group("args").strip()
        rtype = before if kind == "function" else "void"
    else:
        m2 = re.match(r"(?P<name>[A-Za-z_]\w*)\s*\((?P<args>.*)\)\s*$", h)
        if m2:
            name = m2.group("name")
            args = m2.group("args").strip()
            rtype = "void"
        else:
            m3 = re.match(r"(?P<before>\S.*)\s+(?P<name>[A-Za-z_]\w*)\s*$", h)
            if m3:
                before = m3.group("before").strip()
                name = m3.group("name")
                rtype = before if kind == "function" else "void"
            else:
                return None

    arg_list: List[str] = []
    if args:
        for a in split_top_level_commas(args):
            a = a.strip()
            # strip default value
            a = re.sub(r"\s*=\s*.*$", "", a).strip()
            # strip direction / qualifiers
            a = re.sub(r"^(input|output|inout|ref|const|var)\b", "", a).strip()
            a = re.sub(r"\s+", " ", a)
            a = compact_brackets(a)
            if a:
                arg_list.append(a)

    rtype = compact_brackets(re.sub(r"\s+", " ", rtype).strip())
    return f"{rtype} {name}(" + ", ".join(arg_list) + ");"



def resolve_instance_include(mod_type: str, base_dir: Optional[Path], ext_mode: str, noext: bool) -> str:
    """Resolve an include target for an instantiated module.

    - If noext=True, returns just the module name (e.g. "exe").
    - If ext_mode == "auto": try to find a sibling file <mod_type>.sv or <mod_type>.svh in base_dir.
      Fallback: <mod_type>.sv
    - If ext_mode is ".sv" or ".svh": return <mod_type><ext_mode>
    """
    if noext:
        return mod_type

    ext_mode = ext_mode.strip()
    if ext_mode not in {"auto", ".sv", ".svh"}:
        ext_mode = "auto"

    if ext_mode == "auto" and base_dir is not None:
        for ext in (".sv", ".svh"):
            cand = base_dir / f"{mod_type}{ext}"
            if cand.exists():
                return f"{mod_type}{ext}"
        return f"{mod_type}.sv"

    if ext_mode in {".sv", ".svh"}:
        return f"{mod_type}{ext_mode}"

    return f"{mod_type}.sv"


def insert_includes_after_header(out_lines: List[str], include_lines: List[str]) -> List[str]:
    """Insert include_lines after the leading file header comments/blank lines.

    Also avoids inserting duplicates if the exact include already exists anywhere.
    """
    if not include_lines:
        return out_lines

    existing = set([ln.strip() for ln in out_lines if ln.lstrip().startswith("#include")])
    final_includes = [ln for ln in include_lines if ln.strip() not in existing]
    if not final_includes:
        return out_lines

    # Find insertion point: after leading block of comments/blank lines.
    idx = 0
    while idx < len(out_lines):
        s = out_lines[idx].strip()
        if s == "":
            idx += 1
            continue
        if s.startswith("//"):
            idx += 1
            continue
        if s.startswith("/*") or s.startswith("/*!"):
            # skip until end of block comment
            idx += 1
            while idx < len(out_lines) and "*/" not in out_lines[idx]:
                idx += 1
            if idx < len(out_lines):
                idx += 1
            continue
        break

    # If there are already includes right after the header, insert after them.
    while idx < len(out_lines) and out_lines[idx].lstrip().startswith("#include"):
        idx += 1

    new_out = out_lines[:idx] + final_includes + [""] + out_lines[idx:]
    return new_out

def convert_sv_to_cpp_pseudo(
    src: str,
    wrap_namespace: bool = False,
    use_code_blocks: bool = True,
    namespace_name: Optional[str] = None,
    keep_unknown_as_comment: bool = False,
    # For resolving instance-generated includes
    input_path: Optional[str] = None,
    emit_instance_includes: bool = True,
    inst_include_ext: str = "auto",
    inst_include_noext: bool = False,
) -> str:
    lines = src.splitlines()
    out: List[str] = []

    i = 0
    assign_counter = 0
    always_counter = 0
    func_counter = 0
    typedef_counter = 0

    in_block_comment = False


    inst_module_types: set[str] = set()
    base_dir = Path(input_path).parent if input_path else None
    # (Optional) find a reasonable namespace name automatically
    if wrap_namespace and namespace_name is None:
        for ln in lines:
            m = re.match(r"^\s*(module|package)\s+([A-Za-z_]\w*)\b", ln)
            if m:
                namespace_name = m.group(2)
                break
        if namespace_name is None:
            namespace_name = "sv"

    if wrap_namespace:
        out.append(f"namespace {sanitize_identifier(namespace_name or 'sv')} {{")
        out.append("")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Preserve block comments verbatim (including Doxygen headers)
        if in_block_comment:
            out.append(line)
            if "*/" in line:
                in_block_comment = False
            i += 1
            continue

        if "/*" in line:
            out.append(line)
            if "*/" not in line:
                in_block_comment = True
            i += 1
            continue

        # Preserve line comments (including SPDX)
        if stripped.startswith("//"):
            out.append(line)
            i += 1
            continue

        if stripped == "":
            out.append("")
            i += 1
            continue

        # SystemVerilog `include -> #include
        m_inc = re.match(r'^\s*`include\s+"([^"]+)"\s*', line)
        if m_inc:
            out.append(f'#include "{m_inc.group(1)}"')
            i += 1
            continue

        # import -> include(s)
        if re.match(r"^\s*import\b", line):
            stmt_lines = [line]
            while ";" not in stmt_lines[-1] and i + 1 < len(lines):
                i += 1
                stmt_lines.append(lines[i])

            stmt = " ".join([re.sub(r"//.*$", "", l).strip() for l in stmt_lines])
            stmt = re.sub(r"\s+", " ", stmt)
            body = re.sub(r"^\s*import\s+", "", stmt).rstrip(";").strip()
            for it in split_top_level_commas(body):
                it = it.strip()
                if it:
                    out.append(f'#include "{it}"')
            i += 1
            continue

        # typedef enum
        if re.match(r"^\s*typedef\s+enum\b", line):
            typedef_lines = [line]
            brace_depth = 0
            saw_lbrace = False
            while True:
                text = re.sub(r"//.*$", "", typedef_lines[-1])
                brace_depth += len(re.findall(r"\{", text))
                brace_depth -= len(re.findall(r"\}", text))
                if "{" in text:
                    saw_lbrace = True
                if saw_lbrace and brace_depth <= 0 and re.search(r"}\s*\w+\s*;", text):
                    break
                if i + 1 >= len(lines):
                    break
                i += 1
                typedef_lines.append(lines[i])

            typedef_counter += 1
            if use_code_blocks:
                out.extend(make_doxygen_code_block(sv_pretty_format(typedef_lines), indent="  "))
            else:
                out.extend(make_doxygen_block(typedef_lines, indent="  "))

            joined = "\n".join(typedef_lines)
            mname = re.search(r"}\s*(\w+)\s*;", joined)
            enum_name = mname.group(1) if mname else f"enum_{typedef_counter}"

            body_m = re.search(r"\{(.*)\}", joined, flags=re.S)
            enum_body = body_m.group(1) if body_m else ""

            enums: List[str] = []
            for item in split_top_level_commas(enum_body):
                item = item.strip()
                if not item:
                    continue
                item = re.sub(r"//.*$", "", item).strip().rstrip(";").strip()
                if not item:
                    continue

                # SV numeric literals -> C++-ish
                item = re.sub(
                    r"(\d+)?'h([0-9a-fA-F_]+)",
                    lambda m: "0x" + m.group(2).replace("_", ""),
                    item,
                )
                item = re.sub(
                    r"(\d+)?'d([0-9_]+)",
                    lambda m: m.group(2).replace("_", ""),
                    item,
                )
                item = re.sub(
                    r"(\d+)?'b([01_xXzZ_]+)",
                    lambda m: "0b"
                    + m.group(2)
                    .replace("_", "")
                    .replace("x", "0")
                    .replace("X", "0")
                    .replace("z", "0")
                    .replace("Z", "0"),
                    item,
                )
                item = re.sub(r"'0\b", "0", item)
                item = re.sub(r"'1\b", "1", item)

                enums.append(item)

            out.append(f"  enum {enum_name} {{")
            for e in enums:
                out.append(f"    {e},")
            out.append("  };")
            out.append("")
            i += 1
            continue

        # typedef struct
        if re.match(r"^\s*typedef\s+struct\b", line):
            struct_lines = [line]
            brace_depth = 0
            saw_lbrace = False
            while True:
                text = re.sub(r"//.*$", "", struct_lines[-1])
                brace_depth += len(re.findall(r"\{", text))
                brace_depth -= len(re.findall(r"\}", text))
                if "{" in text:
                    saw_lbrace = True
                if saw_lbrace and brace_depth <= 0 and re.search(r"}\s*\w+\s*;", text):
                    break
                if i + 1 >= len(lines):
                    break
                i += 1
                struct_lines.append(lines[i])

            typedef_counter += 1
            if use_code_blocks:
                out.extend(make_doxygen_code_block(sv_pretty_format(struct_lines), indent="  "))
            else:
                out.extend(make_doxygen_block(struct_lines, indent="  "))

            joined = "\n".join(struct_lines)
            mname = re.search(r"}\s*(\w+)\s*;", joined)
            struct_name = mname.group(1) if mname else f"struct_{typedef_counter}"

            body_m = re.search(r"\{(.*)\}", joined, flags=re.S)
            body = body_m.group(1) if body_m else ""

            out.append(f"  struct {struct_name} {{")
            for bl in body.splitlines():
                b = bl.strip()
                if not b:
                    continue
                if b.startswith("///") or b.startswith("//!"):
                    out.append("    " + b)
                    continue
                b = re.sub(r"//.*$", "", b).strip()
                if not b:
                    continue
                if b.endswith(";"):
                    b = b[:-1].strip()

                mm = re.match(
                    r"(?P<type>.+?)\s+(?P<names>[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)?(?:\s*,\s*[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)?)*)$",
                    b,
                )
                if mm:
                    typ = compact_brackets(re.sub(r"\s+", " ", mm.group("type")).strip())
                    names = mm.group("names")
                    for nm in split_top_level_commas(names):
                        nm_clean = compact_brackets(re.sub(r"\s+", "", nm))
                        out.append(f"    {typ} {nm_clean};")
                else:
                    out.append(f"    // {b}")
            out.append("  };")
            out.append("")
            i += 1
            continue

        # function / task
        if re.match(r"^\s*function\b", line) or re.match(r"^\s*task\b", line):
            kind = "function" if re.match(r"^\s*function\b", line) else "task"
            end_kw = "endfunction" if kind == "function" else "endtask"

            block_lines = [line]
            while i + 1 < len(lines):
                if re.search(rf"\b{end_kw}\b", re.sub(r"//.*$", "", block_lines[-1])):
                    break
                i += 1
                block_lines.append(lines[i])
                if re.search(rf"\b{end_kw}\b", re.sub(r"//.*$", "", lines[i])):
                    break

            func_counter += 1
            if use_code_blocks:
                out.extend(make_doxygen_code_block(sv_pretty_format(block_lines), indent="  "))
            else:
                out.extend(make_doxygen_block(block_lines, indent="  "))

            hdr_parts: List[str] = []
            for bl in block_lines:
                hdr_parts.append(re.sub(r"//.*$", "", bl).strip())
                if ";" in bl:
                    break
            header = re.sub(r"\s+", " ", " ".join(hdr_parts))
            sig = parse_sv_function_signature(header, kind=kind) or f"void {kind}_{func_counter}();"

            out.append(f"  {sig}")
            out.append("")
            i += 1
            continue

        # always blocks
        m_always = re.match(r"^\s*(always_ff|always_comb|always_latch|always)\b", line)
        if m_always:
            kw = m_always.group(1)
            block_lines = [line]
            clean = re.sub(r"//.*$", "", line)

            if re.search(r"\bbegin\b", clean):
                depth = len(re.findall(r"\bbegin\b", clean)) - len(re.findall(r"\bend\b", clean))
                while i + 1 < len(lines) and depth > 0:
                    i += 1
                    block_lines.append(lines[i])
                    clean2 = re.sub(r"//.*$", "", lines[i])
                    depth += len(re.findall(r"\bbegin\b", clean2))
                    depth -= len(re.findall(r"\bend\b", clean2))
            else:
                while i + 1 < len(lines) and ";" not in re.sub(r"//.*$", "", block_lines[-1]):
                    i += 1
                    block_lines.append(lines[i])

            always_counter += 1
            mlabel = re.search(r"\bbegin\s*:\s*(\w+)", block_lines[0])
            label = mlabel.group(1) if mlabel else None

            fname = f"{kw}_{label}" if label else f"{kw}_{always_counter}"
            fname = sanitize_identifier(fname)

            if use_code_blocks:
                out.extend(make_doxygen_code_block(sv_pretty_format(block_lines), indent="  "))
            else:
                out.extend(make_doxygen_block(block_lines, indent="  "))
            out.append(f"  void {fname}();")
            out.append("")
            i += 1
            continue


        # assign
        if re.match(r"^\s*assign\b", line):
            stmt_lines = [line]
            while ";" not in re.sub(r"//.*$", "", stmt_lines[-1]) and i + 1 < len(lines):
                i += 1
                stmt_lines.append(lines[i])

            stmt_clean = " ".join([re.sub(r"//.*$", "", l).strip() for l in stmt_lines])
            stmt_clean = re.sub(r"\s+", " ", stmt_clean).strip()

            assign_counter += 1
            m = re.match(r"assign\s+(.+?)\s*=\s*(.+?)\s*;", stmt_clean)
            lhs = m.group(1).strip() if m else f"lhs_{assign_counter}"
            fname = "assign_" + sanitize_identifier(lhs)

            # Put the SV assign in a Doxygen \code block so it stays readable.
            if use_code_blocks:
                out.extend(make_doxygen_code_block(sv_pretty_format([stmt_clean]), indent="  "))
            else:
                out.append(f"  ///{stmt_clean}")

            out.append(f"  void {fname}();")
            out.append("")
            i += 1
            continue


        # module instantiation -> function
        # Example:
        #   exe #() exe (
        #       .clk_i(clk_i),
        #       ...
        #   );
        # =>
        #   /*! \code <instance> \endcode */
        #   void exe_inst();
        #
        # Heuristic: a statement starting with an identifier, followed by optional
        # parameterization, an instance identifier, then a port list (...), ending with ';'.
        if re.match(r"^\s*[A-Za-z_]\w*\b", line) and "(" in line:
            # Fast reject obvious non-instantiations
            first_tok = re.match(r"^\s*([A-Za-z_]\w*)\b", line).group(1)
            if first_tok not in {
                "if", "for", "foreach", "while", "do", "case", "casez", "casex",
                "unique", "priority", "return", "break", "continue", "disable",
                "begin", "end", "assign", "always", "always_ff", "always_comb", "always_latch",
                "function", "task", "typedef", "module", "package", "generate", "endgenerate",
                "initial", "final", "assert", "assume", "cover", "property", "sequence",
            }:
                stmt_lines, end_idx = collect_statement_until_semicolon(lines, i)
                # Build a compact, comment-free version for header parsing
                stmt_clean = " ".join([strip_line_comment(l).strip() for l in stmt_lines])
                stmt_clean = re.sub(r"\s+", " ", stmt_clean).strip()
                parsed = parse_instance_header(stmt_clean)
                if parsed is not None:
                    mod_type, inst_name = parsed
                    if emit_instance_includes:
                        inst_module_types.add(mod_type)
                    fname = sanitize_identifier(f"{inst_name}_inst")

                    if use_code_blocks:
                        out.extend(make_doxygen_code_block(sv_pretty_format(stmt_lines), indent="  "))
                    else:
                        out.extend(make_doxygen_block(stmt_lines, indent="  "))

                    out.append(f"  void {fname}();")
                    out.append("")
                    i = end_idx + 1
                    continue


        # port declarations: input/output/inout -> variable decl
        m_decl_dir = re.match(r"^\s*(input|output|inout)\b(.*)$", line)
        if m_decl_dir:
            indent = re.match(r"^(\s*)", line).group(1)
            rest = m_decl_dir.group(2).strip()
            rest = re.sub(r"[,\s]*\)?\s*$", "", rest)
            rest = rest.rstrip(";").strip()
            decl = normalize_decl_text(rest).rstrip(",")
            if decl:
                out.append(f"{indent}{decl};")
            i += 1
            continue

        # internal declarations
        if re.match(r"^\s*(wire|logic|reg|bit|byte|shortint|int|longint|integer|genvar|parameter|localparam)\b", line):
            indent = re.match(r"^(\s*)", line).group(1)
            clean = re.sub(r"//.*$", "", line).strip()

            # parameter/localparam -> const
            if clean.startswith("parameter") or clean.startswith("localparam"):
                clean2 = re.sub(r"^(parameter|localparam)\b", "const", clean)
                clean2 = clean2.rstrip(",").rstrip(";").strip()
                clean2 = compact_brackets(re.sub(r"\s+", " ", clean2))
                out.append(f"{indent}{clean2};")
                i += 1
                continue

            # possibly multi-line decl
            if ";" not in clean:
                stmt_lines = [clean]
                while i + 1 < len(lines) and ";" not in stmt_lines[-1]:
                    i += 1
                    stmt_lines.append(re.sub(r"//.*$", "", lines[i]).strip())
                clean = " ".join(stmt_lines)

            clean = clean.rstrip(";").strip()

            mm = re.match(
                r"(?P<type>.+?)\s+(?P<names>[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)?(?:\s*,\s*[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)?)*)$",
                clean,
            )
            if mm:
                typ = compact_brackets(re.sub(r"\s+", " ", mm.group("type")).strip())
                names = mm.group("names")
                for nm in split_top_level_commas(names):
                    nm_clean = compact_brackets(re.sub(r"\s+", "", nm))
                    out.append(f"{indent}{typ} {nm_clean};")
            else:
                clean_sp = compact_brackets(re.sub(r"\s+", " ", clean))
                out.append(f"{indent}{clean_sp};")

            i += 1
            continue

        # Drop module/package keywords (content is handled through the conversions above)
        if re.match(r"^\s*(module|endmodule|package|endpackage)\b", line):
            i += 1
            continue

        # Default: either drop or keep as a non-doxygen comment
        if keep_unknown_as_comment:
            out.append("// " + line.rstrip())
        i += 1

    if wrap_namespace:
        out.append("")
        out.append("} // namespace " + sanitize_identifier(namespace_name or "sv"))
        out.append("")


    # Inject includes for instantiated modules (helps Doxygen include graphs).
    if emit_instance_includes and inst_module_types:
        inc_lines: List[str] = []
        for mt in sorted(inst_module_types):
            target = resolve_instance_include(mt, base_dir, inst_include_ext, inst_include_noext)
            inc_lines.append(f'#include "{target}"')
        out = insert_includes_after_header(out, inc_lines)

    return "\n".join(out) + "\n"


def read_input(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def main() -> int:
    ap = argparse.ArgumentParser(description="SystemVerilog -> pseudo C++ filter for Doxygen.")
    ap.add_argument("input", nargs="?", help="Input .sv/.svh file (if omitted: read stdin).")
    ap.add_argument("--wrap-namespace", action="store_true",
                    help="Wrap output in a C++ namespace (helps avoid global name collisions in Doxygen).")
    ap.add_argument("--namespace", dest="namespace_name", default=None,
                    help="Namespace name to use with --wrap-namespace (default: module/package name if found).")
    ap.add_argument("--keep-unknown", action="store_true",
                    help="Keep unhandled SV lines as plain // comments (otherwise dropped).")
    ap.add_argument("--no-inst-includes", action="store_true",
                    help="Do not emit #include lines for instantiated modules.")
    ap.add_argument("--inst-include-ext", default="auto", choices=["auto", ".sv", ".svh"],
                    help="Extension mode for instance includes (default: auto).")
    ap.add_argument("--inst-include-noext", action="store_true",
                    help="Emit instance includes without extension (e.g. #include \"exe\").")
    ap.add_argument("--no-code-blocks", action="store_true",
                    help="Disable Doxygen \\code blocks for generated SV snippets.")
    args = ap.parse_args()

    src = read_input(args.input)
    sys.stdout.write(
        convert_sv_to_cpp_pseudo(
            src,
            wrap_namespace=args.wrap_namespace,
            namespace_name=args.namespace_name,
            keep_unknown_as_comment=args.keep_unknown,
            use_code_blocks=not args.no_code_blocks,
            input_path=args.input,
            emit_instance_includes=not args.no_inst_includes,
            inst_include_ext=args.inst_include_ext,
            inst_include_noext=args.inst_include_noext,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

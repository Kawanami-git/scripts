#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       sv2cpp.py
# \brief      Convert SystemVerilog to C++-like code for Doxygen documentation.
# \author     Kawanami
# \version    1.0
# \date       03/11/2025
#
# \details
#   This script converts SystemVerilog code into a C++-like format suitable for
#   Doxygen. It preserves Doxygen comments, translates preprocessor directives,
#   normalizes declarations, wraps always/initial/generate blocks into functions,
#   converts typedef enums to C++ enum classes, captures assign statements, and
#   renders module instantiations as C++-like function stubs.
#
#   Additionally, it converts SV hex literals of the form `<bits>'h<HEX>` into
#   `0x<HEX>` inside:
#     - SystemVerilog `` `define ...`` lines as they are translated,
#     - Any already-produced `#define ...` lines encountered in the main loop.
#
# \remarks
#   - The architecture block for ARCHITECTURE/START_ADDR is folded into C++
#     constexprs when the exact pattern is found.
#
# \section sv2cpp_py_version_history Version history
# | Version | Date       | Author   | Description                                |
# |:-------:|:----------:|:--------:|:-------------------------------------------|
# | 1.0     | 03/11/2025 | Kawanami | Initial version.                           |
# | 1.1     | xx/xx/xxxx | Author   |                                            |
# ********************************************************************************
# */

import re, io, sys, collections

# ---------- regexes ----------
re_module_start   = re.compile(r'^\s*module\b')
re_module_end     = re.compile(r'^\s*endmodule\b')
re_param          = re.compile(r'^\s*(parameter|localparam)\b')
re_port           = re.compile(r'^\s*(input|output|inout)\b')
re_internal       = re.compile(r'^\s*(?:wire|reg|logic|bit)\b')
re_begin_label    = re.compile(r'^\s*begin\s*:\s*([A-Za-z_]\w*)\b')
re_label_inline   = re.compile(r'\bbegin\s*:\s*([A-Za-z_]\w*)\b')
re_always         = re.compile(r'^\s*(always(?:_(?:ff|comb|latch))?|initial)\b(.*)$')
re_begin_any      = re.compile(r'\bbegin\b')
re_end_any        = re.compile(r'\bend\b')
re_generate_open  = re.compile(r'^\s*generate\b')
re_generate_close = re.compile(r'^\s*endgenerate\b')
re_tick           = re.compile(r'^\s*`(\w+)(?:\s+(.*))?$')
re_assign_full    = re.compile(r'^\s*assign\s+([A-Za-z_]\w*)\s*=\s*(.+?);')
re_plain_assign_start     = re.compile(r'^\s*assign\b')
re_commented_assign_start = re.compile(r'^\s*//\s*assign\b')
re_function_start = re.compile(r'^\s*function\b')
re_endfunction    = re.compile(r'\bendfunction\b')
re_typedef_enum_kw= re.compile(r'^\s*(?://\s*)?typedef\s+enum\b', re.IGNORECASE)

# Already-translated C-style #define lines
re_c_define   = re.compile(r'^\s*#\s*define\b(?P<rest>.*)$')

# SystemVerilog hex literal: <bits>'h<HEX> (allow spaces and underscores)
re_svhex_cap  = re.compile(r"(?i)\b(\d+)\s*'\s*h\s*([0-9a-f_]+)\b")


# ---------- helpers ----------
def w(out, line=""):
    """Write a line to the output buffer with trailing newline."""
    out.write(line + "\n")


def normalize_spaces(s: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return re.sub(r'\s+', ' ', s).strip()


def normalize_decl_semicolon(line: str) -> str:
    """Ensure declarations end with ';' (replace trailing ',' or append ';')."""
    raw = line.rstrip("\n")
    m = re.split(r'(//.*)$', raw, maxsplit=1)
    code = m[0].rstrip()
    cmt  = m[1] if len(m) > 1 else ""
    if re.search(r';\s*$', code):
        return code + (cmt or "")
    if re.search(r',\s*$', code):
        code = re.sub(r',\s*$', ';', code)
    else:
        code = code + ';'
    return code + (cmt or "")


def strip_block_comments(s: str) -> str:
    """Remove /* ... */ comments."""
    return re.sub(r'/\*.*?\*/', ' ', s, flags=re.DOTALL)


def strip_inline_comments(s: str) -> str:
    """Remove // ... inline comments."""
    return re.sub(r'//.*?(?=$|\n)', '', s)


def cleaned_no_comments(s: str) -> str:
    """Remove both block and inline comments."""
    return strip_inline_comments(strip_block_comments(s))


def replace_svhex_payload(s: str) -> str:
    """
    Replace all SV hex literals in string payload:
      64'hDEAD_BEEF -> 0xDEADBEEF
    (No suffix is added here; purpose is pure SV->C hex.)
    """
    return re_svhex_cap.sub(lambda m: "0x" + m.group(2).replace("_", ""), s)


def sv_to_c_preproc(out, line):
    """
    Convert SystemVerilog preprocessor directives (backtick) to C-style lines.
    Also converts SV hex literals in the payload of `define` to 0x... form.
    """
    m = re_tick.match(line)
    if not m:
        w(out, "// " + line.rstrip())
        return
    kind, rest = m.group(1), (m.group(2) or "").strip()
    k = kind.lower()
    if   k == "ifdef":   w(out, f"#ifdef {rest}")
    elif k == "ifndef":  w(out, f"#ifndef {rest}")
    elif k == "elsif":   w(out, f"#elif {rest}")
    elif k == "else":    w(out, "#else")
    elif k == "endif":   w(out, "#endif")
    elif k == "define":
        fixed = replace_svhex_payload(rest)
        w(out, f"#define {fixed}")
    elif k == "undef":   w(out, f"#undef {rest}")
    elif k == "include": w(out, f"#include {rest}")
    else:                w(out, "// " + "`" + kind + (" " + rest if rest else ""))


def slurp_block(lines, i, end_pred):
    """Collect lines until end_pred returns True for a line (inclusive)."""
    buf, j, n = [], i, len(lines)
    while j < n:
        ln = lines[j]
        buf.append(ln)
        if end_pred(ln):
            j += 1
            break
        j += 1
    return buf, j


def slurp_always(lines, i):
    """
    Collect an always/initial block including nested begin/end.
    Stops when balanced or, for single-line bodies, after the next line.
    """
    buf, depth, j, n = [], 0, i, len(lines)
    saw_begin = False
    while j < n:
        ln = lines[j]
        buf.append(ln)
        begins = len(re_begin_any.findall(ln))
        ends   = len(re_end_any.findall(ln))
        if begins:
            saw_begin = True
        depth += begins
        depth -= ends
        j += 1
        if saw_begin and depth <= 0:
            break
        if not saw_begin and j > i + 1:
            break
    return buf, j


def slurp_generate(lines, i):
    """Collect a full generate ... endgenerate block (supports nesting)."""
    buf, depth, j, n = [], 0, i, len(lines)
    while j < n:
        ln = lines[j]
        if re_generate_open.match(ln):
            depth += 1
        if re_generate_close.match(ln):
            depth -= 1
            buf.append(ln)
            j += 1
            if depth <= 0:
                break
            else:
                continue
        buf.append(ln)
        j += 1
    return buf, j


def pick_generate_name(buf, gen_idx):
    """
    Heuristic to name a generate block using labels found in nested always blocks.
    If none found, return a generic name with an index.
    """
    labels = []
    for k, ln in enumerate(buf):
        ma = re_always.match(ln)
        if ma:
            tail = (ma.group(2) or "")
            inline = re_label_inline.search(tail)
            lab = None
            if inline:
                lab = inline.group(1)
            elif k + 1 < len(buf):
                nx = buf[k + 1].strip()
                m2 = re_begin_label.match(nx)
                if m2:
                    lab = m2.group(1)
            if lab:
                labels.append(lab)
    if labels:
        return collections.Counter(labels).most_common(1)[0][0]
    return f"gen_block_{gen_idx}"


def join_until_semicolon_for_assign(lines, i, strip_leading_comment=False):
    """
    Join assignment lines across multiple lines until a semicolon is found.
    Optionally strip leading '//' from each line before joining.
    """
    buf, j, n = [], i, len(lines)
    while j < n:
        ln = lines[j]
        if strip_leading_comment and ln.lstrip().startswith('//'):
            ln = ln.lstrip()[2:]
        buf.append(ln.rstrip())
        if ';' in ln:
            j += 1
            break
        j += 1
    text = "\n".join(buf)
    text = cleaned_no_comments(text)
    text = normalize_spaces(text)
    return text, j


# ---------- typedef enum handling ----------
def slurp_typedef_enum(lines, i):
    """
    Slurp a typedef enum block, compute bit width if present, and emit a
    C++ 'enum class <name> : <uint{8,16,32}_t> { ... };'.
    """
    buf, j, n, typedef_found = [], i, len(lines), False
    while j < n:
        raw = lines[j]
        buf.append(raw.rstrip())
        if re.search(r'\}\s*[A-Za-z_]\w*\s*;', raw):
            j += 1
            typedef_found = True
            break
        j += 1
    if not typedef_found:
        return None, i + 1, None

    text = "\n".join(buf)
    text_nocmt = re.sub(r'^\s*//\s*', '', text, flags=re.MULTILINE)

    width_m = re.search(r'enum\s*(?:reg|logic)?\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]', text_nocmt)
    if width_m:
        msb = int(width_m.group(1))
        lsb = int(width_m.group(2))
        bits = abs(msb - lsb) + 1
    else:
        bits = 32

    if bits <= 8:
        ctype = "uint8_t"
    elif bits <= 16:
        ctype = "uint16_t"
    else:
        ctype = "uint32_t"

    body_m = re.search(r'enum\b.*?\{(.*?)\}', text_nocmt, flags=re.DOTALL)
    if body_m:
        body = body_m.group(1)
        items = [normalize_spaces(x).strip() for x in body.split(',') if normalize_spaces(x).strip()]
    else:
        items = []

    name_m = re.search(r'\}\s*([A-Za-z_]\w*)\s*;', text_nocmt)
    typedef_name = name_m.group(1) if name_m else f"enum_{i}"

    cpp = io.StringIO()
    w(cpp, f"enum class {typedef_name} : {ctype} {{")
    if items:
        for k, it in enumerate(items):
            it = re.sub(r'\s+', ' ', it).rstrip(',')
            w(cpp, f"  {it}{',' if k < len(items)-1 else ''}")
    w(cpp, "};")
    return cpp.getvalue(), j, typedef_name


# ---------- Instantiations ----------
def slurp_instantiation(lines, i):
    """
    Parse a potential module instantiation and return:
      (ok, next_index, module_name, instance_name, collected_buffer)
    Uses a bounded lookahead to avoid runaway on malformed input.
    """
    n = len(lines)
    j = i
    header_lines = []
    scan_limit = min(i + 300, n)

    # Skip leading blanks/comments
    while j < scan_limit and j < n:
        ln = lines[j]
        if cleaned_no_comments(ln).strip():
            break
        header_lines.append(ln.rstrip())
        j += 1
    if j >= n:
        return (False, i + 1, None, None, None)

    state = "mod"
    mod = None
    inst = None

    while j < scan_limit and j < n:
        ln = lines[j]
        header_lines.append(ln.rstrip())
        txt = cleaned_no_comments("\n".join(header_lines))

        if state == "mod":
            m = re.match(r'^\s*([A-Za-z_]\w*)\b', txt)
            if not m:
                return (False, i + 1, None, None, None)
            mod = m.group(1)
            if mod in ("input","output","inout","wire","reg","logic","bit",
                       "assign","function","typedef","parameter","localparam",
                       "always","initial","generate","endgenerate","module","endmodule"):
                return (False, i + 1, None, None, None)
            state = "maybe_params"

        if state == "maybe_params":
            after_mod = txt[len(mod):]
            if "#(" in after_mod and txt.count("(") >= 1:
                idx = after_mod.find("#(")
                sub = after_mod[idx+1:]
                depth = 0
                for ch in sub:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                        if depth == 0:
                            state = "need_inst"
                            break
                if state != "need_inst":
                    j += 1
                    continue
            else:
                state = "need_inst"

        if state == "need_inst":
            m2 = re.search(r'(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?([A-Za-z_]\w*)\s*\(\s*$', txt, flags=re.DOTALL)
            if m2:
                inst = m2.group(1)
                state = "ports"
                j += 1
                break
            else:
                if ';' in txt and '(' not in txt.split(';')[-1]:
                    return (False, i + 1, None, None, None)
                j += 1
                continue

    if state != "ports" or inst is None:
        return (False, i + 1, None, None, None)

    ports_lines = []
    depth = 1
    while j < n:
        ln = lines[j]
        ports_lines.append(ln.rstrip())
        cl = cleaned_no_comments(ln)
        for ch in cl:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
        j += 1
        if depth <= 0:
            joined = cleaned_no_comments("\n".join(ports_lines))
            if re.search(r'\)\s*;\s*$', joined):
                break

    if depth > 0:
        return (False, i + 1, None, None, None)

    buf = header_lines + ports_lines
    return (True, j, mod, inst, buf)


# ---------- ARCH block conversion ----------
def sv_hex_to_c(sv_hex: str, width_hint_bits: int = None) -> str:
    """
    Convert a SV literal like 64'h0000_8000 to a C hex literal.
    Choose suffix U/ULL depending on width hint if provided.
    """
    m = re.match(r"(?i)^\s*(\d+)\s*'\s*h\s*([0-9a-f_]+)\s*$", sv_hex)
    if not m:
        sv_hex = sv_hex.strip()
        if sv_hex.lower().startswith("0x"):
            return sv_hex
        try:
            v = int(sv_hex, 10)
            if width_hint_bits and width_hint_bits > 32:
                return f"{v}ULL"
            return f"{v}u"
        except ValueError:
            return sv_hex
    bits = int(m.group(1))
    hexpart = m.group(2).replace("_", "")
    v = int(hexpart, 16)
    if bits > 32:
        return f"0x{v:0{(bits+3)//4}x}ULL"
    else:
        return f"0x{v:0{(bits+3)//4}x}u"

# ---------- main filter ----------
def filter_text(text: str) -> str:
    """
    Main transformation pipeline over the input text.
    """
    out = io.StringIO()
    lines = text.splitlines()
    i, n = 0, len(lines)
    gen_idx = 1
    pending_doxy = None
    typedef_names = set()
    in_doxy = False

    def flush_pending_doxy():
        nonlocal pending_doxy
        if pending_doxy is not None:
            w(out, pending_doxy)
            pending_doxy = None

    while i < n:
        line = lines[i]
        s = line.strip()

        # --- Doxygen block state handling ---
        if in_doxy:
            w(out, line.rstrip())
            if "*/" in s:
                in_doxy = False
            i += 1
            continue
        else:
            if s.startswith("/*!") or s.startswith("/**"):
                flush_pending_doxy()
                in_doxy = True
                w(out, line.rstrip())
                i += 1
                continue

        # Buffer doxygen "///"
        if s.startswith("///"):
            pending_doxy = line.rstrip()
            i += 1
            continue

        # Backticks -> C preprocessor
        if s.startswith("`"):
            flush_pending_doxy()
            sv_to_c_preproc(out, line)
            i += 1
            continue

        # Already commented lines: keep as-is
        if line.lstrip().startswith("//"):
            flush_pending_doxy()
            w(out, line.rstrip())
            i += 1
            continue

        # Convert any #define ... lines: replace SV hex with 0x...
        m_def = re_c_define.match(line)
        if m_def:
            flush_pending_doxy()
            rest = m_def.group('rest').strip()
            fixed = replace_svhex_payload(rest)
            w(out, f"#define {fixed}")
            i += 1
            continue

        # module/endmodule -> comment only
        if re_module_start.match(line) or re_module_end.match(line):
            flush_pending_doxy()
            w(out, "// " + line.rstrip())
            i += 1
            continue

        # typedef enum (even if commented)
        if re_typedef_enum_kw.match(line):
            flush_pending_doxy()
            cpp, j2, tname = slurp_typedef_enum(lines, i)
            if cpp:
                w(out, cpp.rstrip())
                typedef_names.add(tname)
                i = j2
                continue
            w(out, "// " + line.strip())
            i += 1
            continue

        # Declarations that use converted enum class types
        if typedef_names:
            stripped = re.sub(r'^\s*//\s*', '', line)
            m_typedef_var = re.match(
                r'^\s*(?:' + '|'.join(map(re.escape, typedef_names)) + r')\s+([A-Za-z_]\w*)\s*;',
                stripped
            )
            if m_typedef_var:
                flush_pending_doxy()
                tmatch = re.match(r'^\s*(?:' + '|'.join(map(re.escape, typedef_names)) + r')', stripped)
                tname = tmatch.group(0)
                vname = m_typedef_var.group(1)
                w(out, f"{tname} {vname};")
                i += 1
                continue

        # generate block
        if re_generate_open.match(line):
            flush_pending_doxy()
            buf, j = slurp_generate(lines, i)
            fname = pick_generate_name(buf, gen_idx); gen_idx += 1
            w(out, f"void {fname}() {{")
            w(out, "  // generate block (original SV below)")
            for b in buf:
                w(out, "  // " + b.rstrip())
            w(out, "}")
            # Scan instantiations inside generate
            k, L = 0, len(buf)
            used_names = set()
            while k < L:
                ok, j2, mod, inst, ibuf = slurp_instantiation(buf, k)
                if ok:
                    fn = inst
                    if fn in used_names:
                        suffix = 2
                        while f"{fn}_{suffix}" in used_names:
                            suffix += 1
                        fn = f"{fn}_{suffix}"
                    used_names.add(fn)
                    w(out, f"void {fn}() {{")
                    w(out, "  // module instantiation (original SV below)")
                    for lb in ibuf:
                        w(out, "  // " + lb.rstrip())
                    w(out, "}")
                    k = j2
                else:
                    k += 1
            i = j
            continue

        # always/initial
        ma = re_always.match(line)
        if ma:
            flush_pending_doxy()
            tail = (ma.group(2) or "")
            label = None
            inline = re_label_inline.search(tail)
            if inline:
                label = inline.group(1)
            else:
                if i + 1 < n:
                    nx = lines[i + 1].strip()
                    m2 = re_begin_label.match(nx)
                    if m2:
                        label = m2.group(1)
            if not label:
                kw = ma.group(1)
                label = {
                    "always_ff":"always_ff",
                    "always_comb":"always_comb",
                    "always_latch":"always_latch",
                    "initial":"initial"
                }.get(kw, "always")
            buf, j = slurp_always(lines, i)
            w(out, f"void {label}() {{")
            head = buf[0].rstrip()
            w(out, "  // original: " + head)
            for b in buf[1:]:
                w(out, "  // " + b.rstrip())
            w(out, "}")
            i = j
            continue

        # function … endfunction
        if re_function_start.match(line):
            flush_pending_doxy()
            buf, j = slurp_block(lines, i, lambda ln: re_endfunction.search(ln) is not None)
            header = buf[0]
            header_nc = cleaned_no_comments(header)
            mname = re.search(r'\bfunction\b.*?\b([A-Za-z_]\w*)\s*\(', header_nc)
            fname = mname.group(1) if mname else f"sv_function_{i}"
            w(out, f"void {fname}() {{")
            w(out, "  // function block (original SV below)")
            for b in buf:
                w(out, "  // " + b.rstrip())
            w(out, "}")
            i = j
            continue

        # Instantiation (outside generate)
        ok_inst, j_inst, mod, inst, ibuf = slurp_instantiation(lines, i)
        if ok_inst:
            flush_pending_doxy()
            w(out, f"void {inst}() {{")
            w(out, "  // module instantiation (original SV below)")
            for lb in ibuf:
                w(out, "  // " + lb.rstrip())
            w(out, "}")
            i = j_inst
            continue

        # Params/ports/internals -> force ';'
        if re_param.match(line) or re_port.match(line) or re_internal.match(line):
            flush_pending_doxy()
            out_line = normalize_decl_semicolon(line)
            w(out, out_line.rstrip())
            i += 1
            continue

        # Assigns (single-line)
        m_as = re_assign_full.match(line)
        if m_as:
            lhs, rhs = m_as.group(1), m_as.group(2)
            w(out, f"/// assign {lhs} = {rhs};\\n")
            if pending_doxy is not None:
                w(out, pending_doxy)
                pending_doxy = None
            w(out, f"void assign_{lhs}();")
            i += 1
            continue

        # Assigns (multi-line / commented)
        if re_plain_assign_start.match(line):
            joined_assign, j2 = join_until_semicolon_for_assign(lines, i, strip_leading_comment=False)
            m2 = re.match(r'\bassign\s+([A-Za-z_]\w*)\s*=\s*(.*);', joined_assign)
            if m2:
                lhs, rhs = m2.group(1), m2.group(2)
                w(out, f"/// assign {lhs} = {rhs};\\n")
                if pending_doxy is not None:
                    w(out, pending_doxy)
                    pending_doxy = None
                w(out, f"void assign_{lhs}();")
                i = j2
                continue

        if re_commented_assign_start.match(line):
            joined_assign, j2 = join_until_semicolon_for_assign(lines, i, strip_leading_comment=True)
            m3 = re.match(r'\bassign\s+([A-Za-z_]\w*)\s*=\s*(.*);', joined_assign)
            if m3:
                lhs, rhs = m3.group(1), m3.group(2)
                w(out, f"/// assign {lhs} = {rhs};\\n")
                if pending_doxy is not None:
                    w(out, pending_doxy)
                    pending_doxy = None
                w(out, f"void assign_{lhs}();")
                i = j2
                continue

        # Blank line passthrough
        if s == "":
            flush_pending_doxy()
            w(out, "")
            i += 1
            continue

        # Default: comment original SV line
        flush_pending_doxy()
        w(out, "// " + s)
        i += 1

    flush_pending_doxy()
    return out.getvalue()


def main():
    data = sys.stdin.read() if len(sys.argv) == 1 else open(sys.argv[1], 'r', encoding='utf-8').read()
    sys.stdout.write(filter_text(data))


if __name__ == "__main__":
    main()

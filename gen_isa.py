# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       gen_isa.py
# \brief      Generate assembly code from an ISA test YAML description
# \author     Kawanami
# \version    1.0
# \date       03/11/2025
#
# \details
#  This script reads an ISA test description in YAML format and generates an
#  assembly (.s) file for a specified RISC-V architecture (XLEN32 or XLEN64).
#  The script supports the generation of test sequences with random values
#  and can handle different memory configurations specified in the YAML file.
#
#  The output is a valid assembly file that can be processed by a RISC-V
#  simulator or emulator. The test sequences are generated according to the
#  instructions in the YAML file and include data sections, instruction sequences,
#  and setup code for testing.
#
# \remarks
#  - The script requires the PyYAML library for YAML parsing (`pip install pyyaml`).
#  - It supports iterations of the test sequence for repeated testing.
#
# \section gen_isa_py_version_history Version history
# | Version | Date       | Author     | Description                               |
# |:-------:|:----------:|:-----------|:------------------------------------------|
# | 1.0     | 03/11/2025 | Kawanami   | Initial version.                          |
# ********************************************************************************
# */

from pathlib import Path
import yaml
import argparse
import random

# Register pool excluding the x0 register (which is hardwired to zero)
REG_POOL = [f'x{i}' for i in range(1, 32)]  # x0 is hardwired to zero

def parse_args():
    """
    Parse command-line arguments for the ISA test generator script.

    Returns:
        argparse.Namespace: Parsed command-line arguments
    """
    parser = argparse.ArgumentParser(description="ISA test YAML to .s generator")
    parser.add_argument("--yaml", required=True, help="YAML test file path")
    parser.add_argument("--archi", required=True, type=str, choices=["XLEN32", "XLEN64"], help="Target architecture")
    parser.add_argument("--iteration", type=int, default=1, help="Number of iterations")
    parser.add_argument("--out", required=True, help="Output .s file path")
    return parser.parse_args()

def load_yaml(filepath):
    """
    Load and parse a YAML file.

    Args:
        filepath (str): Path to the YAML file.

    Returns:
        dict: Parsed YAML data.
    """
    with open(filepath, 'r') as f:
        return yaml.safe_load(f)

def parse_memory_config(requires):
    """
    Parse memory configuration from the 'requires' field in the YAML file.

    Args:
        requires (list): List of required configurations from the YAML data.

    Returns:
        tuple: Starting address and memory size (both in bytes).
    """
    start, size = None, None
    for entry in requires:
        if isinstance(entry, str):
            if entry.startswith("mem-data-start="):
                start = int(entry.split("=")[1], 16)
            elif entry.startswith("mem-data-size="):
                size_str = entry.split("=")[1].upper()
                if size_str.endswith("K"):
                    size = int(size_str[:-1]) * 1024
                elif size_str.endswith("M"):
                    size = int(size_str[:-1]) * 1024 * 1024
                else:
                    size = int(size_str)
    return start, size

def alloc_random_reg(used_regs, alias_map, alias):
    """
    Allocate a random register that is not already used.

    Args:
        used_regs (set): Set of already used registers.
        alias_map (dict): Mapping of aliases to register names.
        alias (str): The alias to be allocated.

    Returns:
        str: The allocated register name.
    """
    available = list(set(REG_POOL) - used_regs)
    if not available:
        raise ValueError("No available registers to allocate.")
    reg = random.choice(available)
    alias_map[alias] = reg
    used_regs.add(reg)
    return reg

def format_value(val):
    """
    Format a value as a string, either as a decimal or hexadecimal.

    Args:
        val (int): The value to format.

    Returns:
        str: The formatted value as a string.
    """
    if -2048 <= val <= 2047:
        return str(val)
    else:
        return f"0x{val:X}"

def resolve_operand(op, alias_map, used_regs, yaml_data=None):
    """
    Resolve an operand, which could be a register, immediate value, or random value.

    Args:
        op (str, dict): The operand, which may be a dictionary for random values or a string.
        alias_map (dict): Mapping of aliases to registers.
        used_regs (set): Set of already used registers.
        yaml_data (dict, optional): The YAML data, used for memory alignment requirements.

    Returns:
        str: The resolved operand as a string.
    """
    requires = yaml_data.get("requires", []) if yaml_data else []

    # Handle random operand generation
    if isinstance(op, dict) and "random" in op:
        bounds = op["random"]
        min_val = int(bounds["min"], 0) if isinstance(bounds["min"], str) else bounds["min"]
        max_val = int(bounds["max"], 0) if isinstance(bounds["max"], str) else bounds["max"]

        # Handle memory alignment based on requirements
        if "mem-aligned-8" in requires:
            min_val = (min_val + 7) & ~0b111
            max_val = max_val & ~0b111
            if min_val > max_val:
                raise ValueError("Invalid memory-aligned range")
            val = random.randrange(min_val, max_val + 1, 8)
        elif "mem-aligned-4" in requires:
            min_val = (min_val + 3) & ~0b11
            max_val = max_val & ~0b11
            if min_val > max_val:
                raise ValueError("Invalid memory-aligned range")
            val = random.randrange(min_val, max_val + 1, 4)
        elif "mem-aligned-2" in requires:
            min_val = (min_val + 1) & ~0b1
            max_val = max_val & ~0b1
            if min_val > max_val:
                raise ValueError("Invalid memory-aligned range")
            val = random.randrange(min_val, max_val + 1, 2)
        else:
            val = random.randint(min_val, max_val)

        return format_value(val)

    # Handle other types of operands (registers, constants, aliases)
    elif isinstance(op, str):
        if op.startswith("random "):
            alias = op.split()[1]
            return alloc_random_reg(used_regs, alias_map, alias)
        elif op in alias_map:
            return alias_map[op]
        elif op.startswith("x"):
            if op in used_regs:
                raise ValueError(f"Register collision: {op} already used.")
            used_regs.add(op)
            return op
        elif op == "random":
            val = random.randint(-2048, 2047)
            if "mem-aligned-8" in requires:
                val = val & ~0b111
            if "mem-aligned-4" in requires:
                val = val & ~0b11
            elif "mem-aligned-2" in requires:
                val = val & ~0b1
            return format_value(val)
        else:
            try:
                val = int(op, 0)
                return format_value(val)
            except ValueError:
                return op

    return str(op)

def generate_instruction(instr, alias_map, used_regs, yaml_data=None):
    """
    Generate a single instruction in assembly format from a YAML instruction.

    Args:
        instr (dict): Instruction data from YAML.
        alias_map (dict): Map of alias registers.
        used_regs (set): Set of already used registers.
        yaml_data (dict, optional): The YAML data for resolving operands.

    Returns:
        str: The generated assembly line for the instruction.
    """
    if 'label' in instr:
        return f"{instr['label']}:"

    op = instr['op']
    alias_map["__current_op"] = op

    context = {'op': op}
    for field in ['rd', 'rs1', 'rs2', 'imm', 'offset']:
        if field in instr:
            context[field] = resolve_operand(instr[field], alias_map, used_regs, yaml_data)
        else:
            context[field] = None

    if 'format' in instr:
        return "    " + instr['format'].format(**context)

    operands = [v for v in [context[f] for f in ['rd', 'rs1', 'rs2', 'imm', 'offset']] if v is not None]
    return f"    {op} " + ", ".join(map(str, operands))

def generate_data_section(yaml_data, archi):
    """
    Generate the data section for the assembly, including data initialization.

    Args:
        yaml_data (dict): Parsed YAML data.
        archi (str): Architecture type ("XLEN32" or "XLEN64").

    Returns:
        list[str]: List of lines for the data section of the assembly.
    """
    requires = yaml_data.get("requires", [])
    start_addr, total_bytes = parse_memory_config(requires)

    word_size = 4 if archi == "XLEN32" else 8
    dir_word  = ".word" if word_size == 4 else ".dword"
    hex_width = 8 if word_size == 4 else 16

    lines = [
        ".section .data",
        ".global data",
        f".balign {word_size}",
        "",
        "tohost:   .dword 0",
        "fromhost: .dword 0",
        "data:"
    ]

    if start_addr is not None and total_bytes is not None:
        addr = start_addr
        end  = start_addr + total_bytes

        if addr % word_size != 0:
            addr = (addr + (word_size - 1)) & ~(word_size - 1)

        while addr + word_size <= end:
            value = random.getrandbits(32 if word_size == 4 else 64)
            lines.append(f"    {dir_word} 0x{value:0{hex_width}X}")
            addr += word_size

        while addr < end:
            lines.append(f"    .byte 0x{random.getrandbits(8):02X}")
            addr += 1

    return lines

def generate_asm(yaml_data, archi, iterations):
    """
    Generate the full assembly code based on the YAML configuration.

    Args:
        yaml_data (dict): Parsed YAML data.
        archi (str): Architecture type ("XLEN32" or "XLEN64").
        iterations (int): Number of iterations for the test.

    Returns:
        str: The generated assembly code.
    """
    asm_lines = [
        ".section .text.start, \"ax\", @progbits", ".globl _start", "_start:",
        "    # Clear registers that Spike sets",
        "    addi x5, x0, 0",
        "    addi x10, x0, 0",
        "    addi x11, x0, 0"
    ]

    if "fix-iteration" in yaml_data.get("requires", []):
        iterations = 1

    # Select architecture-specific or fallback sequence
    seq_key = "rv32" if archi == "XLEN32" else "rv64"
    sequence = yaml_data.get(seq_key, {}).get("sequence")
    if not sequence:
        sequence = yaml_data.get("sequence")
        if not sequence:
            return None

    for i in range(iterations):
        asm_lines.append(f"    # Iteration {i+1}")
        alias_map = {}
        used_regs = set()
        for instr in sequence:
            line = generate_instruction(instr, alias_map, used_regs, yaml_data)
            asm_lines.append(line)

    asm_lines += [
        "    # End of test sequence",
        "    la t1, tohost",
        "    li t2, 1",
        "    sw t2, 0(t1)",
        "    ebreak",
        "",
        "exit_loop:",
        "    j exit_loop"
    ]

    asm_lines += generate_data_section(yaml_data, archi)
    return "\n".join(asm_lines)

if __name__ == "__main__":
    """
    Main entry point for the script. Parses the arguments, loads the YAML data,
    generates the assembly, and writes it to the output file.
    """
    args = parse_args()
    yaml_data = load_yaml(args.yaml)
    asm_output = generate_asm(yaml_data, args.archi, args.iteration)
    if asm_output != None:
        Path(args.out).write_text(asm_output + "\n")
    print(f"Assembly generated and written to {args.out}")

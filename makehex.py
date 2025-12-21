# SPDX-License-Identifier: MIT
# /*!
# ********************************************************************************
# \file       makehex.py
# \brief      Convert an ELF firmware into a flat hex stream: "addr:word" per line.
# \author     Kawanami
# \version    1.0
# \date       26/10/2025
#
# \details
#  Reads an ELF file and emits text lines of the form:
#      addr_hex:word_hex
#  suitable for the SCHOLAR RISC-V loader. Code sections are chunked with a
#  configurable word size (default 4B). Data sections default to 4B for ELF32
#  and 8B for ELF64 unless overridden. BSS (SHT_NOBITS) sections are skipped.
#
#  Byte order: words are printed in little-endian (bytes reversed in the hex
#  word). All-zero words are omitted by default.
#
# \remarks
#  - Requires pyelftools (`pip install pyelftools`).
#  - Address width can be forced to 32 or 64 bits; otherwise auto-selects based
#    on ELF class.
#  - Intended output is consumed by `load_firmware()` which expects "addr:data"
#    lines.
#
# \section makehex_py_version_history Version history
# | Version | Date       | Author     | Description                               |
# |:-------:|:----------:|:-----------|:------------------------------------------|
# | 1.0     | 26/10/2025 | Kawanami   | Initial version.                          |
# ********************************************************************************
# */

from elftools.elf.elffile import ELFFile
from elftools.elf.constants import SH_FLAGS
import argparse

def is_memory_section(section):
    """
    Check if the given ELF section is a memory section (i.e., can be allocated).

    Args:
        section (elftools.elf.sections.Section): The ELF section to check.

    Returns:
        bool: True if the section is a memory section, False otherwise.
    """
    return bool(section['sh_flags'] & SH_FLAGS.SHF_ALLOC)

def is_code_section(section):
    """
    Check if the given ELF section is a code section (i.e., contains executable code).

    Args:
        section (elftools.elf.sections.Section): The ELF section to check.

    Returns:
        bool: True if the section is a code section, False otherwise.
    """
    return bool(section['sh_flags'] & SH_FLAGS.SHF_EXECINSTR)

def is_bss_section(section):
    """
    Check if the given ELF section is a BSS section (i.e., uninitialized data).

    Args:
        section (elftools.elf.sections.Section): The ELF section to check.

    Returns:
        bool: True if the section is a BSS section, False otherwise.
    """
    return section['sh_type'] == 'SHT_NOBITS' or section['sh_type'] == 8  # 8 = SHT_NOBITS

def extract_entries(section, step):
    """
    Extract memory entries (address and word) from an ELF section.

    Args:
        section (elftools.elf.sections.Section): The ELF section to extract data from.
        step (int): The step size (word size in bytes) for reading the section.

    Returns:
        list: A list of tuples, each containing an address and the corresponding word in hexadecimal format.
    """
    addr = section['sh_addr']
    data = section.data()
    entries = []

    # Iterate over the data in chunks of size 'step'
    for i in range(0, len(data), step):
        chunk = data[i:i+step]
        if len(chunk) < step:
            chunk += b'\x00' * (step - len(chunk))

        # Little-endian: reverse the bytes in the word for correct output
        hexword = ''.join(f"{b:02x}" for b in reversed(chunk))

        # Skip zero words (optional, can be removed if you want to emit all words)
        if hexword != "0" * (step * 2):
            entries.append((addr, hexword))

        addr += step

    return entries

def main():
    """
    Main function that parses the ELF file and generates the flat hex stream
    in the format "addr:word" for use with the SCHOLAR RISC-V loader.
    """
    p = argparse.ArgumentParser(description="ELF -> .hex (addr:word)")
    p.add_argument("elf", help="firmware.elf")
    p.add_argument("--data-step", type=int, choices=[1,2,4,8], default=None,
                   help="Word size for data sections (in bytes). Default: auto (ELF32->4, ELF64->8)")
    p.add_argument("--code-step", type=int, choices=[1,2,4,8], default=4,
                   help="Word size for code sections (in bytes). Default: 4")
    p.add_argument("--addr-width", choices=["auto","32","64"], default="auto",
                   help="Address width in bits for printing. Default: auto (ELF32->32, ELF64->64)")
    args = p.parse_args()

    # Open ELF file and parse it
    with open(args.elf, 'rb') as f:
        elf = ELFFile(f)

        # Automatically set word size for data sections based on ELF class
        auto_data_step = 8 if elf.elfclass == 64 else 4
        data_step = args.data_step if args.data_step is not None else auto_data_step
        code_step = args.code_step

        # Determine address width for printing
        if args.addr_width == "auto":
            addr_hex_width = 16 if elf.elfclass == 64 else 8
            addr_mask = (1 << (64 if elf.elfclass == 64 else 32)) - 1
        elif args.addr_width == "64":
            addr_hex_width = 16
            addr_mask = (1 << 64) - 1
        else:  # "32"
            addr_hex_width = 8
            addr_mask = (1 << 32) - 1

        all_entries = []

        # Iterate over sections in the ELF file
        for section in elf.iter_sections():
            # Skip non-memory or BSS sections
            if not is_memory_section(section):
                continue
            if is_bss_section(section):
                continue

            # Select the word size based on the section type
            step = code_step if is_code_section(section) else data_step
            entries = extract_entries(section, step)
            all_entries.extend(entries)

        # Sort entries by address
        all_entries.sort(key=lambda x: x[0])

        # Print the resulting address:word hex stream
        for addr, word in all_entries:
            addr &= addr_mask  # Apply address mask (to ensure correct width)
            print(f"{addr:0{addr_hex_width}x}:{word}")

if __name__ == "__main__":
    """
    Entry point of the script. Parses arguments, processes the ELF file,
    and prints the resulting hex stream.
    """
    main()

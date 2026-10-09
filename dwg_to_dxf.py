#!/usr/bin/env python3
"""
Convert a DWG file to DXF for processing by the floor-plan extractor.

This script looks for common CAD conversion tools:
- dwg2dxf (ODA/LibreDWG-compatible tools)
- ODAFileConverter.exe
- AutoCAD-based conversion if exposed via CLI

Usage:
    python dwg_to_dxf.py "C:\\Users\\ahmed\\OneDrive\\Desktop\\Drawing1.dwg" --out "Drawing1.dxf"
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_executable(names):
    for name in names:
        result = shutil.which(name)
        if result:
            return result
    return None


def convert_with_dwg2dxf(input_path: Path, output_path: Path):
    exe = find_executable(["dwg2dxf", "dwg2dxf.exe", "ODAFileConverter", "ODAFileConverter.exe"])
    if not exe:
        return False, "No supported DWG-to-DXF converter found on PATH"

    cmd = [exe, str(input_path), str(output_path)]
    try:
        subprocess.run(cmd, check=True)
        return True, str(output_path)
    except subprocess.CalledProcessError as exc:
        return False, f"Conversion failed with exit code {exc.returncode}"


def convert_with_oda_file_converter(input_path: Path, output_path: Path):
    candidates = [
        r"C:\\Program Files\\ODA\\ODAFileConverter\\ODAFileConverter.exe",
        r"C:\\Program Files (x86)\\ODA\\ODAFileConverter\\ODAFileConverter.exe",
        r"C:\\Program Files\\ODAFileConverter\\ODAFileConverter.exe",
        r"C:\\Program Files (x86)\\ODAFileConverter\\ODAFileConverter.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            cmd = [path, str(input_path), str(output_path)]
            try:
                subprocess.run(cmd, check=True)
                return True, str(output_path)
            except subprocess.CalledProcessError as exc:
                return False, f"ODA conversion failed with exit code {exc.returncode}"
    return False, "ODAFileConverter.exe was not found"


def convert_dwg_to_dxf(input_path: Path, output_path: Path):
    # try common converter tools first
    for fn in [convert_with_dwg2dxf, convert_with_oda_file_converter]:
        ok, result = fn(input_path, output_path)
        if ok:
            return True, result

    return False, (
        "No compatible DWG-to-DXF converter is available.\n"
        "Install one of:\n"
        "  - ODA File Converter\n"
        "  - dwg2dxf / libredwg tools\n"
        "  - AutoCAD with command-line export support\n"
        "Then rerun this script."
    )


def main():
    parser = argparse.ArgumentParser(description="Convert DWG to DXF before floor-plan extraction.")
    parser.add_argument("dwg_path", help="Input DWG file path")
    parser.add_argument("--out", dest="out_path", default=None, help="Output DXF file path")
    args = parser.parse_args()

    input_path = Path(args.dwg_path)
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    if input_path.suffix.lower() != ".dwg":
        print(f"Expected a DWG file, got: {input_path}")
        sys.exit(1)

    out_path = Path(args.out_path) if args.out_path else input_path.with_suffix(".dxf")
    ok, result = convert_dwg_to_dxf(input_path, out_path)
    if ok:
        print(f"Converted successfully: {result}")
        return 0

    print(result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

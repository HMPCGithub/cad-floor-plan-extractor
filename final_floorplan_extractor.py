#!/usr/bin/env python3
"""
Final floor plan extractor for the detected DXF structure.

This version is tuned to the real drawing you inspected:
- Embedded block in modelspace
- walls live in WALL / block walls layers
- doors live in DOOR-AR
- windows live in WIN
- dimensions live in DIM-IN-AR

Usage:
    python final_floorplan_extractor.py "C:\Users\ahmed\OneDrive\Desktop\cad-floor-plan-extractor-main\Drawing1.dxf" --output "C:\temp\floorplan_report.xlsx"
"""

import argparse
import sys
from pathlib import Path

import ezdxf
import pandas as pd
from shapely.geometry import Polygon


def extract_rooms(block_entities):
    rooms = []
    room_id = 1

    for entity in block_entities:
        if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            continue
        layer = entity.dxf.layer
        if layer not in ("WALL", "block walls"):
            continue
        if not getattr(entity, "closed", False):
            continue

        pts = [(float(p[0]), float(p[1])) for p in entity]
        if len(pts) < 3:
            continue

        try:
            poly = Polygon(pts)
            if poly.is_valid and poly.area > 0:
                rooms.append({
                    "Room_ID": room_id,
                    "Room_Name": f"Room_{room_id}",
                    "Layer": layer,
                    "Floor_Area_m2": round(poly.area, 2),
                    "Perimeter_m": round(poly.length, 2),
                    "Gross_Wall_Area_m2": round(poly.length * 0.15, 2),
                })
                room_id += 1
        except Exception:
            pass

    return rooms


def extract_doors(block_entities):
    doors = []
    for entity in block_entities:
        if entity.dxftype() == "INSERT" and entity.dxf.layer == "DOOR-AR":
            doors.append({
                "block": entity.dxf.name,
                "x": entity.dxf.insert[0],
                "y": entity.dxf.insert[1],
                "rotation": entity.dxf.rotation,
            })
    return doors


def extract_windows(block_entities):
    windows = []
    for entity in block_entities:
        if entity.dxftype() == "INSERT" and entity.dxf.layer == "WIN":
            windows.append({
                "block": entity.dxf.name,
                "x": entity.dxf.insert[0],
                "y": entity.dxf.insert[1],
                "rotation": entity.dxf.rotation,
            })
    return windows


def extract_dimensions(block_entities):
    dims = []
    for entity in block_entities:
        if entity.dxftype() == "DIMENSION":
            dims.append({
                "layer": entity.dxf.layer,
                "text": getattr(entity, "text", ""),
                "x": getattr(entity.dxf, "definition_point", (0, 0, 0))[0],
                "y": getattr(entity.dxf, "definition_point", (0, 0, 0))[1],
            })
    return dims


def export_excel(output_path: str, rooms, doors, windows, dimensions):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if rooms:
        room_df = pd.DataFrame(rooms)
    else:
        room_df = pd.DataFrame(columns=[
            "Room_ID", "Room_Name", "Layer", "Floor_Area_m2", "Perimeter_m", "Gross_Wall_Area_m2"
        ])

    if doors:
        door_df = pd.DataFrame(doors)
    else:
        door_df = pd.DataFrame(columns=["block", "x", "y", "rotation"])

    if windows:
        win_df = pd.DataFrame(windows)
    else:
        win_df = pd.DataFrame(columns=["block", "x", "y", "rotation"])

    if dimensions:
        dim_df = pd.DataFrame(dimensions)
    else:
        dim_df = pd.DataFrame(columns=["layer", "text", "x", "y"])

    summary_data = [{
        "Total_Rooms": len(rooms),
        "Total_Floor_Area_m2": round(sum(r["Floor_Area_m2"] for r in rooms), 2),
        "Total_Door_Count": len(doors),
        "Total_Window_Count": len(windows),
        "Total_Dimension_Count": len(dimensions),
    }]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        room_df.to_excel(writer, sheet_name="Room_Breakdown", index=False)
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="Summary", index=False)
        door_df.to_excel(writer, sheet_name="Doors", index=False)
        win_df.to_excel(writer, sheet_name="Windows", index=False)
        dim_df.to_excel(writer, sheet_name="Dimensions", index=False)

    print(f"✓ Excel created: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract floor plan overview from DXF block")
    parser.add_argument("dxf_path", help="Path to DXF file")
    parser.add_argument("--output", default="C:\\temp\\floorplan_report.xlsx", help="Output Excel path")
    args = parser.parse_args()

    dxf_path = Path(args.dxf_path)
    if not dxf_path.exists():
        print(f"Error: file not found: {dxf_path}")
        sys.exit(1)

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    block_entities = None
    for entity in msp:
        if entity.dxftype() == "INSERT":
            block_name = entity.dxf.name
            print(f"Found embedded block: {block_name}")
            block_entities = list(doc.blocks.get(block_name))
            break

    if block_entities is None:
        print("No INSERT block found in modelspace. Exporting empty workbook.")
        block_entities = []

    rooms = extract_rooms(block_entities)
    doors = extract_doors(block_entities)
    windows = extract_windows(block_entities)
    dimensions = extract_dimensions(block_entities)

    print(f"Rooms: {len(rooms)}")
    print(f"Doors: {len(doors)}")
    print(f"Windows: {len(windows)}")
    print(f"Dimensions: {len(dimensions)}")

    export_excel(args.output, rooms, doors, windows, dimensions)


if __name__ == "__main__":
    main()

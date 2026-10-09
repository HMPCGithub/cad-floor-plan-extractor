#!/usr/bin/env python3
"""
CAD Floor Plan Extractor - Reads block contents and extracts room data to Excel

This extractor:
1. Reads the DXF file
2. Extracts the embedded block (if any)
3. Analyzes layers: WALL, DOOR-AR, WIN, STAIR, DIM-IN-AR, block walls
4. Identifies closed polylines as room boundaries
5. Calculates floor area, wall perimeter, wall area
6. Applies door/window deductions
7. Exports structured Excel report with validation

Usage:
    python extract_floorplan_final.py "C:\\Users\\ahmed\\OneDrive\\Desktop\\Drawing1.dxf" --output floorplan_report.xlsx

Dependencies:
    pip install ezdxf shapely pandas openpyxl
"""

import sys
import math
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from shapely.geometry import Polygon, Point
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


class FloorPlanExtractor:
    def __init__(self, dxf_path: str):
        self.dxf_path = Path(dxf_path)
        self.doc = ezdxf.readfile(str(self.dxf_path))
        self.msp = self.doc.modelspace()
        
        # Try to extract block content
        self.entities = self._get_entities()
        
        self.rooms = []
        self.doors = []
        self.windows = []
        self.dimensions = []
        self.walls = []
        self.errors = []
        self.warnings = []

    def _get_entities(self):
        """Get entities from either modelspace or embedded block."""
        # First check if there's an INSERT block
        inserts = [e for e in self.msp if e.dxftype() == "INSERT"]
        
        if inserts:
            # Extract from the first block
            block_name = inserts[0].dxf.name
            print(f"📦 Found embedded block: {block_name}")
            block = self.doc.blocks.get(block_name)
            return list(block)
        else:
            # Use modelspace directly
            print("📄 Using modelspace entities")
            return list(self.msp)

    def extract_room_boundaries(self):
        """Extract closed polylines from WALL and block walls layers as room boundaries."""
        room_id = 1
        for entity in self.entities:
            if entity.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
                continue
            
            layer = entity.dxf.layer
            if layer not in ("WALL", "block walls"):
                continue
            
            if not getattr(entity, "closed", False):
                continue
            
            # Convert to points
            pts = []
            for p in entity:
                if len(p) >= 2:
                    pts.append((float(p[0]), float(p[1])))
            
            if len(pts) < 3:
                continue
            
            try:
                poly = Polygon(pts)
                if poly.is_valid and poly.area > 0:
                    self.rooms.append({
                        "id": room_id,
                        "name": f"Room_{room_id}",
                        "layer": layer,
                        "geometry": poly,
                        "area": float(poly.area),
                        "perimeter": float(poly.length),
                    })
                    room_id += 1
            except Exception as e:
                self.errors.append(f"Invalid polygon in layer {layer}: {e}")

    def extract_doors(self):
        """Extract door blocks and measurements from DOOR-AR layer."""
        for entity in self.entities:
            if entity.dxftype() == "INSERT":
                layer = entity.dxf.layer
                if layer == "DOOR-AR":
                    insert_pt = tuple(entity.dxf.insert[:2])
                    self.doors.append({
                        "type": "DOOR",
                        "layer": layer,
                        "block_name": entity.dxf.name,
                        "insert": insert_pt,
                        "rotation": entity.dxf.rotation,
                        "scale": entity.dxf.xscale,
                    })
            elif entity.dxftype() == "LWPOLYLINE":
                layer = entity.dxf.layer
                if layer == "DOOR-AR":
                    # Door opening polygon
                    pts = [(float(p[0]), float(p[1])) for p in entity]
                    if len(pts) >= 2:
                        # Calculate door width (distance between first two points)
                        width = math.dist(pts[0], pts[1])
                        self.doors.append({
                            "type": "DOOR_POLY",
                            "layer": layer,
                            "points": pts,
                            "width": width,
                        })

    def extract_windows(self):
        """Extract window blocks from WIN layer."""
        for entity in self.entities:
            if entity.dxftype() == "INSERT":
                layer = entity.dxf.layer
                if layer == "WIN":
                    insert_pt = tuple(entity.dxf.insert[:2])
                    self.windows.append({
                        "type": "WINDOW",
                        "layer": layer,
                        "block_name": entity.dxf.name,
                        "insert": insert_pt,
                        "rotation": entity.dxf.rotation,
                        "scale": entity.dxf.xscale,
                    })
            elif entity.dxftype() == "LINE":
                layer = entity.dxf.layer
                if layer == "WIN":
                    start = tuple(entity.dxf.start[:2])
                    end = tuple(entity.dxf.end[:2])
                    width = math.dist(start, end)
                    self.windows.append({
                        "type": "WINDOW_LINE",
                        "layer": layer,
                        "start": start,
                        "end": end,
                        "width": width,
                    })

    def extract_dimensions(self):
        """Extract dimension annotations."""
        for entity in self.entities:
            if entity.dxftype() == "DIMENSION":
                layer = entity.dxf.layer
                text = getattr(entity, "text", "")
                def_pt = tuple(getattr(entity.dxf, "definition_point", (0, 0, 0))[:2])
                self.dimensions.append({
                    "layer": layer,
                    "text": str(text),
                    "definition_point": def_pt,
                })

    def extract_walls(self):
        """Extract wall lines for perimeter calculation."""
        for entity in self.entities:
            if entity.dxftype() == "LINE":
                layer = entity.dxf.layer
                if layer == "WALL":
                    start = tuple(entity.dxf.start[:2])
                    end = tuple(entity.dxf.end[:2])
                    length = math.dist(start, end)
                    self.walls.append({
                        "layer": layer,
                        "start": start,
                        "end": end,
                        "length": length,
                    })

    def find_elements_in_room(self, room_poly: Polygon, elements: List[Dict], proximity: float = 1.0) -> List[Dict]:
        """Find elements within or near a room."""
        found = []
        for elem in elements:
            insert = elem.get("insert")
            if insert:
                p = Point(insert)
                if room_poly.contains(p) or room_poly.distance(p) < proximity:
                    found.append(elem)
        return found

    def compute_room_summary(self, wall_thickness: float = 0.15) -> List[Dict]:
        """Compute room data including area, wall area, and deductions."""
        summary = []
        
        # Default door/window dimensions
        door_width, door_height = 0.9, 2.1
        window_width, window_height = 1.2, 1.5
        
        for room in self.rooms:
            room_poly = room["geometry"]
            
            # Find doors and windows in this room
            doors_in_room = self.find_elements_in_room(room_poly, self.doors, proximity=1.0)
            windows_in_room = self.find_elements_in_room(room_poly, self.windows, proximity=1.0)
            
            # Calculate deductions
            door_area = len(doors_in_room) * (door_width * door_height)
            window_area = len(windows_in_room) * (window_width * window_height)
            
            # Wall calculations
            wall_area = room["perimeter"] * wall_thickness
            net_wall_area = max(0.0, wall_area - door_area - window_area)
            
            row = {
                "Room_ID": room["id"],
                "Room_Name": room["name"],
                "Layer": room["layer"],
                "Floor_Area_m2": round(room["area"], 2),
                "Perimeter_m": round(room["perimeter"], 2),
                "Wall_Thickness_m": wall_thickness,
                "Gross_Wall_Area_m2": round(wall_area, 2),
                "Door_Count": len(doors_in_room),
                "Door_Area_m2": round(door_area, 2),
                "Window_Count": len(windows_in_room),
                "Window_Area_m2": round(window_area, 2),
                "Net_Wall_Area_m2": round(net_wall_area, 2),
            }
            summary.append(row)
        
        return summary

    def validate_rooms(self) -> List[Dict]:
        """Validate room data."""
        validation = []
        for room in self.rooms:
            errors = []
            if room["area"] <= 0:
                errors.append("zero_area")
            if not room["geometry"].is_valid:
                errors.append("invalid_geometry")
            
            validation.append({
                "Room_ID": room["id"],
                "Room_Name": room["name"],
                "Area_m2": round(room["area"], 2),
                "Status": "OK" if not errors else "ERROR",
                "Errors": "; ".join(errors) if errors else "None",
            })
        return validation

    def export_excel(self, output_path: str):
        """Export all data to Excel workbook."""
        room_summary = self.compute_room_summary()
        room_validation = self.validate_rooms()
        
        # Summary stats
        if room_summary:
            df_summary = pd.DataFrame(room_summary)
            total_area = df_summary["Floor_Area_m2"].sum()
            total_wall_area = df_summary["Gross_Wall_Area_m2"].sum()
            total_door_area = df_summary["Door_Area_m2"].sum()
            total_window_area = df_summary["Window_Area_m2"].sum()
        else:
            total_area = total_wall_area = total_door_area = total_window_area = 0
        
        stats = pd.DataFrame([{
            "Total_Rooms": len(self.rooms),
            "Total_Floor_Area_m2": round(total_area, 2),
            "Total_Wall_Area_m2": round(total_wall_area, 2),
            "Total_Door_Area_m2": round(total_door_area, 2),
            "Total_Window_Area_m2": round(total_window_area, 2),
            "Total_Doors": len(self.doors),
            "Total_Windows": len(self.windows),
            "Total_Dimensions": len(self.dimensions),
        }])
        
        # Write Excel
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            pd.DataFrame(room_summary).to_excel(writer, sheet_name="Room_Breakdown", index=False)
            pd.DataFrame(room_validation).to_excel(writer, sheet_name="Room_Validation", index=False)
            stats.to_excel(writer, sheet_name="Summary", index=False)
            
            if self.doors:
                pd.DataFrame(self.doors).to_excel(writer, sheet_name="Doors", index=False)
            if self.windows:
                pd.DataFrame(self.windows).to_excel(writer, sheet_name="Windows", index=False)
            if self.dimensions:
                pd.DataFrame(self.dimensions).to_excel(writer, sheet_name="Dimensions", index=False)
            if self.errors:
                pd.DataFrame([{"error": e} for e in self.errors]).to_excel(writer, sheet_name="Error_Log", index=False)
        
        self._format_excel(output_path)
        print(f"✓ Excel exported: {output_path}")

    def _format_excel(self, output_path: str):
        """Format Excel workbook."""
        wb = openpyxl.load_workbook(output_path)
        header_fill = PatternFill("solid", fgColor="4472C4")
        header_font = Font(bold=True, color="FFFFFF")
        border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin")
        )
        
        for ws in wb.worksheets:
            if ws.max_row == 0:
                continue
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
            
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                for cell in row:
                    cell.border = border
            
            for col in ws.columns:
                max_len = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        max_len = max(max_len, len(str(cell.value or "")))
                    except:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 2, 30)
        
        wb.save(output_path)

    def run(self):
        """Execute full extraction pipeline."""
        print("🔍 Extracting floor plan data...")
        self.extract_room_boundaries()
        print(f"  ✓ Found {len(self.rooms)} room boundaries")
        
        self.extract_doors()
        print(f"  ✓ Found {len(self.doors)} doors")
        
        self.extract_windows()
        print(f"  ✓ Found {len(self.windows)} windows")
        
        self.extract_dimensions()
        print(f"  ✓ Found {len(self.dimensions)} dimensions")
        
        self.extract_walls()
        print(f"  ✓ Found {len(self.walls)} wall segments")


def main():
    parser = argparse.ArgumentParser(description="Extract CAD floor plan to Excel")
    parser.add_argument("dxf_path", nargs="?", help="Path to DXF file")
    parser.add_argument("--dxf", dest="dxf_arg", help="DXF file path (alternative flag)")
    parser.add_argument("--output", default="floorplan_report.xlsx", help="Output Excel file")
    args = parser.parse_args()
    
    dxf_path = args.dxf_path or args.dxf_arg
    if not dxf_path:
        print("Usage: python extract_floorplan_final.py <dxf_path> --output <output_file>")
        sys.exit(1)
    
    extractor = FloorPlanExtractor(dxf_path)
    extractor.run()
    extractor.export_excel(args.output)
    
    print(f"\n{'='*80}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()

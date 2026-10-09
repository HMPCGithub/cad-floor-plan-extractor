"""
CAD Floor Plan Extractor to Excel

Extracts floor plan data from DXF/DWG and exports comprehensive breakdown:
- Room ID, Name, Area
- Wall perimeter and area calculations
- Door/Window deductions
- Element counts and positions
- Floor area summaries
- Excel multi-sheet export

Dependencies:
    pip install ezdxf shapely openpyxl pandas
"""

import math
from collections import defaultdict
from typing import List, Dict, Any, Tuple
import json

import ezdxf
from shapely.geometry import Polygon, Point, LineString, MultiLineString
from shapely.ops import unary_union
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils.dataframe import dataframe_to_rows
import pandas as pd


class FloorPlanExtractor:
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        
        # Storage for extracted data
        self.rooms = []
        self.texts = []
        self.dimensions = []
        self.inserts = []
        self.lines = []
        self.room_summary = []
        
    def to_xy_points(self, polyline) -> List[Tuple[float, float]]:
        """Convert DXF polyline points to (x, y) list."""
        pts = []
        for p in polyline:
            pts.append((p[0], p[1]))
        return pts
    
    def extract_text_data(self):
        """Extract TEXT and MTEXT entities."""
        self.texts = []
        for e in self.msp:
            if e.dxftype() == "TEXT":
                self.texts.append({
                    "type": "TEXT",
                    "layer": e.dxf.layer,
                    "text": e.dxf.text,
                    "insert": (e.dxf.insert[0], e.dxf.insert[1]),
                    "height": e.dxf.height,
                    "rotation": e.dxf.rotation,
                })
            elif e.dxftype() == "MTEXT":
                self.texts.append({
                    "type": "MTEXT",
                    "layer": e.dxf.layer,
                    "text": e.text,
                    "insert": (e.insert[0], e.insert[1]),
                    "rotation": e.dxf.rotation,
                })
        return self.texts
    
    def extract_dimensions(self):
        """Extract DIMENSION entities."""
        self.dimensions = []
        for e in self.msp:
            if e.dxftype() == "DIMENSION":
                try:
                    dims_obj = {
                        "type": "DIMENSION",
                        "layer": e.dxf.layer,
                        "text": getattr(e, "text", None),
                        "measurement": getattr(e, "measurement", None),
                        "definition_point": tuple(e.dxf.definition_point)[:2],
                    }
                    if hasattr(e.dxf, "text_midpoint"):
                        dims_obj["text_midpoint"] = tuple(e.dxf.text_midpoint)[:2]
                    if hasattr(e.dxf, "rotation"):
                        dims_obj["rotation"] = e.dxf.rotation
                    self.dimensions.append(dims_obj)
                except Exception as ex:
                    print(f"Warning: Could not extract dimension: {ex}")
        return self.dimensions
    
    def extract_blocks(self):
        """Extract INSERT (block) entities with attributes."""
        self.inserts = []
        for e in self.msp:
            if e.dxftype() == "INSERT":
                block_name = e.dxf.name
                attrs = {}
                
                # Collect attributes
                for attrib in e.attribs:
                    attrs[attrib.dxf.tag] = attrib.dxf.text
                
                insert_obj = {
                    "type": "INSERT",
                    "layer": e.dxf.layer,
                    "block_name": block_name,
                    "insert": (e.dxf.insert[0], e.dxf.insert[1]),
                    "scale": e.dxf.xscale,
                    "rotation": e.dxf.rotation,
                    "attributes": attrs,
                }
                self.inserts.append(insert_obj)
        return self.inserts
    
    def extract_lines(self):
        """Extract LINE entities (for wall measurements)."""
        self.lines = []
        for e in self.msp:
            if e.dxftype() == "LINE":
                start = (e.dxf.start[0], e.dxf.start[1])
                end = (e.dxf.end[0], e.dxf.end[1])
                length = math.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
                
                self.lines.append({
                    "layer": e.dxf.layer,
                    "start": start,
                    "end": end,
                    "length": length,
                    "color": getattr(e.dxf, "color", None),
                })
        return self.lines
    
    def extract_room_polygons(self):
        """Extract closed polylines as room boundaries."""
        self.rooms = []
        room_id = 1
        
        for e in self.msp:
            if e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                if getattr(e, "closed", False):
                    pts = self.to_xy_points(e)
                    if len(pts) >= 3:
                        try:
                            poly = Polygon(pts)
                            if poly.is_valid and poly.area > 0:
                                self.rooms.append({
                                    "id": room_id,
                                    "geometry": poly,
                                    "layer": e.dxf.layer,
                                    "area": poly.area,
                                    "perimeter": poly.length,
                                })
                                room_id += 1
                        except Exception:
                            pass
        return self.rooms
    
    def classify_elements(self):
        """Classify blocks by type."""
        door_keywords = {"DOOR", "DOR", "SWINGDOOR", "DOUBLEDR", "POCKETDR"}
        window_keywords = {"WINDOW", "WIN", "WDW", "GLASS", "CASEMENT"}
        level_keywords = {"LEVEL", "LEVEL_TAG", "LEVEL_NAME", "ELEV"}
        furniture_keywords = {"FURNITURE", "FURN", "DESK", "TABLE", "CHAIR", "SOFA"}
        
        classified = {
            "doors": [],
            "windows": [],
            "levels": [],
            "furniture": [],
            "other": [],
        }
        
        for ins in self.inserts:
            name = (ins.get("block_name") or "").upper()
            if any(k in name for k in door_keywords):
                classified["doors"].append(ins)
            elif any(k in name for k in window_keywords):
                classified["windows"].append(ins)
            elif any(k in name for k in level_keywords):
                classified["levels"].append(ins)
            elif any(k in name for k in furniture_keywords):
                classified["furniture"].append(ins)
            else:
                classified["other"].append(ins)
        
        return classified
    
    def calculate_wall_area(self, room: dict, wall_thickness: float = 0.15) -> float:
        """
        Estimate wall area from room perimeter.
        wall_area = perimeter * wall_thickness
        """
        perimeter = room["perimeter"]
        wall_area = perimeter * wall_thickness
        return wall_area
    
    def find_room_elements(self, room_poly: Polygon, elements: List[dict], 
                          proximity_distance: float = 1.0) -> List[dict]:
        """
        Find elements (doors/windows) associated with a room.
        Uses point-in-polygon and proximity checks.
        """
        found = []
        for elem in elements:
            p = Point(elem["insert"])
            # Element is in room or very close to boundary
            if room_poly.contains(p) or room_poly.distance(p) < proximity_distance:
                found.append(elem)
        return found
    
    def build_room_breakdown(self, wall_thickness: float = 0.15) -> List[Dict]:
        """
        Build comprehensive room breakdown with all metrics.
        """
        classified = self.classify_elements()
        breakdown = []
        
        for room in self.rooms:
            room_data = {
                "Room_ID": room["id"],
                "Room_Name": f"Room_{room['id']}",
                "Layer": room["layer"],
                "Floor_Area_m2": round(room["area"], 2),
                "Perimeter_m": round(room["perimeter"], 2),
                "Wall_Thickness_m": wall_thickness,
                "Wall_Area_m2": round(self.calculate_wall_area(room, wall_thickness), 2),
            }
            
            # Find doors
            doors = self.find_room_elements(room["geometry"], classified["doors"])
            room_data["Door_Count"] = len(doors)
            room_data["Door_IDs"] = ", ".join([d["block_name"] for d in doors])
            
            # Calculate door deduction (typical door: 0.9m x 2.1m)
            door_area_deduction = len(doors) * (0.9 * 2.1)
            room_data["Door_Area_Deduction_m2"] = round(door_area_deduction, 2)
            
            # Find windows
            windows = self.find_room_elements(room["geometry"], classified["windows"])
            room_data["Window_Count"] = len(windows)
            room_data["Window_IDs"] = ", ".join([w["block_name"] for w in windows])
            
            # Calculate window deduction (typical window: 1.2m x 1.5m)
            window_area_deduction = len(windows) * (1.2 * 1.5)
            room_data["Window_Area_Deduction_m2"] = round(window_area_deduction, 2)
            
            # Net wall area
            net_wall_area = (room_data["Wall_Area_m2"] - 
                           room_data["Door_Area_Deduction_m2"] - 
                           room_data["Window_Area_Deduction_m2"])
            room_data["Net_Wall_Area_m2"] = round(max(0, net_wall_area), 2)
            
            # Text/labels in room
            texts_in_room = []
            for t in self.texts:
                p = Point(t["insert"])
                if room["geometry"].contains(p):
                    texts_in_room.append(t["text"])
            room_data["Text_Labels"] = "; ".join(texts_in_room[:3])
            room_data["Text_Label_Count"] = len(texts_in_room)
            
            # Dimensions in room
            dims_in_room = []
            for d in self.dimensions:
                if "definition_point" in d:
                    p = Point(d["definition_point"])
                    if room["geometry"].contains(p):
                        dims_in_room.append(str(d.get("text", "")))
            room_data["Dimension_Count"] = len(dims_in_room)
            room_data["Dimensions"] = "; ".join(dims_in_room[:3])
            
            breakdown.append(room_data)
        
        self.room_summary = breakdown
        return breakdown
    
    def get_summary_stats(self) -> Dict[str, float]:
        """Calculate overall summary statistics."""
        if not self.room_summary:
            return {}
        
        df = pd.DataFrame(self.room_summary)
        stats = {
            "Total_Rooms": len(self.room_summary),
            "Total_Floor_Area_m2": round(df["Floor_Area_m2"].sum(), 2),
            "Total_Wall_Area_m2": round(df["Wall_Area_m2"].sum(), 2),
            "Total_Net_Wall_Area_m2": round(df["Net_Wall_Area_m2"].sum(), 2),
            "Total_Doors": int(df["Door_Count"].sum()),
            "Total_Windows": int(df["Window_Count"].sum()),
            "Average_Room_Area_m2": round(df["Floor_Area_m2"].mean(), 2),
            "Largest_Room_m2": round(df["Floor_Area_m2"].max(), 2),
            "Smallest_Room_m2": round(df["Floor_Area_m2"].min(), 2),
        }
        return stats
    
    def export_to_excel(self, output_path: str):
        """Export all extracted data to Excel workbook."""
        
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            # Sheet 1: Room Breakdown
            df_rooms = pd.DataFrame(self.room_summary)
            df_rooms.to_excel(writer, sheet_name="Room_Breakdown", index=False)
            
            # Sheet 2: Summary Statistics
            summary_stats = self.get_summary_stats()
            df_stats = pd.DataFrame([summary_stats])
            df_stats.to_excel(writer, sheet_name="Summary", index=False)
            
            # Sheet 3: Doors
            classified = self.classify_elements()
            df_doors = pd.DataFrame(classified["doors"])
            if not df_doors.empty:
                df_doors.to_excel(writer, sheet_name="Doors", index=False)
            
            # Sheet 4: Windows
            df_windows = pd.DataFrame(classified["windows"])
            if not df_windows.empty:
                df_windows.to_excel(writer, sheet_name="Windows", index=False)
            
            # Sheet 5: Text Labels
            df_texts = pd.DataFrame(self.texts)
            if not df_texts.empty:
                df_texts.to_excel(writer, sheet_name="Text_Labels", index=False)
            
            # Sheet 6: Dimensions
            df_dims = pd.DataFrame(self.dimensions)
            if not df_dims.empty:
                df_dims.to_excel(writer, sheet_name="Dimensions", index=False)
            
            # Sheet 7: Lines (walls)
            df_lines = pd.DataFrame(self.lines)
            if not df_lines.empty:
                df_lines.to_excel(writer, sheet_name="Lines", index=False)
        
        # Format the workbook
        self._format_excel(output_path)
        print(f"✓ Excel file exported: {output_path}")
    
    def _format_excel(self, output_path: str):
        """Apply formatting to the Excel workbook."""
        wb = openpyxl.load_workbook(output_path)
        
        # Style headers
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin")
        )
        
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            
            # Format header row
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Format data rows
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                for cell in row:
                    cell.border = border
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        
        wb.save(output_path)
    
    def extract_all(self):
        """Run all extraction methods."""
        print("Extracting floor plan data...")
        self.extract_room_polygons()
        print(f"  ✓ Found {len(self.rooms)} rooms")
        
        self.extract_text_data()
        print(f"  ✓ Found {len(self.texts)} text labels")
        
        self.extract_dimensions()
        print(f"  ✓ Found {len(self.dimensions)} dimensions")
        
        self.extract_blocks()
        print(f"  ✓ Found {len(self.inserts)} blocks/elements")
        
        self.extract_lines()
        print(f"  ✓ Found {len(self.lines)} lines")
        
        self.build_room_breakdown()
        print(f"  ✓ Room breakdown complete")
        
        return self
    
    def print_summary(self):
        """Print summary to console."""
        stats = self.get_summary_stats()
        print("\n" + "="*60)
        print("FLOOR PLAN SUMMARY")
        print("="*60)
        for key, value in stats.items():
            print(f"{key:.<40} {value}")
        print("="*60)


def main(dxf_path: str, output_excel_path: str, wall_thickness: float = 0.15):
    """
    Main function to extract floor plan and export to Excel.
    
    Args:
        dxf_path: Path to DXF/DWG file
        output_excel_path: Path to output Excel file
        wall_thickness: Wall thickness in meters (default 0.15m = 15cm)
    """
    extractor = FloorPlanExtractor(dxf_path)
    extractor.extract_all()
    extractor.print_summary()
    extractor.export_to_excel(output_excel_path)


if __name__ == "__main__":
    # Example usage:
    # main("floorplan.dxf", "floorplan_breakdown.xlsx", wall_thickness=0.15)
    pass

#!/usr/bin/env python3
"""
Automated DXF Inspection and Template Generator

This script:
1. Scans a DXF file for all layers, entities, blocks, text, dimensions
2. Analyzes patterns and suggests layer mappings
3. Generates a custom config template JSON
4. Creates a detailed inspection report
5. Outputs everything to files for review

Usage:
    python auto_inspect_and_template.py "C:\\Users\\ahmed\\OneDrive\\Desktop\\Drawing1.dxf"

Output files:
    - dxf_inspection_report.txt (detailed layer breakdown)
    - suggested_config.json (auto-generated template to review)
    - layer_analysis.csv (layer statistics)
    - blocks_analysis.csv (block names and counts)
    - text_samples.csv (text label samples)
    - dimensions_samples.csv (dimension samples)
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import ezdxf
import csv


class DXFAnalyzer:
    def __init__(self, dxf_path: str):
        self.dxf_path = Path(dxf_path)
        if not self.dxf_path.exists():
            raise FileNotFoundError(f"DXF file not found: {self.dxf_path}")

        self.doc = ezdxf.readfile(str(self.dxf_path))
        self.msp = self.doc.modelspace()

        # Storage for analysis
        self.layer_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "entity_types": set(), "entities": []}
        )
        self.block_names: Dict[str, int] = defaultdict(int)
        self.block_attrs: Dict[str, Set[str]] = defaultdict(set)
        self.text_items: List[Dict[str, Any]] = []
        self.dimension_items: List[Dict[str, Any]] = []
        self.polyline_closed_count = 0
        self.line_count = 0
        self.insert_count = 0

    def analyze(self):
        """Run full DXF analysis."""
        print("🔍 Analyzing DXF file...")
        for entity in self.msp:
            self._analyze_entity(entity)
        print(f"✓ Found {len(self.layer_stats)} layers")
        print(f"✓ Found {len(self.block_names)} unique blocks")
        print(f"✓ Found {len(self.text_items)} text items")
        print(f"✓ Found {len(self.dimension_items)} dimensions")

    def _analyze_entity(self, entity):
        """Analyze a single entity."""
        layer = entity.dxf.layer
        etype = entity.dxftype()

        self.layer_stats[layer]["count"] += 1
        self.layer_stats[layer]["entity_types"].add(etype)
        self.layer_stats[layer]["entities"].append(etype)

        if etype in ("LWPOLYLINE", "POLYLINE"):
            if getattr(entity, "closed", False):
                self.polyline_closed_count += 1
            self.layer_stats[layer]["closed_polylines"] = (
                self.layer_stats[layer].get("closed_polylines", 0) + 1
            )

        elif etype == "LINE":
            self.line_count += 1

        elif etype == "INSERT":
            self.insert_count += 1
            block_name = (entity.dxf.name or "").strip()
            if block_name:
                self.block_names[block_name] += 1
                # Collect block attributes
                for attrib in entity.attribs:
                    tag = getattr(attrib.dxf, "tag", "UNKNOWN")
                    self.block_attrs[block_name].add(str(tag))

        elif etype in ("TEXT", "MTEXT"):
            text_val = getattr(entity, "text", getattr(entity.dxf, "text", ""))
            insert = tuple(getattr(entity.dxf, "insert", (0, 0, 0))[:2])
            self.text_items.append({
                "layer": layer,
                "text": str(text_val),
                "insert": insert,
            })

        elif etype == "DIMENSION":
            text_val = getattr(entity, "text", "")
            def_pt = tuple(getattr(entity.dxf, "definition_point", (0, 0, 0))[:2])
            self.dimension_items.append({
                "layer": layer,
                "text": str(text_val),
                "definition_point": def_pt,
            })

    def guess_layer_category(self, layer_name: str) -> str:
        """Heuristic guess of layer category based on name."""
        layer_upper = layer_name.upper()

        if any(k in layer_upper for k in ["WALL", "WALLS"]):
            return "walls"
        if any(k in layer_upper for k in ["ROOM", "SPACE", "AREAS", "BOUNDARY"]):
            return "room_boundaries"
        if any(k in layer_upper for k in ["DOOR", "DOR"]):
            return "doors"
        if any(k in layer_upper for k in ["WINDOW", "WIN", "WDW"]):
            return "windows"
        if any(k in layer_upper for k in ["LEVEL", "ELEV", "FLOOR", "STORY"]):
            return "levels"
        if any(k in layer_upper for k in ["TEXT", "LABEL", "ANNOT"]):
            return "text_labels"
        if any(k in layer_upper for k in ["DIM", "DIMENSION"]):
            return "dimensions"
        if any(k in layer_upper for k in ["FURN", "FURNITURE"]):
            return "furniture"

        return "other"

    def generate_layer_report(self) -> str:
        """Generate a detailed layer report."""
        lines = [
            "=" * 80,
            "DXF LAYER INSPECTION REPORT",
            "=" * 80,
            f"File: {self.dxf_path}",
            "",
            "=" * 80,
            "SUMMARY",
            "=" * 80,
            f"Total Layers: {len(self.layer_stats)}",
            f"Total Entities: {sum(s['count'] for s in self.layer_stats.values())}",
            f"Closed Polylines: {self.polyline_closed_count} (room candidates)",
            f"Lines: {self.line_count}",
            f"Inserts (Blocks): {self.insert_count}",
            f"Text Items: {len(self.text_items)}",
            f"Dimensions: {len(self.dimension_items)}",
            "",
            "=" * 80,
            "LAYER BREAKDOWN",
            "=" * 80,
        ]

        for layer_name in sorted(self.layer_stats.keys()):
            stat = self.layer_stats[layer_name]
            entity_types = sorted(stat["entity_types"])
            guessed_category = self.guess_layer_category(layer_name)
            closed_poly = stat.get("closed_polylines", 0)

            lines.append("")
            lines.append(f"Layer: {layer_name}")
            lines.append(f"  Guessed Category: {guessed_category}")
            lines.append(f"  Total Entities: {stat['count']}")
            lines.append(f"  Entity Types: {', '.join(entity_types)}")
            if closed_poly > 0:
                lines.append(f"  Closed Polylines: {closed_poly} (possible rooms)")

        lines.append("")
        lines.append("=" * 80)
        lines.append("BLOCK NAMES & COUNTS")
        lines.append("=" * 80)
        for block_name in sorted(self.block_names.keys()):
            count = self.block_names[block_name]
            attrs = sorted(self.block_attrs.get(block_name, set()))
            lines.append(f"{block_name}: {count} instances | Attributes: {', '.join(attrs) if attrs else 'None'}")

        lines.append("")
        lines.append("=" * 80)
        lines.append("TEXT SAMPLES (first 20)")
        lines.append("=" * 80)
        for item in self.text_items[:20]:
            lines.append(f"[{item['layer']}] '{item['text']}' @ {item['insert']}")

        lines.append("")
        lines.append("=" * 80)
        lines.append("DIMENSION SAMPLES (first 20)")
        lines.append("=" * 80)
        for item in self.dimension_items[:20]:
            lines.append(f"[{item['layer']}] '{item['text']}' @ {item['definition_point']}")

        return "\n".join(lines)

    def generate_suggested_config(self) -> Dict[str, Any]:
        """Generate a suggested config template based on analysis."""
        layer_to_category = {}
        for layer_name in self.layer_stats.keys():
            category = self.guess_layer_category(layer_name)
            if category not in layer_to_category:
                layer_to_category[category] = []
            layer_to_category[category].append(layer_name)

        # Suggest block keywords based on block names found
        door_keywords = []
        window_keywords = []
        for block_name in self.block_names.keys():
            upper = block_name.upper()
            if any(k in upper for k in ["DOOR", "DOR", "SWING"]):
                door_keywords.append(block_name)
            elif any(k in upper for k in ["WINDOW", "WIN", "WDW", "GLASS"]):
                window_keywords.append(block_name)

        config = {
            "project": "Floor Plan Extraction (Auto-Generated)",
            "description": "Configuration template auto-generated from DXF inspection",
            "cad_file": str(self.dxf_path),
            "settings": {
                "wall_thickness_m": 0.15,
                "door_width_m": 0.9,
                "door_height_m": 2.1,
                "window_width_m": 1.2,
                "window_height_m": 1.5,
                "min_room_area_m2": 0.5,
                "proximity_distance_m": 1.0,
            },
            "layers": {},
        }

        # Build layer definitions
        layer_definitions = {
            "walls": {
                "enabled": True,
                "layer_names": layer_to_category.get("walls", []),
                "entity_types": ["LINE", "LWPOLYLINE", "POLYLINE"],
                "description": "Wall outlines and centerlines",
                "visualization": {"color": 1, "lineweight": 35, "linetype": "CONTINUOUS"},
            },
            "room_boundaries": {
                "enabled": True,
                "layer_names": layer_to_category.get("room_boundaries", []),
                "entity_types": ["LWPOLYLINE", "POLYLINE"],
                "description": "Closed polygons defining room spaces - REQUIRED",
                "required": True,
                "visualization": {"color": 5, "lineweight": 50, "linetype": "CONTINUOUS"},
            },
            "doors": {
                "enabled": True,
                "layer_names": layer_to_category.get("doors", []),
                "entity_types": ["INSERT"],
                "block_keywords": door_keywords if door_keywords else ["DOOR"],
                "description": "Door block inserts",
                "visualization": {"color": 2, "lineweight": 25, "linetype": "CONTINUOUS"},
            },
            "windows": {
                "enabled": True,
                "layer_names": layer_to_category.get("windows", []),
                "entity_types": ["INSERT"],
                "block_keywords": window_keywords if window_keywords else ["WINDOW"],
                "description": "Window block inserts",
                "visualization": {"color": 4, "lineweight": 25, "linetype": "CONTINUOUS"},
            },
            "levels": {
                "enabled": True,
                "layer_names": layer_to_category.get("levels", []),
                "entity_types": ["TEXT", "INSERT"],
                "block_keywords": ["LEVEL"],
                "description": "Floor level indicators",
                "visualization": {"color": 3, "lineweight": 15, "linetype": "CONTINUOUS"},
            },
            "text_labels": {
                "enabled": True,
                "layer_names": layer_to_category.get("text_labels", []),
                "entity_types": ["TEXT", "MTEXT"],
                "description": "Room names and annotations",
                "visualization": {"color": 7, "lineweight": 0, "linetype": "CONTINUOUS"},
            },
            "dimensions": {
                "enabled": True,
                "layer_names": layer_to_category.get("dimensions", []),
                "entity_types": ["DIMENSION"],
                "description": "Dimension text and values",
                "visualization": {"color": 6, "lineweight": 15, "linetype": "CONTINUOUS"},
            },
        }

        config["layers"] = layer_definitions
        config["extraction_rules"] = {
            "room_identification": {
                "method": "closed_polyline",
                "source_layer": "room_boundaries",
                "min_area_m2": 0.5,
                "auto_id": True,
            },
            "wall_calculation": {
                "method": "perimeter_based",
                "thickness_m": 0.15,
                "deduct_doors": True,
                "deduct_windows": True,
            },
            "door_window_deduction": {
                "proximity_distance_m": 1.0,
                "use_block_attributes": True,
                "fallback_to_defaults": True,
            },
            "level_assignment": {
                "method": "text_nearest_room",
                "default_level": "Ground",
            },
            "room_naming": {
                "method": "text_inside_or_block_attribute",
                "fallback_pattern": "Room_{id}",
            },
        }
        config["validation"] = {
            "check_missing_layers": True,
            "check_empty_layers": True,
            "check_geometry_validity": True,
            "check_duplicate_ids": True,
            "check_zero_area": True,
            "generate_error_report": True,
        }
        config["output_options"] = {
            "excel_sheets": [
                "Room_Breakdown",
                "Room_Validation",
                "Error_Log",
                "Warnings",
                "Doors",
                "Windows",
                "Levels",
                "Text_Labels",
                "Dimensions",
                "Summary",
            ],
            "create_visualization_dxf": True,
            "include_validation": True,
            "precision_decimals": 2,
        }

        return config

    def save_layer_analysis_csv(self, output_path: Path):
        """Save layer analysis to CSV."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Layer", "Count", "Entity_Types", "Guessed_Category", "Closed_Polylines"])
            for layer_name in sorted(self.layer_stats.keys()):
                stat = self.layer_stats[layer_name]
                entity_types = ", ".join(sorted(stat["entity_types"]))
                category = self.guess_layer_category(layer_name)
                closed_poly = stat.get("closed_polylines", 0)
                writer.writerow([layer_name, stat["count"], entity_types, category, closed_poly])

    def save_blocks_analysis_csv(self, output_path: Path):
        """Save block analysis to CSV."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Block_Name", "Count", "Attributes"])
            for block_name in sorted(self.block_names.keys()):
                count = self.block_names[block_name]
                attrs = ", ".join(sorted(self.block_attrs.get(block_name, set())))
                writer.writerow([block_name, count, attrs])

    def save_text_samples_csv(self, output_path: Path):
        """Save text samples to CSV."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Layer", "Text", "Insert_X", "Insert_Y"])
            for item in self.text_items[:100]:
                writer.writerow([item["layer"], item["text"], item["insert"][0], item["insert"][1]])

    def save_dimensions_samples_csv(self, output_path: Path):
        """Save dimension samples to CSV."""
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Layer", "Text", "Definition_Point_X", "Definition_Point_Y"])
            for item in self.dimension_items[:100]:
                writer.writerow([item["layer"], item["text"], item["definition_point"][0], item["definition_point"][1]])


def main():
    parser = argparse.ArgumentParser(description="Automated DXF inspection and template generation")
    parser.add_argument("dxf_path", help="Path to DXF file")
    parser.add_argument("--output-dir", default=".", help="Output directory for analysis files")
    args = parser.parse_args()

    try:
        analyzer = DXFAnalyzer(args.dxf_path)
        analyzer.analyze()

        # Generate inspection report
        report = analyzer.generate_layer_report()
        report_path = Path(args.output_dir) / "dxf_inspection_report.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"✓ Inspection report: {report_path}")

        # Generate suggested config
        config = analyzer.generate_suggested_config()
        config_path = Path(args.output_dir) / "suggested_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"✓ Suggested config: {config_path}")

        # Save CSV analyses
        analyzer.save_layer_analysis_csv(Path(args.output_dir) / "layer_analysis.csv")
        print(f"✓ Layer analysis: {Path(args.output_dir) / 'layer_analysis.csv'}")

        analyzer.save_blocks_analysis_csv(Path(args.output_dir) / "blocks_analysis.csv")
        print(f"✓ Block analysis: {Path(args.output_dir) / 'blocks_analysis.csv'}")

        analyzer.save_text_samples_csv(Path(args.output_dir) / "text_samples.csv")
        print(f"✓ Text samples: {Path(args.output_dir) / 'text_samples.csv'}")

        analyzer.save_dimensions_samples_csv(Path(args.output_dir) / "dimensions_samples.csv")
        print(f"✓ Dimension samples: {Path(args.output_dir) / 'dimensions_samples.csv'}")

        print("\n" + "=" * 80)
        print("NEXT STEPS:")
        print("=" * 80)
        print("1. Review dxf_inspection_report.txt to understand the layer structure")
        print("2. Review suggested_config.json and adjust layer names if needed")
        print("3. Run: python cad_floorplan_extractor.py --dxf Drawing1.dxf --config suggested_config.json --output report.xlsx")
        print("=" * 80)

        return 0

    except Exception as exc:
        print(f"❌ Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

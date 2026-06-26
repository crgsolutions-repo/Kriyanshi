import uuid
import random
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    agg_code_to_str,
    is_valid_field_name,
    map_aggregation,
)


def extract_field_with_entity(field):
    if not isinstance(field, dict):
        return None
    native_name = field.get("Native name", "")
    if isinstance(native_name, str) and native_name.strip().lower() == "calculated":
        return None
    col_name = field.get("column")
    entity_name = field.get("parent-name", "")
    derivation = field.get("derivation", None)
    return {"Property": col_name, "Entity": entity_name, "Derivation": derivation}


def convert_tableau_treemap_to_powerbi(json_in):
    """
    Converts a single-workbook/tableau worksheet (treemap) JSON into Power BI treemap visual JSON.
    Special case: rows and cols are empty; all fields come from encodings:
      size   → Values
      color  → Group
      lod    → Group
      text   → Details
    """
    # base skeleton
    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": {
            "x": round(random.uniform(20, 120), 2),
            "y": round(random.uniform(10, 60), 2),
            "z": 1,
            "height": random.randint(400, 700),
            "width": random.randint(800, 1200),
        },
        "visual": {
            "visualType": "treemap",
            "query": {
                "queryState": {
                    "Details": {"projections": []},
                    "Group": {"projections": []},
                    "Values": {"projections": []},
                }
            },
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": {"filters": []},
    }

    # If worksheets list present, take first
    worksheets = json_in.get("worksheets", [json_in])
    ws = worksheets[0]

    enc = ws.get("encodings", {})

    # Helper to build a column projection (or a date hierarchy level)
    def build_column_proj(mapped, active=False):
        deriv = mapped.get("Derivation")
        if (
            deriv
            and isinstance(deriv, str)
            and deriv.lower() in {"year", "quarter", "month", "day"}
        ):
            lvl = deriv.capitalize()
            proj = {
                "field": {
                    "HierarchyLevel": {
                        "Expression": {
                            "Hierarchy": {
                                "Expression": {
                                    "PropertyVariationSource": {
                                        "Expression": {
                                            "SourceRef": {"Entity": mapped["Entity"]}
                                        },
                                        "Name": "Variation",
                                        "Property": mapped["Property"],
                                    }
                                },
                                "Hierarchy": "Date Hierarchy",
                            }
                        },
                        "Level": lvl,
                    }
                },
                "queryRef": f"{mapped['Entity']}.{mapped['Property']}.Variation.Date Hierarchy.{lvl}",
                "nativeQueryRef": f"{mapped['Property']} {lvl}",
            }
            if active:
                proj["active"] = True
            return proj
        else:
            proj = {
                "field": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": mapped["Entity"]}},
                        "Property": mapped["Property"],
                    }
                },
                "queryRef": f"{mapped['Entity']}.{mapped['Property']}",
                "nativeQueryRef": mapped["Property"],
            }
            if active:
                proj["active"] = True
            return proj

    # --- Details (text) ---
    text_enc = enc.get("text")
    details_proj = []
    if text_enc:
        mapped_text = extract_field_with_entity(text_enc)
        if mapped_text and is_valid_field_name(mapped_text["Property"]):
            details_proj.append(build_column_proj(mapped_text))
    powerbi_json["visual"]["query"]["queryState"]["Details"][
        "projections"
    ] = details_proj

    # --- Values (size) ---
    used_value_fields = set()
    values_proj_list = []
    size_enc = enc.get("size")
    values_proj_list = []
    if size_enc:
        mapped_size = extract_field_with_entity(size_enc)
        if mapped_size and is_valid_field_name(mapped_size["Property"]):
            prop = mapped_size["Property"]
            agg_name = mapped_size.get("Derivation") or "Sum"
            agg_code = map_aggregation(agg_name)
            agg_str = agg_code_to_str(agg_code)

            values_proj = {
                "field": {
                    "Aggregation": {
                        "Expression": {
                            "Column": {
                                "Expression": {
                                    "SourceRef": {"Entity": mapped_size["Entity"]}
                                },
                                "Property": prop,
                            }
                        },
                        "Function": agg_code,
                    }
                },
                "queryRef": f"{agg_str}({mapped_size['Entity']}.{prop})",
                "nativeQueryRef": f"{agg_str} of {prop}",
            }
            values_proj_list.append(values_proj)
            # mark this field as used-as-value so we can avoid duplicates
            used_value_fields.add((mapped_size["Entity"], prop))
            # create a corresponding filter entry in filterConfig similar to your example
            filter_item = {
                "name": uuid.uuid4().hex[:20],
                "field": {
                    "Aggregation": {
                        "Expression": {
                            "Column": {
                                "Expression": {
                                    "SourceRef": {"Entity": mapped_size["Entity"]}
                                },
                                "Property": prop,
                            }
                        },
                        "Function": agg_code,
                    }
                },
                "type": "Advanced",
            }
            powerbi_json["filterConfig"]["filters"].append(filter_item)

    powerbi_json["visual"]["query"]["queryState"]["Values"][
        "projections"
    ] = values_proj_list
    # --- Group (color + lod) ---
    group_proj = []

    # Handle color -> Group
    color_enc = enc.get("color")
    if color_enc:
        mapped_color = extract_field_with_entity(color_enc)
        if mapped_color and is_valid_field_name(mapped_color["Property"]):
            key = (mapped_color["Entity"], mapped_color["Property"])
            # mark group as active (matches example)
            if key not in used_value_fields:
                group_proj.append(build_column_proj(mapped_color, active=True))

    # Handle lod -> Group
    lod_enc = enc.get("lod")
    if lod_enc:
        mapped_lod = extract_field_with_entity(lod_enc)
        if mapped_lod and is_valid_field_name(mapped_lod["Property"]):
            key = (mapped_lod["Entity"], mapped_lod["Property"])
            if key not in used_value_fields:
                # avoid adding duplicates if same key already appended by color
                if key not in {
                    (
                        p["field"]["Column"]["Expression"]["SourceRef"]["Entity"],
                        p["field"]["Column"]["Property"],
                    )
                    for p in group_proj
                    if "Column" in p["field"]
                }:
                    group_proj.append(build_column_proj(mapped_lod, active=True))
    # Assign to queryState
    powerbi_json["visual"]["query"]["queryState"]["Group"]["projections"] = group_proj

    return powerbi_json

import re
import sys
import os
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.tableau_cleaning import clean_tableau_name, clean_field_name, AGGREGATION_MAP


# To be updated for multitable compatablity, Issue: Parser ISSUE
def map_derivation_to_agg_func(derivation):
    if not derivation:
        return AGGREGATION_MAP.get("SUM", 0)  # Default SUM
    deriv = derivation.upper()
    return AGGREGATION_MAP.get(deriv, None)


def has_hierarchy(cols):
    """
    Returns True if any column or slice indicates a hierarchy is present
    (i.e., derivation is present and not 'none').
    """
    if isinstance(cols, dict):
        candidates = cols.get("cols", []) + cols.get("slices", [])
    elif isinstance(cols, list):
        candidates = cols
    else:
        return False
    for col in candidates:
        derivation = col.get("derivation", "").lower()
        if derivation and derivation != "none":
            return True
    return False


def make_hierarchy_projection(entity, prop, hierarchy_name, level):
    clean_entity = clean_tableau_name(entity)
    clean_prop = clean_field_name(prop)
    return {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {"SourceRef": {"Entity": clean_entity}},
                                "Name": "Variation",
                                "Property": clean_prop,
                            }
                        },
                        "Hierarchy": hierarchy_name,
                    }
                },
                "Level": level,
            }
        },
        "queryRef": f"{clean_entity}.{clean_prop}.Variation.{hierarchy_name}.{level}",
        "nativeQueryRef": f"{clean_prop} {level}",
        "active": True,
    }


def make_column_projection(entity, prop):
    clean_entity = clean_tableau_name(entity)
    clean_prop = clean_field_name(prop)
    return {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": clean_entity}},
                "Property": clean_prop,
            }
        },
        "queryRef": f"{clean_entity}.{clean_prop}",
        "nativeQueryRef": clean_prop,
    }


def make_aggregation_projection(entity, prop, agg_func_code, agg_name):
    clean_entity = clean_tableau_name(entity)
    clean_prop = clean_field_name(prop)
    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": clean_entity}},
                        "Property": clean_prop,
                    }
                },
                "Function": agg_func_code,
            }
        },
        "queryRef": f"{agg_name}({clean_entity}.{clean_prop})",
        "nativeQueryRef": f"{agg_name} of {clean_prop}",
    }


def extract_default_entity(tableau_json):
    worksheets = tableau_json.get("worksheets", [])
    if worksheets:
        ws = worksheets[0]
        ds = ws.get("datasource") or ws.get("table") or ws.get("parent-name")
        if ds:
            return clean_tableau_name(ds)
    ds = tableau_json.get("datasource") or tableau_json.get("table")
    if ds:
        return clean_tableau_name(ds)
    return None


def extract_all_columns(worksheet):
    cols = worksheet.get("cols", [])
    if isinstance(cols, list):
        return [c for c in cols if isinstance(c, dict)]
    return []


def extract_all_rows(worksheet):
    rows = worksheet.get("rows", [])
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def convert_tableau_to_powerbi_dual_axis(
    tableau_json, position=None, name=None, default_entity=None
):
    worksheets = tableau_json.get("worksheets", [])
    if not worksheets or not worksheets[0]:
        raise ValueError("No worksheets found in Tableau JSON")
    worksheet = worksheets[0]

    if not default_entity:
        default_entity = extract_default_entity(tableau_json) or "Orders"
    else:
        default_entity = clean_tableau_name(default_entity)

    # Columns Handling
    cols = extract_all_columns(worksheet)
    if not cols:
        raise ValueError("No columns found in worksheet")
    first_col = cols[0]
    col_name = clean_field_name(first_col.get("column"))
    cat_entity = clean_tableau_name(first_col.get("parent-name", default_entity))

    # Hierarchy and Category Projection logic (mirroring the reference code)
    use_hierarchy = has_hierarchy(cols)
    if use_hierarchy:
        hierarchy_name = "Date Hierarchy"
        levels = []
        # Collect hierarchy levels from cols
        for col in cols:
            if (
                "derivation" in col
                and col["derivation"]
                and str(col["derivation"]).lower() != "none"
            ):
                level = str(col["derivation"]).capitalize()
                if level not in levels:
                    levels.append(level)
        # Collect hierarchy levels from slices
        for s in worksheet.get("slices", []):
            if (
                "derivation" in s
                and s["derivation"]
                and str(s["derivation"]).lower() != "none"
            ):
                level = str(s["derivation"]).capitalize()
                if level not in levels:
                    levels.append(level)
        if not levels:
            levels = ["Month"]  # Default fallback level
        category_projections = [
            make_hierarchy_projection(cat_entity, col_name, hierarchy_name, level)
            for level in levels
        ]
    else:
        category_projections = [make_column_projection(cat_entity, col_name)]

    # Parse measures properly with regex from rows
    rows = extract_all_rows(worksheet)
    measure_names = []
    for row in rows:
        formula = row.get("name", "")
        parts = [p.strip() for p in formula.split("+")]
        for part in parts:
            match = re.search(
                r"\[\s*(?:sum|avg|countd|cntd|ctd|usr)\s*:\s*([^:\]]+)",
                part,
                re.IGNORECASE,
            )
            if match:
                prop = clean_field_name(match.group(1).strip())
                if prop and prop not in measure_names:
                    measure_names.append(prop)

    if not measure_names:
        measure_names.append("Sales")  # fallback measure

    # Build Y and Y2 projections for first two measures (dual axis)
    y_projections, y2_projections = [], []
    for i, measure_name in enumerate(measure_names):
        col_property = measure_name.split()[0]  # take first token
        entity = cat_entity
        agg_func_code = AGGREGATION_MAP.get("SUM", 0)  # Default to sum
        agg_name = "Sum"
        target_list = y_projections if i == 0 else y2_projections
        target_list.append(
            make_aggregation_projection(entity, col_property, agg_func_code, agg_name)
        )

    # Series encoding from worksheet (only if it is a valid categorical field, not placeholders)
    series_projections = []
    encodings = worksheet.get("encodings", {})
    color_encoding = encodings.get("color")
    if isinstance(color_encoding, list):
        color_encoding = color_encoding[0] if color_encoding else None
    if isinstance(color_encoding, dict):
        series_name = color_encoding.get("name") or color_encoding.get("column")
        if series_name and series_name not in ["[:Measure Names]", ":Measure Names"]:
            series_col = clean_field_name(series_name) or series_name
            series_projections.append(make_column_projection(cat_entity, series_col))

    # Default position if none provided
    position = position or {
        "x": 268.81325509147393,
        "y": 119.295823265447,
        "z": 0,
        "height": 488.3175698998964,
        "width": 930.50742147048663,
    }

    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": position,
        "visual": {
            "visualType": "lineStackedColumnComboChart",
            "query": {
                "queryState": {
                    "Category": {"projections": category_projections},
                    "Y": {"projections": y_projections},
                    "Y2": {"projections": y2_projections},
                }
            },
            "objects": {
                "labels": [
                    {"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}
                ]
            },
            "drillFilterOtherVisuals": True,
        },
    }

    if series_projections:
        powerbi_json["visual"]["query"]["queryState"]["Series"] = {
            "projections": series_projections
        }

    return powerbi_json

# visuals/funnel_chart.py
import uuid
import sys
import os
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.tableau_cleaning import clean_tableau_name, clean_field_name, map_aggregation


# To be modified for multi table compatability
# Helper to strip GUID-like suffix
def strip_guid_suffix(name):
    return re.sub(r"_[A-F0-9]{10,}$", "", name) if name else name


def convert_tableau_funnel_to_powerbi(tableau_json):
    """
    Dynamically converts a Tableau funnel chart JSON into Power BI funnel visual JSON.
    Detects category and measure fields from rows, cols, or encodings.
    Automatically maps aggregation and supports any dimension/measure combination.
    """

    # --- Step 1: Extract worksheet ---
    worksheet = tableau_json.get("worksheets", [{}])[0]
    enc = worksheet.get("encodings", {})
    rows = worksheet.get("rows", [])
    cols = worksheet.get("cols", [])

    # --- Step 2: Determine entity ---
    entity = "Orders"  # default fallback

    # --- Step 3: Detect category (dimension) dynamically ---
    category_info = None
    for key in ["color", "category", "row", "x"]:
        if key in enc:
            category_info = enc[key]
            break
    if not category_info and rows:
        category_info = rows[0]
    if not category_info and cols:
        category_info = cols[0]

    category_field = category_info.get("local-name") if category_info else None
    category_type = category_info.get("local-type") if category_info else None
    category_derivation = category_info.get("derivation") if category_info else None
    entity = category_info.get("parent-name") or entity

    # --- Step 4: Detect measure (value) dynamically ---
    measure_info = None
    for key in ["size", "y", "value", "text"]:
        if key in enc:
            measure_info = enc[key]
            break
    if not measure_info and rows and len(rows) > 1:
        measure_info = rows[1]
    if not measure_info and cols and len(cols) > 1:
        measure_info = cols[1]

    measure_field = measure_info.get("local-name") if measure_info else None
    agg_func = measure_info.get("derivation", "Sum") if measure_info else "Sum"

    # --- Step 5: Map aggregation dynamically ---
    agg_func = agg_func.title() if agg_func else "Sum"
    agg_code = map_aggregation(agg_func.lower(), 0)

    # --- Step 6: Validation ---
    if not category_field or not measure_field:
        raise ValueError(
            "Missing category or measure field. Cannot build Power BI funnel visual."
        )

    # --- Step 7: Build category projection ---
    category_projection = {
        "Column": {
            "Expression": {
                "SourceRef": {"Entity": clean_tableau_name(strip_guid_suffix(entity))}
            },
            "Property": clean_field_name(category_field),
        }
    }
    category_query_ref = f"{entity}.{category_field}"
    category_native_ref = category_field

    # --- Step 8: Build measure projection ---
    measure_projection = {
        "Aggregation": {
            "Expression": {
                "Column": {
                    "Expression": {
                        "SourceRef": {
                            "Entity": clean_tableau_name(strip_guid_suffix(entity))
                        }
                    },
                    "Property": clean_field_name(measure_field),
                }
            },
            "Function": agg_code,
        }
    }

    # --- Step 9: Build Power BI JSON dynamically ---
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": {"x": 100, "y": 100, "z": 0, "height": 500, "width": 700},
        "visual": {
            "visualType": "funnel",
            "query": {
                "queryState": {
                    "Category": {
                        "projections": [
                            {
                                "field": category_projection,
                                "queryRef": category_query_ref,
                                "nativeQueryRef": category_native_ref,
                                "active": True,
                            }
                        ]
                    },
                    "Y": {
                        "projections": [
                            {
                                "field": measure_projection,
                                "queryRef": f"{agg_func}({entity}.{measure_field})",
                                "nativeQueryRef": f"{agg_func} of {measure_field}",
                            }
                        ]
                    },
                },
                "sortDefinition": {
                    "sort": [{"field": measure_projection, "direction": "Descending"}],
                    "isDefaultSort": True,
                },
            },
            "objects": {},
            "drillFilterOtherVisuals": True,
        },
    }

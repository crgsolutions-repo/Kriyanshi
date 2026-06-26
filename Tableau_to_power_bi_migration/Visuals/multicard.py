import uuid
import random
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    clean_tableau_name,
    clean_field_name,
    AGGREGATION_MAP,
)


def extract_field_with_entity(field):
    """Extract field information from Tableau field definition."""
    if not isinstance(field, dict):
        return None

    native_name = field.get("Native name", "")
    if isinstance(native_name, str) and native_name.strip().lower() == "calculated":
        return None

    col_name = field.get("column")
    entity_name = field.get("parent-name", "")
    derivation = field.get("derivation", None)

    return {"Property": col_name, "Entity": entity_name, "Derivation": derivation}


def map_aggregation(func_name):
    """Map aggregation function name to Power BI function code."""
    if not func_name or not isinstance(func_name, str):
        return 0

    mapping = {"sum": 0, "avg": 1, "average": 1, "count": 2, "min": 3, "max": 4}
    return mapping.get(func_name.lower(), 0)


def agg_code_to_str(func):
    """Convert aggregation code to string representation."""
    mapping = {0: "Sum", 1: "Average", 2: "Count", 3: "Min", 4: "Max"}
    return mapping.get(func, "Sum")


def is_valid_field_name(name):
    """Check if field name is valid."""
    return (
        bool(name)
        and isinstance(name, str)
        and name.lower() not in {"none", "color", "text", ""}
    )


def convert_tableau_to_powerbi_multirow(json_in):
    """
    Convert Tableau worksheet JSON to Power BI multi-row card JSON.

    Args:
        json_in: Tableau worksheet JSON structure

    Returns:
        Power BI multi-row card JSON structure
    """
    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.3.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": {
            "x": random.uniform(9, 50),
            "y": random.uniform(0, 50),
            "z": 0,
            "height": random.uniform(250, 300),
            "width": random.uniform(650, 750),
        },
        "visual": {
            "visualType": "multiRowCard",
            "query": {
                "queryState": {"Values": {"projections": []}},
                "sortDefinition": {"sort": [], "isDefaultSort": True},
            },
            "drillFilterOtherVisuals": True,
        },
    }

    # Get the first worksheet
    worksheets = json_in.get("worksheets", [json_in])
    ws = worksheets[0]

    values_projections = []
    first_dimension = None

    # Process columns (dimensions)
    for col in ws.get("cols", []):
        mapped_col = extract_field_with_entity(col)
        if mapped_col and is_valid_field_name(mapped_col["Property"]):
            deriv = mapped_col.get("Derivation")

            # Skip aggregated fields in columns, they should be in text encodings
            if deriv and deriv.lower() not in {"none", ""}:
                continue

            # Add as dimension (non-aggregated field)
            projection = {
                "field": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": mapped_col["Entity"]}},
                        "Property": mapped_col["Property"],
                    }
                },
                "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}",
                "nativeQueryRef": mapped_col["Property"],
            }
            values_projections.append(projection)

            # Store first dimension for sorting
            if first_dimension is None:
                first_dimension = mapped_col

    # Process text encodings (measures)
    text_encodings = ws.get("encodings", {}).get("text", [])

    # Handle both single object and array
    if isinstance(text_encodings, dict):
        text_encodings = [text_encodings]
    elif not isinstance(text_encodings, list):
        text_encodings = []

    for text_enc in text_encodings:
        mapped_measure = extract_field_with_entity(text_enc)

        if mapped_measure and is_valid_field_name(mapped_measure["Property"]):
            property_name = mapped_measure["Property"]
            entity_name = mapped_measure["Entity"]
            agg_name = mapped_measure.get("Derivation", "Sum")

            # Map aggregation
            agg_code = map_aggregation(agg_name)
            agg_str = agg_code_to_str(agg_code)

            # Create aggregation projection
            projection = {
                "field": {
                    "Aggregation": {
                        "Expression": {
                            "Column": {
                                "Expression": {"SourceRef": {"Entity": entity_name}},
                                "Property": property_name,
                            }
                        },
                        "Function": agg_code,
                    }
                },
                "queryRef": f"{agg_str}({entity_name}.{property_name})",
                "nativeQueryRef": f"{agg_str} of {property_name}",
            }
            values_projections.append(projection)

    # Add projections to the query
    powerbi_json["visual"]["query"]["queryState"]["Values"][
        "projections"
    ] = values_projections

    # Add sorting based on first dimension if available
    if first_dimension:
        sort_field = {
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": first_dimension["Entity"]}},
                    "Property": first_dimension["Property"],
                }
            },
            "direction": "Ascending",
        }
        powerbi_json["visual"]["query"]["sortDefinition"]["sort"] = [sort_field]

    return powerbi_json

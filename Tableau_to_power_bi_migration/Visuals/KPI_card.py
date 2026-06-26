import re
import uuid
import json
import os
import time
import logging

# from utils.tableau_cleaning import map_aggregation


def improved_extract_field_with_entity(field):
    if not isinstance(field, dict):
        return None
    native_name = field.get("Native name", "")
    if isinstance(native_name, str) and native_name.strip().lower() == "calculated":
        return None
    col_name = field.get("column")
    entity_name = field.get("parent-name", "")
    derivation = field.get("derivation", None)
    if not col_name and "name" in field:
        match = re.match(
            r"\[(sum|avg|count|min|max):(.+?):qk\]",
            field.get("name", ""),
            re.IGNORECASE,
        )
        if match:
            agg, col = match.groups()
            col_name = col
            derivation = agg.capitalize()
        else:
            return None
    if not col_name:
        return None
    return {"Property": col_name, "Entity": entity_name, "Derivation": derivation}


def map_aggregation_for_card(func_name):
    mapping = {"sum": 0, "avg": 1, "average": 1, "count": 2, "min": 3, "max": 4}
    return mapping.get(func_name.lower(), 0)


def is_valid_field_name(name: str):
    return (
        bool(name)
        and isinstance(name, str)
        and name.lower() not in {"none", "color", "text", ""}
    )


def extract_kpi_card_fields(worksheet_json):
    """
    Extracts KPI card column info from a Tableau worksheet JSON.
    Handles single dict or list in "cols".
    Returns list of clean field dicts.
    """
    fields = []
    cols = worksheet_json.get("cols", [])
    # Handle case where cols is a single dict instead of list
    if isinstance(cols, dict):
        cols = [cols]

    for field in cols:
        column = field.get("column")
        entity = field.get("parent-name", "")
        derivation = field.get("derivation", "Sum")

        if not column or not isinstance(column, str):
            continue

        field_info = {
            "Property": column.strip(),
            "Entity": entity.strip() or "Unknown",
            "Derivation": derivation.strip().capitalize(),
        }
        fields.append(field_info)

    return fields


def convert_kpi_to_powerbi_json(worksheet, position_x=0, idx=0):
    """
    Converts KPI data to Power BI JSON format.

    Args:
        worksheet: Can be either:
            - A dict with 'worksheets' key containing list of worksheets
            - A single worksheet dict
            - A field dict with Entity, Property, Derivation keys
        position_x: X position for the visual (default: 0)
        idx: Index for tab order calculation (default: 0)

    Returns:
        Power BI visual JSON or list of visuals
    """
    # Handle wrapped worksheet format: {"worksheets": [worksheet]}
    if isinstance(worksheet, dict) and "worksheets" in worksheet:
        worksheets = worksheet["worksheets"]
        if not worksheets:
            return []
        worksheet = worksheets[0]

    # Check if this is already a field dict (has Entity, Property, Derivation)
    if (
        isinstance(worksheet, dict)
        and "Entity" in worksheet
        and "Property" in worksheet
    ):
        field = worksheet
    else:
        # Extract fields from worksheet
        fields = extract_kpi_card_fields(worksheet)
        if not fields:
            return []

        # If multiple fields, create multiple KPI cards
        if len(fields) > 1:
            visuals = []
            for i, field in enumerate(fields):
                visual = _create_single_kpi_visual(
                    field, position_x + (i * 270), idx + i
                )
                visuals.append(visual)
            return visuals

        field = fields[0]

    # Create single KPI visual
    return _create_single_kpi_visual(field, position_x, idx)


def _create_single_kpi_visual(field, position_x, idx):
    """Helper function to create a single KPI visual"""
    entity = field.get("Entity", "Unknown")
    prop = field.get("Property", "Property")
    derivation = field.get("Derivation", "Sum")
    agg_code = map_aggregation_for_card(derivation)

    agg_strs = ["Sum", "Avg", "Count", "Min", "Max"]
    agg_str = agg_strs[agg_code]

    visual_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.3.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": {
            "x": position_x,
            "y": 0,
            "z": 6000,
            "height": 135,
            "width": 260,
            "tabOrder": 6000 + idx,
        },
        "visual": {
            "visualType": "cardVisual",
            "query": {
                "queryState": {
                    "Data": {
                        "projections": [
                            {
                                "field": {
                                    "Aggregation": {
                                        "Expression": {
                                            "Column": {
                                                "Expression": {
                                                    "SourceRef": {"Entity": entity}
                                                },
                                                "Property": prop,
                                            }
                                        },
                                        "Function": agg_code,
                                    }
                                },
                                "queryRef": f"{agg_str}({entity}.{prop})",
                                "nativeQueryRef": f"{agg_str} of {prop}",
                                "format": "0.00",
                            }
                        ]
                    }
                },
                "sortDefinition": {
                    "sort": [
                        {
                            "field": {
                                "Aggregation": {
                                    "Expression": {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {"Entity": entity}
                                            },
                                            "Property": prop,
                                        }
                                    },
                                    "Function": agg_code,
                                }
                            },
                            "direction": "Descending",
                        }
                    ],
                    "isDefaultSort": True,
                },
            },
            "objects": {
                "layout": [
                    {
                        "properties": {
                            "alignment": {"expr": {"Literal": {"Value": "'middle'"}}}
                        }
                    }
                ],
                "padding": [
                    {
                        "properties": {
                            "paddingSelection": {
                                "expr": {"Literal": {"Value": "'Normal'"}}
                            }
                        },
                        "selector": {"id": "default"},
                    }
                ],
                "value": [
                    {
                        "properties": {
                            "horizontalAlignment": {
                                "expr": {"Literal": {"Value": "'center'"}}
                            }
                        },
                        "selector": {"id": "default"},
                    }
                ],
            },
            "drillFilterOtherVisuals": True,
        },
    }
    return visual_json

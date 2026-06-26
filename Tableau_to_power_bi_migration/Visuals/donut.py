# visuals/donut.py

import sys
import os
import uuid
import random

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.tableau_cleaning import (
    clean_field_name,
    clean_tableau_name,
    agg_code_to_str,
    is_valid_field_name,
    map_aggregation,
)

# =====================================================
# FIELD EXTRACTION
# =====================================================

def extract_field_with_entity(field):

    if not isinstance(field, dict):
        return None

    raw_col = (
        field.get("column")
        or field.get("local-name")
        or field.get("name")
    )

    if not raw_col:
        return None

    col_name = clean_field_name(raw_col)

    if not is_valid_field_name(col_name):
        return None

    entity_name = clean_tableau_name(
        field.get("parent-name", "")
    )

    if not entity_name:
        entity_name = "Table1"

    derivation = field.get("derivation")

    return {
        "Property": col_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": str(
            field.get("local-type", "")
        ).lower(),
    }


# =====================================================
# CATEGORY PROJECTION
# =====================================================

def build_category_projection(mapped_col):

    deriv = str(
        mapped_col.get("Derivation", "")
    ).lower()

    # ==========================================
    # DATE HIERARCHY
    # ==========================================

    if deriv in {
        "year",
        "quarter",
        "month",
        "day",
        "week",
    }:

        return {
            "field": {
                "HierarchyLevel": {
                    "Expression": {
                        "Hierarchy": {
                            "Expression": {
                                "PropertyVariationSource": {
                                    "Expression": {
                                        "SourceRef": {
                                            "Entity": mapped_col["Entity"]
                                        }
                                    },
                                    "Name": "Variation",
                                    "Property": mapped_col["Property"],
                                }
                            },
                            "Hierarchy": "Date Hierarchy",
                        }
                    },
                    "Level": deriv.capitalize(),
                }
            },
            "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}.Variation.Date Hierarchy.{deriv.capitalize()}",
            "nativeQueryRef": f"{mapped_col['Property']} {deriv.capitalize()}",
            "active": True,
        }

    # ==========================================
    # NORMAL CATEGORY
    # ==========================================

    return {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Entity": mapped_col["Entity"]
                    }
                },
                "Property": mapped_col["Property"],
            }
        },
        "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}",
        "nativeQueryRef": mapped_col["Property"],
        "active": True,
    }


# =====================================================
# MEASURE PROJECTION
# =====================================================

def build_measure_projection(mapped_col):

    agg_name = mapped_col.get("Derivation") or "Sum"

    agg_code = map_aggregation(agg_name)

    if agg_code is None:
        agg_code = 0

    agg_str = agg_code_to_str(agg_code)

    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Entity": mapped_col["Entity"]
                            }
                        },
                        "Property": mapped_col["Property"],
                    }
                },
                "Function": agg_code,
            }
        },
        "queryRef": f"{agg_str}({mapped_col['Entity']}.{mapped_col['Property']})",
        "nativeQueryRef": f"{agg_str} of {mapped_col['Property']}",
    }


# =====================================================
# FILTER
# =====================================================

def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


# =====================================================
# SAFE ENCODING FETCH
# =====================================================

def get_encoding_field(encodings, encoding_name):

    if encoding_name not in encodings:
        return None

    encoding = encodings[encoding_name]

    if isinstance(encoding, list):

        if len(encoding) > 0:
            return encoding[0]

        return None

    if isinstance(encoding, dict):
        return encoding

    return None


# =====================================================
# FIND DONUT ENCODINGS
# =====================================================

def find_donut_encodings(ws):

    direct_encodings = (
        ws.get("encodings")
        or ws.get("table", {}).get("encodings")
    )

    if direct_encodings:
        return direct_encodings

    panes = (
        ws.get("table", {}).get("panes", [])
        or ws.get("panes", [])
    )

    for pane in panes:

        enc = pane.get("encodings", {})

        if not enc:
            continue

        keys = set(enc.keys())

        if (
            "color" in keys
            or "wedge-size" in keys
            or "size" in keys
            or "text" in keys
        ):
            return enc

    return {}


# =====================================================
# MAIN CONVERTER
# =====================================================

def convert_tableau_to_powerbi_donut(tableau_json):

    worksheets = tableau_json.get(
        "worksheets",
        [tableau_json]
    )

    ws = worksheets[0]

    encodings = find_donut_encodings(ws)

    if not encodings:
        raise ValueError(
            f"Could not find donut encodings dynamically."
        )

    # =====================================================
    # CATEGORY FIELD
    # =====================================================

    category_field = None

    color_encoding = encodings.get("color")

    if isinstance(color_encoding, list):

        for fld in color_encoding:

            if not isinstance(fld, dict):
                continue

            local_type = str(
                fld.get("local-type", "")
            ).lower()

            if local_type in {
                "string",
                "date",
                "datetime",
            }:
                category_field = fld
                break

        # fallback
        if not category_field:

            for fld in color_encoding:

                if isinstance(fld, dict):
                    category_field = fld
                    break

    elif isinstance(color_encoding, dict):

        category_field = color_encoding

    # =====================================================
    # CATEGORY FALLBACK
    # =====================================================

    if not category_field:

        rows = ws.get("rows", [])
        cols = ws.get("cols", [])

        for fld in rows + cols:

            local_type = str(
                fld.get("local-type", "")
            ).lower()

            if local_type in {
                "string",
                "date",
                "datetime",
            }:
                category_field = fld
                break

    # =====================================================
    # MEASURE FIELD
    # =====================================================

    measure_field = (
        get_encoding_field(encodings, "wedge-size")
        or get_encoding_field(encodings, "angle")
        or get_encoding_field(encodings, "size")
    )

    # =====================================================
    # TEXT FALLBACK
    # =====================================================

    if not measure_field:

        text_enc = encodings.get("text", [])

        if not isinstance(text_enc, list):
            text_enc = [text_enc]

        for fld in text_enc:

            if not isinstance(fld, dict):
                continue

            local_type = str(
                fld.get("local-type", "")
            ).lower()

            derivation = str(
                fld.get("derivation", "")
            ).lower()

            if (
                derivation in {
                    "sum",
                    "avg",
                    "average",
                    "count",
                    "min",
                    "max",
                    "median",
                }
                or local_type in {
                    "real",
                    "integer",
                    "numeric",
                }
            ):
                measure_field = fld
                break

    # =====================================================
    # MEASURE FALLBACK
    # =====================================================

    if not measure_field:

        rows = ws.get("rows", [])
        cols = ws.get("cols", [])

        for fld in rows + cols:

            local_type = str(
                fld.get("local-type", "")
            ).lower()

            if local_type in {
                "real",
                "integer",
                "numeric",
            }:
                measure_field = fld
                break

    # =====================================================
    # VALIDATION
    # =====================================================

    category = extract_field_with_entity(category_field)

    measure = extract_field_with_entity(measure_field)

    if not category:
        raise ValueError(
            "Donut category field not found."
        )

    if not measure:
        raise ValueError(
            "Donut measure field not found."
        )

    # =====================================================
    # BUILD PROJECTIONS
    # =====================================================

    category_projection = build_category_projection(
        category
    )

    measure_projection = build_measure_projection(
        measure
    )

    # =====================================================
    # FILTERS
    # =====================================================

    filters = [

        build_filter(
            category_projection,
            "Categorical"
        ),

        build_filter(
            measure_projection,
            "Advanced"
        ),
    ]

    # =====================================================
    # FINAL POWER BI JSON
    # =====================================================

    powerbi_json = {

        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.5.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x": random.uniform(50, 120),
            "y": random.uniform(150, 300),
            "z": 0,
            "height": random.uniform(340, 360),
            "width": random.uniform(480, 520),
        },

        "visual": {

            "visualType": "donutChart",

            "query": {

                "queryState": {

                    "Category": {
                        "projections": [
                            category_projection
                        ]
                    },

                    "Y": {
                        "projections": [
                            measure_projection
                        ]
                    },
                },

                "sortDefinition": {

                    "sort": [
                        {
                            "field": measure_projection["field"],
                            "direction": "Descending",
                        }
                    ],

                    "isDefaultSort": True,
                },
            },

            "drillFilterOtherVisuals": True,
        },

        "filterConfig": {
            "filters": filters
        },
    }

    return powerbi_json                            
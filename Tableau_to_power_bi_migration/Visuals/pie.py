# visuals/pie_chart.py

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
    clean_tableau_name,
    clean_field_name,
    agg_code_to_str,
    is_valid_field_name,
    map_aggregation,
)

# =========================================================
# HELPERS
# =========================================================

def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


def get_encoding_field(encodings, encoding_name):

    if not encodings:
        return None

    encoding = encodings.get(encoding_name)

    if isinstance(encoding, list):

        if encoding:
            return encoding[0]

        return None

    if isinstance(encoding, dict):
        return encoding

    return None


def is_measure(f):

    if not isinstance(f, dict):
        return False

    derivation = str(
        f.get("derivation", "")
    ).lower()

    measure_derivations = {
        "sum",
        "avg",
        "average",
        "count",
        "countd",
        "cnt",
        "min",
        "max",
        "median",
        "stdev",
        "var"
    }

    if derivation in measure_derivations:
        return True

    # Table calculations
    if f.get("table-calc:type"):
        return True

    return False
# =========================================================
# FIELD EXTRACTION
# =========================================================

def extract_field_with_entity(field):

    if not field:
        return None

    if not isinstance(field, dict):
        return None

    raw_col = (

        field.get("column")

        or field.get("local-name")

        or field.get("field")

        or field.get("fieldName")

        or field.get("name")

        or field.get("caption")
    )

    if not raw_col:
        return None

    property_name = clean_field_name(raw_col)

    if not property_name:
        return None

    if not is_valid_field_name(property_name):
        return None

    entity_name = clean_tableau_name(
        field.get("parent-name")
        or field.get("table")
        or "Table1"
    )

    derivation = field.get("derivation")

    return {
        "Property": property_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": str(
            field.get("local-type", "")
        ).lower(),
    }


# =========================================================
# CATEGORY PROJECTION
# =========================================================

def build_category_projection(mapped_col):

    deriv = str(
        mapped_col.get("Derivation", "")
    ).lower()

    # =====================================================
    # DATE HIERARCHY SUPPORT
    # =====================================================

    if deriv in {
        "year",
        "quarter",
        "month",
        "day",
        "week",
    }:

        level = deriv.capitalize()

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
                    "Level": level,
                }
            },

            "queryRef":
                f"{mapped_col['Entity']}."
                f"{mapped_col['Property']}."
                f"Variation.Date Hierarchy.{level}",

            "nativeQueryRef":
                f"{mapped_col['Property']} {level}",

            "active": True,
        }

    # =====================================================
    # NORMAL CATEGORY
    # =====================================================

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

        "queryRef":
            f"{mapped_col['Entity']}."
            f"{mapped_col['Property']}",

        "nativeQueryRef":
            mapped_col["Property"],

        "active": True,
    }


# =========================================================
# MEASURE PROJECTION
# =========================================================

def build_measure_projection(mapped_col):

    agg_name = (
        mapped_col.get("Derivation")
        or "Sum"
    )

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

        "queryRef":
            f"{agg_str}("
            f"{mapped_col['Entity']}."
            f"{mapped_col['Property']})",

        "nativeQueryRef":
            f"{agg_str} of "
            f"{mapped_col['Property']}",
    }


# =========================================================
# MAIN CONVERTER
# =========================================================

def convert_tableau_to_powerbi(tableau_json):

    worksheets = tableau_json.get(
        "worksheets",
        [tableau_json]
    )

    # =====================================================
    # FIND PIE WORKSHEET
    # =====================================================

    ws = None

    for sheet in worksheets:

        marks = [
            str(m).lower()
            for m in sheet.get("marks", [])
        ]

        if "pie" in marks:

            ws = sheet
            break

    if not ws:
        raise ValueError(
            "Pie worksheet not found"
        )

    # =====================================================
    # GET DATA
    # =====================================================

    encodings = (
        ws.get("encodings")
        or {}
    )

    rows = ws.get("rows", [])
    cols = ws.get("cols", [])

    # =====================================================
    # CATEGORY DETECTION
    # =====================================================

    category_field = (

        get_encoding_field(encodings, "color")

        or get_encoding_field(encodings, "label")

        or get_encoding_field(encodings, "detail")
    )

    # fallback
    if not category_field:

        for fld in rows + cols:

            if not is_measure(fld):

                category_field = fld
                break

    # =====================================================
    # MEASURE DETECTION
    # =====================================================

    measure_field = (

        get_encoding_field(encodings, "angle")

        or get_encoding_field(encodings, "wedge-size")

        or get_encoding_field(encodings, "size")

        or get_encoding_field(encodings, "text")
    )

    # fallback
    if not measure_field:

        # Search all encodings deeply
        for enc_name, enc_val in encodings.items():

            if isinstance(enc_val, list):

                for item in enc_val:

                    if isinstance(item, dict) and is_measure(item):

                        measure_field = item
                        break

            elif isinstance(enc_val, dict):

                if is_measure(enc_val):

                    measure_field = enc_val

            if measure_field:
                break

    # rows/cols fallback
    if not measure_field:

        for fld in rows + cols:

            if is_measure(fld):

                measure_field = fld
                break
    # =====================================================
    # VALIDATION
    # =====================================================

    category = extract_field_with_entity(
        category_field
    )

    measure = extract_field_with_entity(
        measure_field
    )

    if not category:
        raise ValueError(
            f"Pie category field not found. "
            f"Worksheet: {ws.get('worksheet')}"
        )

    if not measure:
        raise ValueError(
            f"Pie measure field not found. "
            f"Worksheet: {ws.get('worksheet')}"
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

        "$schema":
            "https://developer.microsoft.com/"
            "json-schemas/fabric/item/report/"
            "definition/visualContainer/2.5.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x": 349, # random.uniform(50, 120),
            "y": 359, # random.uniform(120, 220),
            "z": 0,
            "height": 300,
            "width": 500,
        },

        "visual": {

            "visualType": "pieChart",

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
                            "field":
                                measure_projection["field"],

                            "direction":
                                "Descending",
                        }
                    ],

                    "isDefaultSort": True,
                },
            },

            "objects": {

                "labels": [
                    {
                        "properties": {

                            "labelStyle": {
                                "expr": {
                                    "Literal": {
                                        "Value": "'Data'"
                                    }
                                }
                            },

                            "labelDisplayUnits": {
                                "expr": {
                                    "Literal": {
                                        "Value": "1D"
                                    }
                                }
                            },

                            "labelPrecision": {
                                "expr": {
                                    "Literal": {
                                        "Value": "0L"
                                    }
                                }
                            },
                        }
                    }
                ]
            },

            "drillFilterOtherVisuals": True,
        },

        "filterConfig": {
            "filters": filters
        },
    }

    return powerbi_json
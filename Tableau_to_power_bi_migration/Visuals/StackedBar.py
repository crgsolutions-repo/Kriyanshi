# visuals/StackedBar.py

import uuid
import random
import json


# =========================================================
# HELPERS
# =========================================================

def clean_field_name(field_name):

    if not field_name or not isinstance(field_name, str):
        return None

    field_name = field_name.replace("[", "").replace("]", "")

    parts = field_name.split(":")

    # sum:Sales:qk -> Sales
    # none:Region:nk -> Region

    if len(parts) >= 2:
        return parts[1].strip()

    return field_name.strip()


def is_valid_field_name(name):

    invalid = {
        "",
        "none",
        "measure names",
        "measure values",
    }

    return (
        bool(name)
        and isinstance(name, str)
        and name.lower() not in invalid
    )


def is_measure_field(field):
    if not isinstance(field, dict):
        return False

    deriv = str(field.get("derivation", "")).lower()
    local_type = str(field.get("local-type", "")).lower()

    if deriv in {
        "sum",
        "avg",
        "average",
        "count",
        "countd",
        "min",
        "max",
        "median",
        "percent",
    }:
        return True

    if local_type in {
        "real",
        "integer",
        "float",
        "numeric",
        "double",
    }:
        return True

    return False


def map_aggregation(func_name):

    mapping = {
        "sum": 0,
        "avg": 1,
        "average": 1,
        "count": 2,
        "min": 3,
        "max": 4,
        "median": 0,
    }

    return mapping.get(
        str(func_name).lower(),
        0
    )


def agg_code_to_str(code):

    mapping = {
        0: "Sum",
        1: "Avg",
        2: "Count",
        3: "Min",
        4: "Max",
    }

    return mapping.get(code, "Sum")


# =========================================================
# FIELD EXTRACTION
# =========================================================

def extract_field_with_entity(field):

    if not isinstance(field, dict):
        return None

    raw_col = (
        field.get("column")
        or field.get("local-name")
    )

    if not raw_col:
        return None

    col_name = clean_field_name(raw_col)

    if not is_valid_field_name(col_name):
        return None

    entity_name = (
        field.get("parent-name")
        or "Orders"
    )

    derivation = field.get("derivation")

    return {
        "Property": col_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": str(
            field.get("local-type", "")
        ).lower(),
    }


# =========================================================
# GET VALID ENCODING
# =========================================================

def get_encoding(encodings, name):

    if name not in encodings:
        return None

    enc = encodings[name]

    if not isinstance(enc, list):
        enc = [enc]

    for item in enc:

        if not isinstance(item, dict):
            continue

        raw_col = (
            item.get("column")
            or item.get("local-name")
            or ""
        )

        cleaned = clean_field_name(raw_col)

        if not is_valid_field_name(cleaned):
            continue

        return item

    return None


# =========================================================
# CATEGORY PROJECTION
# =========================================================

def build_category_projection(mapped_col):

    deriv = mapped_col.get("Derivation")

    # DATE HIERARCHY SUPPORT

    if deriv and deriv.lower() in {
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


# =========================================================
# SERIES PROJECTION
# =========================================================

def build_series_projection(mapped_col):

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


# =========================================================
# FILTER
# =========================================================

def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


# =========================================================
# MAIN CONVERTER
# =========================================================

def convert_tableau_to_powerbi_stacked_bar_2T(tableau_json):

    worksheets = tableau_json.get(
        "worksheets",
        [tableau_json]
    )

    ws = worksheets[0]

    encodings = (
        ws.get("encodings")
        or ws.get("table", {}).get("encodings")
        or {}
    )

    table = ws.get("table", {})

    panes = table.get("panes", [])

    for pane in panes:

        pane_enc = pane.get("encodings", {})

        if pane_enc:
            encodings.update(pane_enc)

    rows = ws.get("rows", [])
    cols = ws.get("cols", [])

    # =====================================================
    # CATEGORY FIELD
    # =====================================================

    category_field = None

    dimension_fields = []

    for fld in cols + rows:

        if not isinstance(fld, dict):
            continue

        deriv = str(
            fld.get("derivation", "")
        ).lower()

        local_type = str(
            fld.get("local-type", "")
        ).lower()

        if (
            deriv == "none"
            or local_type in {
                "string",
                "date",
                "datetime",
            }
        ):

            dimension_fields.append(fld)

    if dimension_fields:
        category_field = dimension_fields[0]

    # =====================================================
    # SERIES FIELD (LEGEND)
    # =====================================================

    series_field = None

    # ---------------------------------------------
    # 1. COLOR ENCODING
    # ---------------------------------------------

    series_field = get_encoding(
        encodings,
        "color"
    )

    # reject measure-based series selections
    if is_measure_field(series_field):
        series_field = None

    # ---------------------------------------------
    # 2. DETAIL ENCODING
    # ---------------------------------------------

    if not series_field:

        series_field = get_encoding(
            encodings,
            "detail"
        )

        if is_measure_field(series_field):
            series_field = None

    # ---------------------------------------------
    # 3. SECOND DIMENSION
    # ---------------------------------------------

    if not series_field and category_field:

        category_name = clean_field_name(
            category_field.get("column", "")
        )

        for fld in dimension_fields:

            fld_name = clean_field_name(
                fld.get("column", "")
            )

            if (
                fld_name
                and fld_name != category_name
                and not is_measure_field(fld)
            ):

                series_field = fld
                break

    # ---------------------------------------------
    # 4. FORCE FROM COLS
    # ---------------------------------------------

    if not series_field:

        for fld in cols:

            if not isinstance(fld, dict):
                continue

            fld_name = clean_field_name(
                fld.get("column", "")
            )

            category_name = clean_field_name(
                category_field.get("column", "")
            )

            if (
                fld_name
                and fld_name != category_name
                and not is_measure_field(fld)
            ):

                local_type = str(
                    fld.get("local-type", "")
                ).lower()

                deriv = str(
                    fld.get("derivation", "")
                ).lower()

                if (
                    deriv == "none"
                    or local_type in {
                        "string",
                        "date",
                        "datetime",
                    }
                ):

                    series_field = fld
                    break

    print("\n========== SERIES FIELD ==========")

    print(
        json.dumps(
            series_field,
            indent=2
        )
    )

    print("==================================\n")

    # =====================================================
    # MEASURE FIELD
    # =====================================================

    measure_field = None

    for fld in rows + cols:

        if not isinstance(fld, dict):
            continue

        deriv = str(
            fld.get("derivation", "")
        ).lower()

        local_type = str(
            fld.get("local-type", "")
        ).lower()

        if (
            deriv in {
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
                "float",
                "numeric",
            }
        ):

            measure_field = fld
            break

    if not measure_field:

        measure_field = (
            get_encoding(encodings, "size")
            or get_encoding(encodings, "text")
        )

    # =====================================================
    # MAP FIELDS
    # =====================================================

    category = extract_field_with_entity(
        category_field
    )

    series = extract_field_with_entity(
        series_field
    )

    measure = extract_field_with_entity(
        measure_field
    )

    # =====================================================
    # VALIDATION
    # =====================================================

    if not category:
        raise ValueError(
            "Stacked bar category not found."
        )

    if not measure:
        raise ValueError(
            "Stacked bar measure not found."
        )

    # =====================================================
    # BUILD PROJECTIONS
    # =====================================================

    category_projection = (
        build_category_projection(category)
    )

    measure_projection = (
        build_measure_projection(measure)
    )

    query_state = {
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
    }

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
    # FINAL SAFETY CHECK FOR SERIES
    # =====================================================

    if series and measure:
        same_as_measure = (
            series["Property"] == measure["Property"]
            and series["Entity"] == measure["Entity"]
        )

        if same_as_measure:
            series = None

    # =====================================================
    # SERIES / LEGEND
    # =====================================================

    if series:

        series_projection = (
            build_series_projection(series)
        )

        query_state["Series"] = {
            "projections": [
                series_projection
            ]
        }

        filters.append(
            build_filter(
                series_projection,
                "Categorical"
            )
        )

    # =====================================================
    # FINAL JSON
    # =====================================================

    powerbi_json = {

        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.5.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x": random.uniform(50, 120),
            "y": random.uniform(50, 120),
            "z": 0,
            "height": 610,
            "width": 1100,
        },

        "visual": {

            "visualType": "columnChart",

            "query": {

                "queryState": query_state,

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

    print("\n========== FINAL JSON ==========")

    print(
        json.dumps(
            powerbi_json,
            indent=2
        )
    )

    print("================================\n")

    return powerbi_json

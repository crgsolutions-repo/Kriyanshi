
import uuid
import random
import sys
import os

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
)

from utils.tableau_cleaning import (
    map_aggregation,
    expand_axis_fields,
    enrich_field_from_workbook,
    collect_table_measure_fields,
    is_measure_like_table_field,
    is_measure_names_placeholder_field,
    recover_partial_tableau_field,
)


# =========================================================
# HELPERS
# =========================================================

def clean_tableau_name(name):

    if not name:
        return None

    s = str(name)

    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]

    replacements = [
        "none:",
        "sum:",
        "avg:",
        "count:",
        ":qk",
        ":nk",
        ":ok",
    ]

    for r in replacements:
        s = s.replace(r, "")

    if "." in s:
        s = s.split(".")[-1]

    return s.strip()


def is_valid_field_name(name):

    return (
        bool(name)
        and isinstance(name, str)
        and name.lower()
        not in {
            "",
            "measure names",
            "measure values",
            "multiple values",
        }
    )


def agg_name(code):

    mapping = {
        0: "Sum",
        1: "Avg",
        2: "Count",
        3: "Min",
        4: "Max",
    }

    return mapping.get(code, "Sum")


# =========================================================
# DATE HIERARCHY
# =========================================================

def is_date_hierarchy_level(level):

    if not level:
        return False

    return str(level).lower() in {
        "year",
        "quarter",
        "month",
        "day",
        "week",
    }


def build_date_hierarchy_projection(
    entity,
    prop,
    level
):

    level = level.capitalize()

    return {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {
                                    "SourceRef": {
                                        "Entity": entity
                                    }
                                },
                                "Name": "Variation",
                                "Property": prop,
                            }
                        },
                        "Hierarchy": "Date Hierarchy",
                    }
                },
                "Level": level,
            }
        },
        "queryRef": (
            f"{entity}.{prop}"
            f".Variation.Date Hierarchy.{level}"
        ),
        "nativeQueryRef": f"{prop} {level}",
        "active": True,
    }


# =========================================================
# FIELD EXTRACTION
# =========================================================

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

    property_name = clean_tableau_name(raw_col)

    if not is_valid_field_name(property_name):
        return None

    entity_name = (
        field.get("parent-name")
        or "Orders"
    )

    entity_name = entity_name.replace(".csv", "")

    derivation = field.get("derivation")

    local_type = str(
        field.get("local-type", "")
    ).lower()

    return {
        "Property": property_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": local_type,
    }


# =========================================================
# FIELD TYPE DETECTION
# =========================================================

def is_measure_field(field):

    derivation = str(
        field.get("Derivation", "")
    ).lower()

    if derivation in {
        "sum",
        "avg",
        "average",
        "count",
        "min",
        "max",
    }:
        return True

    datatype = str(
        field.get("LocalType", "")
    ).lower()

    if datatype in {
        "real",
        "integer",
        "number",
        "numeric",
        "float",
        "double",
    }:
        return True

    return False


# =========================================================
# PROJECTION BUILDERS
# =========================================================

def build_dimension_projection(entity, prop):

    return {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Entity": entity
                    }
                },
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
        "active": True,
    }


def build_measure_projection(
    entity,
    prop,
    agg_code
):

    agg_str = agg_name(agg_code)

    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Entity": entity
                            }
                        },
                        "Property": prop,
                    }
                },
                "Function": agg_code,
            }
        },
        "queryRef": (
            f"{agg_str}({entity}.{prop})"
        ),
        "nativeQueryRef": (
            f"{agg_str} of {prop}"
        ),
    }


# =========================================================
# FILTER BUILDER
# =========================================================

def build_filter(
    field_projection,
    filter_type
):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


# =========================================================
# MAIN CONVERTER
# =========================================================

def convert_tableau_pivot_to_powerbi(json_in):

    worksheets = json_in.get(
        "worksheets",
        [json_in]
    )

    if not isinstance(worksheets, list):
        worksheets = [worksheets]

    ws = worksheets[0]
    workbook = json_in.get("workbook") or json_in

    rows_data = [
        enrich_field_from_workbook(f, workbook)
        for f in expand_axis_fields(ws.get("rows", []))
    ]
    cols_data = [
        enrich_field_from_workbook(f, workbook)
        for f in expand_axis_fields(ws.get("cols", []))
    ]

    # =====================================================
    # BASE VISUAL
    # =====================================================

    powerbi_json = {

        "$schema":
        "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.5.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x": 0, # random.uniform(40, 80),
            "y": 359, # random.uniform(40, 90),
            "z": 0,
            "height": 360,
            "width": 294,
        },

        "visual": {

            "visualType": "pivotTable",

            "query": {

                "queryState": {

                    "Rows": {
                        "projections": []
                    },

                    "Columns": {
                        "projections": []
                    },

                    "Values": {
                        "projections": []
                    },
                },

                "sortDefinition": {
                    "isDefaultSort": True
                },
            },

            "drillFilterOtherVisuals": True,
        },

        "filterConfig": {
            "filters": []
        },
    }

    def collect_axis_dimensions(axis_fields):
        dimensions = []
        seen = set()
        for fld in axis_fields:
            fld = recover_partial_tableau_field(fld) or fld
            if is_measure_names_placeholder_field(fld):
                continue
            if is_measure_like_table_field(fld):
                continue
            mapped = extract_field_with_entity(fld)
            if not mapped:
                continue
            key = (
                mapped["Entity"],
                mapped["Property"],
                mapped.get("Derivation"),
            )
            if key in seen:
                continue
            seen.add(key)
            dimensions.append(mapped)
        return dimensions

    row_dimensions = collect_axis_dimensions(rows_data)
    col_dimensions = collect_axis_dimensions(cols_data)
    collected_measures = collect_table_measure_fields(ws, workbook)
    values = [proj for _, proj in collected_measures]

    if not row_dimensions and not col_dimensions:
        return None
    if not values:
        return None

    row_filters = []

    def append_dimension(dim, target_key):
        derivation = dim.get("Derivation")
        if is_date_hierarchy_level(derivation):
            projection = build_date_hierarchy_projection(
                dim["Entity"], dim["Property"], derivation
            )
        else:
            projection = build_dimension_projection(
                dim["Entity"], dim["Property"]
            )
        powerbi_json["visual"]["query"]["queryState"][target_key][
            "projections"
        ].append(projection)
        row_filters.append(build_filter(projection, "Categorical"))

    for dim in row_dimensions:
        append_dimension(dim, "Rows")

    for dim in col_dimensions:
        append_dimension(dim, "Columns")

    measure_filters = []
    for measure_projection in values:
        measure_filters.append(
            build_filter(measure_projection, "Advanced")
        )

    powerbi_json["visual"]["query"]["queryState"]["Values"]["projections"] = values

    # =====================================================
    # FILTERS
    # =====================================================

    powerbi_json["filterConfig"]["filters"] = (
        row_filters + measure_filters
    )

    return powerbi_json


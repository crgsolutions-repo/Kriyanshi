# visuals/table.py

import uuid
import random
import re

from utils.tableau_cleaning import (
    parse_tableau_calc_formula,
    expand_axis_fields,
    enrich_field_from_workbook,
    collect_table_measure_fields,
    is_measure_like_table_field,
    is_measure_names_placeholder_field,
    recover_partial_tableau_field,
)

# =========================================================
# CLEANING HELPERS
# =========================================================

def clean_tableau_name(name):

    if not name:
        return "Table1"

    s = str(name)

    s = s.replace("[", "").replace("]", "")

    prefixes = [
        "sum:",
        "avg:",
        "average:",
        "count:",
        "cnt:",
        "countd:",
        "min:",
        "max:",
        "none:",
        "yr:",
        "qtr:",
        "mn:",
        "wk:",
        "day:",
    ]

    for p in prefixes:
        s = s.replace(p, "")

    s = re.sub(
        r"\.(csv|xlsx|xls|txt|json)$",
        "",
        s,
        flags=re.IGNORECASE
    )

    s = s.replace(":qk", "")
    s = s.replace(":nk", "")
    s = s.replace(":ok", "")

    return s.strip()


def clean_field_name(field_name):

    if not field_name:
        return None

    s = str(field_name)

    s = s.replace("[", "").replace("]", "").strip()

    if not s:
        return None

    parts = s.split(":")

    tableau_prefixes = {
        "sum",
        "avg",
        "average",
        "count",
        "cnt",
        "countd",
        "min",
        "max",
        "median",
        "stdev",
        "var",
        "none",
        "yr",
        "qtr",
        "mn",
        "wk",
        "day",
        "usr",
        "tmn",
        "pcto",
    }

    if len(parts) >= 2:

        if parts[0].lower() in tableau_prefixes:

            return parts[-2].strip()

    return parts[0].strip()


# =========================================================
# AGGREGATION
# =========================================================

AGGREGATION_MAP = {

    "sum": 0,
    "avg": 1,
    "average": 1,
    "count": 2,
    "cnt": 2,
    "countd": 3,
    "min": 4,
    "max": 5,
}


def map_aggregation(derivation):

    if not derivation:
        return 0

    key = str(derivation).lower()
    if key in {"", "none", "null"}:
        return 0

    code = AGGREGATION_MAP.get(key, 0)
    return 0 if code is None else code


def agg_name(code):

    mapping = {
        0: "Sum",
        1: "Avg",
        2: "Count",
        3: "DistinctCount",
        4: "Min",
        5: "Max",
    }

    return mapping.get(code, "Sum")


# =========================================================
# FIELD TYPE CHECK
# =========================================================

def is_measure_field(field):

    if not isinstance(field, dict):
        return False

    derivation = str(
        field.get("derivation", "")
    ).lower()

    if derivation in AGGREGATION_MAP:
        return True

    if derivation in {"user", "none"}:
        return bool(
            parse_tableau_calc_formula(
                field.get("formula")
                or field.get("name_calc")
                or field.get("name")
                or ""
            )
        )

    return False


# =========================================================
# ENTITY EXTRACTION
# =========================================================

def get_entity(field):

    if not isinstance(field, dict):
        return "Table1"

    entity = (
        field.get("parent-name")
        or field.get("table")
        or "Table1"
    )

    return clean_tableau_name(entity)


# =========================================================
# FIELD EXTRACTION
# =========================================================

def extract_field(field):

    if not isinstance(field, dict):
        return None

    raw_col = (
        field.get("column")
        or field.get("local-name")
        or field.get("field")
        or field.get("fieldName")
        or field.get("caption")
        or field.get("name")
    )

    if not raw_col:
        return None

    prop = clean_field_name(raw_col)

    if (
        not prop
        or prop.strip() == ""
        or "measure names" in prop.lower()
        or "measure values" in prop.lower()
    ):
        return None

    derivation = field.get("derivation")

    if str(derivation).lower() in {"user", "none"}:
        formula_info = parse_tableau_calc_formula(
            field.get("formula")
            or field.get("name_calc")
            or field.get("name")
            or ""
        )
        if formula_info:
            derivation = formula_info["Derivation"]
            prop = formula_info.get("Property", prop)

    return {
        "Entity": get_entity(field),
        "Property": prop,
        "Derivation": derivation,
        "LocalType": str(
            field.get("local-type", "")
        ).lower(),
    }


# =========================================================
# DATE HIERARCHY SUPPORT
# =========================================================

def build_dimension_projection(mapped_col):

    deriv = str(
        mapped_col.get("Derivation", "")
    ).lower()

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

    agg_code = map_aggregation(
        mapped_col.get("Derivation")
    )
    if agg_code is None:
        agg_code = 0

    agg_str = agg_name(agg_code)

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
# FILTER BUILDER
# =========================================================

def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


# =========================================================
# MAIN TABLE CONVERTER
# =========================================================

def convert_tableau_to_powerbi_table(tableau_json):

    worksheets = tableau_json.get(
        "worksheets",
        [tableau_json]
    )

    if not isinstance(worksheets, list):
        worksheets = [worksheets]

    ws = worksheets[0]
    workbook = tableau_json.get("workbook") or tableau_json

    rows = [
        enrich_field_from_workbook(f, workbook)
        for f in expand_axis_fields(ws.get("rows", []))
    ]
    cols = [
        enrich_field_from_workbook(f, workbook)
        for f in expand_axis_fields(ws.get("cols", []))
    ]
    encodings = ws.get("encodings", {})

    def find_entity_by_property(property_name):
        if not property_name:
            return None

        candidates = list(rows + cols)
        for val in encodings.values():
            if isinstance(val, list):
                candidates.extend(val)
            elif isinstance(val, dict):
                candidates.append(val)

        default_entity = None
        for candidate in candidates:
            extracted = extract_field(candidate)
            if not extracted:
                continue

            if extracted["Entity"] != "Table1" and default_entity is None:
                default_entity = extracted["Entity"]

            if (
                extracted["Property"] == property_name
                and extracted["Entity"] != "Table1"
            ):
                return extracted["Entity"]

        return default_entity

    def normalize_extracted_field(raw_field):
        extracted = extract_field(raw_field)
        if not extracted:
            return None

        if extracted["Entity"] == "Table1":
            inferred = find_entity_by_property(extracted["Property"])
            if inferred:
                extracted["Entity"] = inferred

        return extracted

    # =====================================================
    # DYNAMIC FIELD COLLECTION
    # =====================================================

    all_fields = []

    all_fields.extend(rows)
    all_fields.extend(cols)

    for val in encodings.values():

        if isinstance(val, list):
            all_fields.extend(val)

        elif isinstance(val, dict):
            all_fields.append(val)

    # =====================================================
    # SEPARATE DIMENSIONS + MEASURES
    # =====================================================

    row_dimensions = []
    column_dimensions = []
    measure_fields = []

    # ROWS

    for fld in rows:

        if not isinstance(fld, dict):
            continue

        fld = recover_partial_tableau_field(fld) or fld
        extracted = normalize_extracted_field(fld)

        if not extracted:
            continue

        if is_measure_names_placeholder_field(fld):
            continue
        if is_measure_like_table_field(fld) or is_measure_field(fld):
            continue

        if extracted not in row_dimensions:
            row_dimensions.append(extracted)

    # COLUMNS

    for fld in cols:

        if not isinstance(fld, dict):
            continue

        fld = recover_partial_tableau_field(fld) or fld
        extracted = normalize_extracted_field(fld)

        if not extracted:
            continue

        if is_measure_names_placeholder_field(fld):
            continue
        if is_measure_like_table_field(fld) or is_measure_field(fld):
            continue

        if extracted not in column_dimensions:
            column_dimensions.append(extracted)

    # =====================================================
    # VALIDATION
    # =====================================================

    if not row_dimensions and not column_dimensions:
        raise ValueError(
            "No valid dimension field found."
        )

    collected_measures = collect_table_measure_fields(ws, workbook)
    measure_projections = [proj for _, proj in collected_measures]

    if not measure_projections:
        fallback_dim = row_dimensions[0] if row_dimensions else (
            column_dimensions[0] if column_dimensions else None
        )
        if fallback_dim:
            measure_projections = [build_measure_projection(fallback_dim)]
        else:
            raise ValueError(
                "No valid measure field found."
            )

    # =====================================================
    # BUILD PROJECTIONS
    # =====================================================

    row_projections = [

        build_dimension_projection(dim)

        for dim in row_dimensions
    ]

    column_projections = [

        build_dimension_projection(dim)

        for dim in column_dimensions
    ]

    # =====================================================
    # DETECT TABLE VS MATRIX
    # =====================================================

    is_matrix = len(column_projections) > 0

    visual_type = (
        "pivotTable"
        if is_matrix
        else "tableEx"
    )

    # =====================================================
    # QUERY STATE
    # =====================================================

    if is_matrix:

        query_state = {

            "Rows": {
                "projections": row_projections
            },

            "Columns": {
                "projections": column_projections
            },

            "Values": {
                "projections": measure_projections
            },
        }

    else:

        query_state = {

            "Values": {
                "projections":
                    row_projections
                    + measure_projections
            }
        }

    # =====================================================
    # FILTERS
    # =====================================================

    filters = []

    all_projections = (
        row_projections
        + column_projections
        + measure_projections
    )

    for proj in all_projections:

        filter_type = (
            "Advanced"
            if "Aggregation" in proj["field"]
            else "Categorical"
        )

        filters.append(
            build_filter(proj, filter_type)
        )

    # =====================================================
    # FINAL POWER BI JSON
    # =====================================================

    powerbi_json = {

        "$schema":
        "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x": random.uniform(20, 80),
            "y": random.uniform(20, 80),
            "z": 0,
            "height": 500,
            "width": 700,
        },

        "visual": {

            "visualType": visual_type,

            "query": {

                "queryState": query_state
            },

            "drillFilterOtherVisuals": True,
        },

        "filterConfig": {
            "filters": filters
        },
    }

    return powerbi_json
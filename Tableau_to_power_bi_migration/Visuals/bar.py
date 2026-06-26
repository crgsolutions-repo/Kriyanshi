import uuid
import random

from utils.tableau_cleaning import (
    clean_tableau_name,
    clean_field_name,
    agg_code_to_str,
    is_valid_field_name,
    map_aggregation,
    parse_tableau_calc_formula,
)

# =====================================================
# HELPERS
# =====================================================
def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }

# =====================================================
# FIELD EXTRACTION
# =====================================================

def extract_field_with_entity(field):

    if not isinstance(field, dict):
        return None

    raw_col = (
        field.get("column")
        or field.get("local-name")
    )

    if not raw_col:
        return None

    property_name = clean_field_name(raw_col)

    if not is_valid_field_name(property_name):
        return None

    entity_name = clean_tableau_name(
        field.get("parent-name")
        or field.get("table")
        or "Table1"
    )

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
            property_name = formula_info.get("Property", property_name)

    return {
        "Property": property_name,
        "Entity": entity_name,
        "Derivation": derivation,
    }


# =====================================================
# CATEGORY PROJECTION
# =====================================================

def build_category_projection(field):

    deriv = str(
        field.get("Derivation", "")
    ).lower()

    DATE_LEVELS = {
        "year": "Year",
        "quarter": "Quarter",
        "month": "Month",
        "day": "Day",
        "week": "Week",
    }

    # ==========================================
    # DATE HIERARCHY
    # ==========================================

    if deriv in DATE_LEVELS:

        level = DATE_LEVELS[deriv]

        return {
            "field": {
                "HierarchyLevel": {
                    "Expression": {
                        "Hierarchy": {
                            "Expression": {
                                "PropertyVariationSource": {
                                    "Expression": {
                                        "SourceRef": {
                                            "Entity": field["Entity"]
                                        }
                                    },
                                    "Name": "Variation",
                                    "Property": field["Property"],
                                }
                            },
                            "Hierarchy": "Date Hierarchy",
                        }
                    },
                    "Level": level,
                }
            },

            "queryRef":
                f"{field['Entity']}."
                f"{field['Property']}."
                f"Variation.Date Hierarchy."
                f"{level}",

            "nativeQueryRef":
                f"{field['Property']} {level}",

            "active": True,
        }

    # ==========================================
    # NORMAL COLUMN
    # ==========================================

    return {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Entity": field["Entity"]
                    }
                },
                "Property": field["Property"],
            }
        },

        "queryRef":
            f"{field['Entity']}.{field['Property']}",

        "nativeQueryRef":
            field["Property"],

        "active": True,
    }

# =====================================================
# MEASURE PROJECTION
# =====================================================

def build_measure_projection(field):

    agg_code = map_aggregation(
        field.get("Derivation")
    )

    agg_name = agg_code_to_str(
        agg_code
    )

    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Entity": field["Entity"]
                            }
                        },
                        "Property": field["Property"],
                    }
                },
                "Function": agg_code,
            }
        },

        "queryRef":
            f"{agg_name}("
            f"{field['Entity']}."
            f"{field['Property']})",

        "nativeQueryRef":
            f"{agg_name} of "
            f"{field['Property']}",
    }


# =====================================================
# SINGLE BAR VISUAL
# =====================================================

def build_bar_chart_for_worksheet(ws):

    rows = ws.get("rows", [])
    cols = ws.get("cols", [])
    encodings = (
    ws.get("encodings")
    or ws.get("table", {}).get("encodings")
    or {}
)

    # =================================================
    # ALL FIELDS
    # =================================================

    all_fields = rows + cols

    def find_entity_for_property(property_name):

        if not property_name:
            return None

        default_entity = None
        for entry in rows + cols:
            extracted = extract_field_with_entity(entry)
            if not extracted:
                continue

            if extracted["Entity"] != "Table1" and default_entity is None:
                default_entity = extracted["Entity"]

            if (
                extracted["Property"] == property_name
                and extracted["Entity"] != "Table1"
            ):
                return extracted["Entity"]

        for entry in encodings.values():
            if isinstance(entry, list):
                for item in entry:
                    if not isinstance(item, dict):
                        continue
                    extracted = extract_field_with_entity(item)
                    if not extracted:
                        continue

                    if extracted["Entity"] != "Table1" and default_entity is None:
                        default_entity = extracted["Entity"]

                    if (
                        extracted["Property"] == property_name
                        and extracted["Entity"] != "Table1"
                    ):
                        return extracted["Entity"]
            elif isinstance(entry, dict):
                extracted = extract_field_with_entity(entry)
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

        extracted = extract_field_with_entity(raw_field)

        if not extracted:
            return None

        if extracted["Entity"] == "Table1":
            inferred = find_entity_for_property(
                extracted["Property"]
            )
            if inferred:
                extracted["Entity"] = inferred

        return extracted

    # =================================================
    # HELPERS
    # =================================================

    def is_measure(field):

        if not isinstance(field, dict):
            return False

        deriv = str(
            field.get("derivation", "")
        ).lower()

        local_type = str(
            field.get("local-type", "")
        ).lower()

        if deriv in {
            "sum",
            "avg",
            "average",
            "count",
            "countd",
            "min",
            "max",
            "median",
        }:
            return True

        if deriv in {"user", "none"}:
            if parse_tableau_calc_formula(
                field.get("formula")
                or field.get("name_calc")
                or field.get("name")
                or ""
            ):
                return True

        if local_type in {
            "real",
            "integer",
            "numeric",
        }:
            return True

        return False

    def get_first_valid_encoding(name):
        enc = encodings.get(name)

        if isinstance(enc, dict):
            return enc

        if isinstance(enc, list):
            for item in enc:
                if isinstance(item, dict):
                    return item

        return None

    # =================================================
    # CATEGORY FIELD
    # =================================================

    category_field = None

    # Prefer dimension from cols
    for fld in cols:

        extracted = normalize_extracted_field(fld)

        if not extracted:
            continue

        if not is_measure(fld):

            category_field = fld
            break

    # fallback -> rows
    if not category_field:

        for fld in rows:

            extracted = normalize_extracted_field(fld)

            if not extracted:
                continue

            if not is_measure(fld):

                category_field = fld
                break

    # =================================================
    # MEASURE FIELD
    # =================================================

    # =================================================
    # EXTRACTION
    # =================================================

    category = normalize_extracted_field(
        category_field
    )

    # =================================================
    # VALIDATION
    # =================================================

    if not category:
        raise ValueError(
            "Bar category field not found."
        )
    
    measure_fields = []

    all_measure_sources = (
    rows+ cols)

    for enc in encodings.values():

        if isinstance(enc, list):
            all_measure_sources.extend(enc)

        elif isinstance(enc, dict):
            all_measure_sources.append(enc)

    for fld in all_measure_sources:

        if is_measure(fld):

            extracted = normalize_extracted_field(fld)

            if extracted:

                key = (
                    extracted["Entity"],
                    extracted["Property"]
                )

                if key not in [
                    (
                        m["Entity"],
                        m["Property"]
                    )
                    for m in measure_fields
                ]:
                    measure_fields.append(extracted)
    # OUTSIDE LOOP
    if not measure_fields:
        # Fallback: if category exists, create a Count on that category
        if category:
            measure_fields.append({
                "Property": category["Property"],
                "Entity": category["Entity"],
                "Derivation": "Count",
            })
        else:
            raise ValueError("Bar measure field not found.")
    # =================================================
    # SERIES DETECTION (explicit color OR fallback second dimension)
    # =================================================

    series = None
    series_is_explicit_color = False

    possible_series = get_first_valid_encoding("color")

    if isinstance(possible_series, dict):
        extracted = normalize_extracted_field(possible_series)

        if extracted and not is_measure(possible_series):
            # For explicit color encodings, use as series (even if same as category)
            # This creates a legend with different colors
            series = extracted
            series_is_explicit_color = True

    if not series:
        # Fallback: if no explicit legend color, use a second dimension as Series
        dimension_candidates = []
        for fld in cols + rows:
            if not isinstance(fld, dict):
                continue
            if is_measure(fld):
                continue
            extracted = normalize_extracted_field(fld)
            if not extracted:
                continue
            if (
                extracted["Property"] == category["Property"]
                and extracted["Entity"] == category["Entity"]
            ):
                continue
            if extracted not in dimension_candidates:
                dimension_candidates.append(extracted)

        if dimension_candidates:
            series = dimension_candidates[0]
    # =================================================
    # PROJECTIONS
    # =================================================

    category_projection = (
        build_category_projection(category)
    )

    measure_projection = [
        build_measure_projection(m)
        for m in measure_fields
    ]

    # =================================================
    # QUERY STATE
    # =================================================

    query_state = {

        "Category": {
            "projections": [
                category_projection
            ]
        },

        "Y": {
    "projections": measure_projection},
    }

    # =================================================
    # FILTERS
    # =================================================

    filters = [

    build_filter(
        category_projection,
        "Categorical"
    ),

    *[
        build_filter(
            m,
            "Advanced"
        )

        for m in measure_projection
    ],
]

# =================================================
# Inject Series into query_state only when valid
# and add its filter. Also choose visual type accordingly
# =================================================

    if series:
        series_projection = build_category_projection(series)
        query_state["Series"] = {"projections": [series_projection]}
        filters.append(build_filter(series_projection, "Categorical"))

    visual_type = (
        "columnChart"
        if series and series_is_explicit_color
        else "clusteredColumnChart"
    )

    # =================================================
    # FINAL JSON
    # =================================================

    return {

        "$schema":
            "https://developer.microsoft.com/"
            "json-schemas/fabric/item/report/"
            "definition/visualContainer/2.5.0/schema.json",

        "name":
            uuid.uuid4().hex[:20],

        "position": {
            "x": 599, # random.uniform(50, 120),
            "y": 0, # random.uniform(50, 120),
            "z": 0,
            "height": 304,
            "width": 680,
        },

        "visual": {

            "visualType":
                visual_type,

            "query": {

                "queryState":
                    query_state,

                "sortDefinition": {

                    "sort": [
                        {
                            "field":
                                measure_projection[0]["field"],

                            "direction":
                                "Descending",
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


# =====================================================
# MAIN ENTRY
# =====================================================

def convert_bar_chart_dynamic(tableau_json):

    worksheets = tableau_json.get(
        "worksheets",
        [tableau_json]
    )

    visuals = []

    for ws in worksheets:

        marks = [
            str(m).lower()
            for m in ws.get("marks", [])
        ]

        if "bar" in marks:

            try:

                visuals.append(
                    build_bar_chart_for_worksheet(ws)
                )

            except Exception as e:

                print(
                    f"Bar conversion failed for "
                    f"{ws.get('worksheet')}: {e}"
                )
 
    return visuals


# =====================================================
# BACKWARD COMPATIBILITY
# =====================================================

convert_tableau_bar_to_powerbi = (
    convert_bar_chart_dynamic
)

import sys
import os
import uuid
import random

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    clean_tableau_name,
    clean_field_name,
    AGGREGATION_MAP,
)

# =========================================================
# HELPERS
# =========================================================

def map_derivation_to_agg_func(derivation: str):

    if not derivation:
        return AGGREGATION_MAP.get("SUM", 0)

    deriv = derivation.upper()

    return AGGREGATION_MAP.get(deriv, 0)


def build_filter(field_projection, filter_type):

    return {
        "name": uuid.uuid4().hex[:20],
        "field": field_projection["field"],
        "type": filter_type,
    }


def get_entity(field, worksheet):

    entity = (
        field.get("parent-name")
        or worksheet.get("datasource")
        or worksheet.get("table")
        or "Table"
    )

    return clean_tableau_name(entity)


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
# DATE HIERARCHY
# =========================================================

DATE_HIERARCHY_LEVELS = {
    "year": "Year",
    "quarter": "Quarter",
    "month": "Month",
    "day": "Day",
    "week": "Week",
}


def make_hierarchy_projection(entity, prop, level):

    return {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {
                                    "SourceRef": {
                                        "Entity": clean_tableau_name(entity)
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
        "queryRef": f"{entity}.{prop}.Variation.Date Hierarchy.{level}",
        "nativeQueryRef": f"{prop} {level}",
        "active": True,
    }


# =========================================================
# COLUMN PROJECTION
# =========================================================

def make_column_projection(entity, prop):

    return {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {
                        "Entity": clean_tableau_name(entity)
                    }
                },
                "Property": prop,
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
        "active": True,
    }


# =========================================================
# MEASURE PROJECTION
# =========================================================

def make_aggregation_projection(entity, prop, agg_func_code, agg_name):

    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Entity": clean_tableau_name(entity)
                            }
                        },
                        "Property": prop,
                    }
                },
                "Function": agg_func_code,
            }
        },
        "queryRef": f"{agg_name}({entity}.{prop})",
        "nativeQueryRef": f"{agg_name} of {prop}",
    }


# =========================================================
# MAIN CONVERTER
# =========================================================

def convert_area_chart(tableau_json):

    worksheets = tableau_json.get("worksheets", [])

    if not worksheets:
        raise ValueError("No worksheets found")

    worksheet = worksheets[0]

    rows = worksheet.get("rows", [])
    cols = worksheet.get("cols", [])
    encodings = worksheet.get("encodings", {})

    if not rows:
        raise ValueError("No rows found")

    if not cols:
        raise ValueError("No columns found")

    # =====================================================
    # DYNAMIC FIELD DETECTION
    # =====================================================

    measure_fields = [
        f for f in rows
        if is_measure(f)
    ]

    category_fields = [
        f for f in cols
    ]

    # =====================================================
    # CATEGORY
    # =====================================================

    category_projections = []
    category_filters = []

    for col in category_fields:

        col_name = clean_field_name(
            col.get("column")
        )

        entity = get_entity(
            col,
            worksheet
        )

        derivation = str(
            col.get("derivation", "")
        ).lower()

        datatype = str(
            col.get("datatype", "")
        ).lower()

        matched_level = DATE_HIERARCHY_LEVELS.get(
            derivation
        )

        # DATE HIERARCHY ONLY FOR DATE FIELDS
        if matched_level and datatype == "date":

            projection = make_hierarchy_projection(
                entity,
                col_name,
                matched_level
            )

        else:

            projection = make_column_projection(
                entity,
                col_name
            )

        category_projections.append(projection)

        category_filters.append(
            build_filter(
                projection,
                "Categorical"
            )
        )

    # =====================================================
    # SERIES
    # =====================================================

    series_projections = []
    series_filters = []

    color_encoding = encodings.get("color")

    if color_encoding:

        series_entity = get_entity(
            color_encoding,
            worksheet
        )

        series_property = clean_field_name(
            color_encoding.get("column")
        )

        if series_property:

            series_projection = make_column_projection(
                series_entity,
                series_property
            )

            series_projections.append(
                series_projection
            )

            series_filters.append(
                build_filter(
                    series_projection,
                    "Categorical"
                )
            )

    # =====================================================
    # Y AXIS / MEASURES
    # =====================================================

    y_projections = []
    measure_filters = []

    for measure in measure_fields:

        prop = clean_field_name(
            measure.get("column")
        )

        derivation = measure.get("derivation")

        entity = get_entity(
            measure,
            worksheet
        )

        agg_func_code = map_derivation_to_agg_func(
            derivation
        )

        agg_name = (
            derivation.capitalize()
            if derivation
            else "Sum"
        )

        if agg_name == "Avg":
            agg_name = "Average"

        projection = make_aggregation_projection(
            entity,
            prop,
            agg_func_code,
            agg_name
        )

        y_projections.append(projection)

        measure_filters.append(
            build_filter(
                projection,
                "Advanced"
            )
        )

    # =====================================================
    # FINAL JSON
    # =====================================================

    powerbi_json = {

        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.5.0/schema.json",

        "name": uuid.uuid4().hex[:20],

        "position": {
            "x":842, # random.uniform(50, 120),
            "y":330, # random.uniform(50, 120),
            "z": 1,
            "height": 389,
            "width": 436,
        },

        "visual": {

            "visualType": "areaChart",

            "query": {

                "queryState": {

                    "Category": {
                        "projections": category_projections
                    },

                    "Y": {
                        "projections": y_projections
                    },
                }
            },

            "drillFilterOtherVisuals": True,
        },

        "filterConfig": {
            "filters": (
                category_filters
                + measure_filters
                + series_filters
            )
        },
    }

    # =====================================================
    # SERIES ADD
    # =====================================================

    if series_projections:

        powerbi_json["visual"]["query"]["queryState"]["Series"] = {
            "projections": series_projections
        }

    return powerbi_json
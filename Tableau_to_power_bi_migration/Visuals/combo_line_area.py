import sys
import os
import re
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    clean_tableau_name,
    get_aggregation_map,
    generate_position,
)

# To be updated for multitable compatablity, Issue: Parser ISSUE
# Mapping of recognized aggregation names to Power BI function codes
AGGREGATION_MAP = get_aggregation_map()


def normalise_agg(agg: str) -> str:
    synonyms = {"CNT": "COUNT", "AVERAGE": "AVG"}
    agg = agg.upper()
    return synonyms.get(agg, agg)


def extract_bracketed_expressions(text):
    import re

    return re.findall(r"\[(.*?)\]", text)


def clean_tableau_field_name(name: str) -> str:
    """Removes internal Tableau suffixes like ':qk' from field names."""
    # Use cleaning utility if possible, fallback to current logic
    cleaned_name = clean_tableau_name(name)
    # Additional suffix removal logic as in original
    if ":" in cleaned_name:
        base, suffix = cleaned_name.rsplit(":", 1)
        # Remove known Tableau suffixes like :qk, :ok, :nk, etc.
        if len(suffix) <= 3 and suffix.isalpha():
            return base
    return cleaned_name


def infer_entity_and_property(expression, default_entity=None):
    """Strictly extracts aggregation, entity, and property from a Tableau-style expression."""
    agg_names_pattern = "|".join(
        re.escape(agg.lower()) for agg in AGGREGATION_MAP.keys()
    )
    expression_stripped = expression.strip().strip("[]")
    pattern = re.compile(
        rf"^({agg_names_pattern}):(?:([A-Za-z0-9\_]+)\.)?([A-Za-z0-9_\:\. ]+)$",
        re.IGNORECASE,
    )
    m = pattern.match(expression_stripped)
    if m:
        agg_func, entity, prop = m.groups()
        agg_func = normalise_agg(agg_func)
        entity = entity if entity else default_entity or "UnknownEntity"
        prop = clean_tableau_field_name(prop)
        return agg_func, entity, prop
    m = re.match(r"^(?:([A-Za-z0-9\_]+)\.)?([A-Za-z0-9_\:\. ]+)$", expression_stripped)
    if m:
        entity, prop = m.groups()
        entity = entity if entity else default_entity or "UnknownEntity"
        prop = clean_tableau_field_name(prop)
        return "SUM", entity, prop
    return (
        "SUM",
        default_entity or "UnknownEntity",
        clean_tableau_field_name(expression_stripped),
    )


def extract_default_entity(tableau_json):
    """Attempts to extract a worksheet- or datasource-level entity/table name."""
    worksheets = tableau_json.get("worksheets", [])
    if worksheets:
        ws = worksheets[0]
        ds = ws.get("datasource") or ws.get("table")
        if ds:
            return ds
    ds = tableau_json.get("datasource") or tableau_json.get("table")
    if ds:
        return ds
    return None


def make_projection(measure):
    agg_func_code = AGGREGATION_MAP.get(measure["agg"], 0)
    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": measure["entity"]}},
                        "Property": measure["property"],
                    }
                },
                "Function": agg_func_code,
            }
        },
        "queryRef": f"{measure['agg']}({measure['entity']}.{measure['property']})",
        "nativeQueryRef": f"{measure['agg']} of {measure['property']}",
    }


def make_hierarchy_projection(entity, prop, hierarchy_name, level):
    return {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {"SourceRef": {"Entity": entity}},
                                "Name": "Variation",
                                "Property": prop,
                            }
                        },
                        "Hierarchy": hierarchy_name,
                    }
                },
                "Level": level,
            }
        },
        "queryRef": f"{entity}.{prop}.Variation.{hierarchy_name}.{level}",
        "nativeQueryRef": f"{prop} {level}",
        "active": True,
    }


def convert_tableau_to_powerbi_CCLA(
    tableau_json, position=None, name=None, default_entity=None, entity_map=None
):
    """Convert Tableau worksheet JSON to Power BI chart definition, properly resolving hierarchy names for date fields."""

    # Helper function to detect if column looks like a date column
    def is_date_column(column_name):
        date_indicators = [
            "date",
            "datetime",
            "ship date",
            "order date",
            "delivery date",
            "created date",
        ]
        # lowercase and strip for matching
        col_lower = column_name.lower().strip()
        return any(ind in col_lower for ind in date_indicators)

    worksheets = tableau_json.get("worksheets", [])
    if not worksheets or not worksheets[0]:
        raise ValueError("No worksheets found in Tableau JSON")
    worksheet = worksheets[0]
    if not default_entity:
        default_entity = extract_default_entity(tableau_json) or "Orders"
    rows = worksheet.get("rows", [])
    if not rows:
        raise ValueError("No rows found in Tableau worksheet")

    measures = []
    agg_names_pattern = "|".join(agg.lower() for agg in AGGREGATION_MAP.keys())
    for row in rows:
        row_name = row.get("name", "")
        bracketed_exprs = extract_bracketed_expressions(row_name)
        for expr in bracketed_exprs:
            if "." in expr:
                _, right = expr.split(".", 1)
                expr_to_try = right.strip()
            else:
                expr_to_try = expr.strip()
            m = re.match(rf"({agg_names_pattern}):(.*)", expr_to_try, re.IGNORECASE)
            if m:
                agg, field = m.groups()
                field = field.strip()
                used_entity = (entity_map or {}).get(field) or default_entity
                agg, entity, prop = infer_entity_and_property(
                    f"{agg}:{field}", default_entity=used_entity
                )
                measures.append({"agg": agg, "entity": entity, "property": prop})

    if not measures:
        raise ValueError("No measures found in any row expressions.")

    cols = worksheet.get("cols", [])
    if not cols:
        raise ValueError("No columns found in Tableau worksheet")

    category_col = cols[0]

    # Extract category column info
    col_expr = category_col.get("column", "")
    col_field = col_expr.replace("[", "").replace("]", "")
    cat_entity = (entity_map or {}).get(col_field) or default_entity

    derivation = category_col.get("derivation")
    # Determine hierarchy_name based on column name if it is a date-like column
    raw_column_name = category_col.get("local-name") or col_field

    if is_date_column(raw_column_name):
        hierarchy_name = "Date Hierarchy"
    else:
        # Fallback to default or no hierarchy
        # For example, you can keep the old parent-name-based hierarchy or leave None
        parent_name = category_col.get("parent-name")
        if parent_name:
            hierarchy_name = f"{parent_name}Hierarchy"
        else:
            hierarchy_name = None

    hierarchy_level = derivation if derivation else None

    _, entity, col_property = infer_entity_and_property(
        col_expr, default_entity=cat_entity
    )

    position = position or {
        "x": 217.91,
        "y": 109.75,
        "z": 0,
        "height": 530.0,
        "width": 843.0,
    }

    # Category projection: use hierarchy if detected, else simple column projection
    if hierarchy_name and hierarchy_level:
        cat_projection = make_hierarchy_projection(
            entity, col_property, hierarchy_name, hierarchy_level
        )
    else:
        cat_projection = {
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": entity}},
                    "Property": col_property,
                }
            },
            "queryRef": f"{entity}.{col_property}",
            "nativeQueryRef": f"{col_property}",
            "active": True,
        }

    # Y and Y2 projections
    n = len(measures)
    y_projections = [make_projection(measures[0])]
    y2_projections = [make_projection(measures[1])] if n > 1 else []

    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": name or "DynamicChart",
        "position": position,
        "visual": {
            "visualType": "lineChart",
            "query": {
                "queryState": {
                    "Category": {"projections": [cat_projection]},
                    "Y": {"projections": y_projections},
                },
                "sortDefinition": {
                    "sort": [
                        {
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": entity}},
                                    "Property": col_property,
                                }
                            },
                            "direction": "Descending",
                        }
                    ]
                },
            },
            "objects": {
                "lineStyles": [
                    {
                        "properties": {
                            "areaShow": {"expr": {"Literal": {"Value": "true"}}}
                        }
                    },
                    {
                        "properties": {
                            "areaShow": {"expr": {"Literal": {"Value": "false"}}}
                        },
                        "selector": {
                            "metadata": (
                                f"{measures[1]['agg']}({measures[1]['entity']}.{measures[1]['property']})"
                                if n > 1
                                else ""
                            )
                        },
                    },
                ],
                "labels": [
                    {
                        "properties": {
                            "show": {"expr": {"Literal": {"Value": "true"}}},
                            "bold": {"expr": {"Literal": {"Value": "true"}}},
                            "fontFamily": {
                                "expr": {"Literal": {"Value": "'''Times New Roman'''"}}
                            },
                            "color": {
                                "solid": {
                                    "color": {
                                        "expr": {
                                            "ThemeDataColor": {
                                                "ColorId": 1,
                                                "Percent": 0,
                                            }
                                        }
                                    }
                                }
                            },
                            "fontSize": {"expr": {"Literal": {"Value": "10D"}}},
                        }
                    }
                ],
            },
            "drillFilterOtherVisuals": True,
        },
    }

    if y2_projections:
        powerbi_json["visual"]["query"]["queryState"]["Y2"] = {
            "projections": y2_projections
        }

    return powerbi_json

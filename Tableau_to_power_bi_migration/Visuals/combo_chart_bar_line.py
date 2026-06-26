import re
import sys
import os
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import AGGREGATION_MAP, clean_field_name, map_aggregation


# To be updated for multitable compatablity, Issue: Parser ISSUE
def strip_guid_suffix(name):
    return re.sub(r"\_[A-F0-9]{10,}$", "", name) if name else name


def extract_bracketed_expressions(text):
    """Extract content inside square brackets [ ... ] from a string."""
    return re.findall(r"\[(.*?)\]", text)


def normalise_agg(agg: str) -> str:
    """Normalize aggregator synonyms (CNT -> COUNT, AVERAGE -> AVG, etc.)."""
    synonyms = {"CNT": "COUNT", "AVERAGE": "AVG"}
    agg = agg.upper()
    return synonyms.get(agg, agg)


def infer_entity_and_property(expression, default_entity=None):
    """
    Extract aggregation, entity, and property from Tableau-style expression.
    Cleans Tableau internal field suffixes like ':qk'.
    """
    agg_names_pattern = "|".join(
        re.escape(agg.lower()) for agg in AGGREGATION_MAP.keys()
    )
    expression_stripped = expression.strip().strip("[]")

    pattern = re.compile(
        rf"^({agg_names_pattern}):(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_:.\s]+)$",
        re.IGNORECASE,
    )
    m = pattern.match(expression_stripped)
    if m:
        agg_func, entity, prop = m.groups()
        agg_func = normalise_agg(agg_func)
        entity = entity if entity else default_entity or "UnknownEntity"
        prop = clean_field_name(prop)
        return agg_func, entity, prop
    # Fallback: Entity.Property without agg
    m = re.match(r"^(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_:.\s]+)$", expression_stripped)
    if m:
        entity, prop = m.groups()
        entity = entity if entity else default_entity or "UnknownEntity"
        prop = clean_field_name(prop)
        return "SUM", entity, prop
    return (
        "SUM",
        default_entity or "UnknownEntity",
        clean_field_name(expression_stripped),
    )


def extract_default_entity(tableau_json):
    """Extract default entity/table name from Tableau JSON metadata."""
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


def has_hierarchy(category_col):
    """
    Check if the given category column metadata indicates hierarchy presence,
    based on 'derivation' field's value.
    """
    derivation = category_col.get("derivation", "").lower()
    return derivation != "none" and derivation != ""


def convert_tableau_to_powerbi_CC(
    tableau_json, position=None, name=None, default_entity=None, entity_map=None
):
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

    # Extract measures from row names
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

    col_expr = category_col.get("column", "")
    col_derivation = category_col.get("derivation", "")
    col_field = col_expr.replace("[", "").replace("]", "")
    cat_entity = (entity_map or {}).get(col_field) or default_entity
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

    def make_projection(measure):
        agg_func_code = map_aggregation(measure["agg"], 0)
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

    n = len(measures)
    if n == 1:
        y_projections = [make_projection(measures[0])]
        y2_projections = []
    elif n == 2:
        y_projections = [make_projection(measures[0])]
        y2_projections = [make_projection(measures[1])]
    elif n > 2:
        half = n // 2
        y_projections = [make_projection(m) for m in measures[:half]]
        y2_projections = [make_projection(m) for m in measures[half:]]
    else:
        y_projections = []
        y2_projections = []

    if has_hierarchy(category_col):
        cat_projection = {
            "field": {
                "HierarchyLevel": {
                    "Expression": {
                        "Hierarchy": {
                            "Expression": {
                                "PropertyVariationSource": {
                                    "Expression": {"SourceRef": {"Entity": entity}},
                                    "Name": "Variation",
                                    "Property": col_property,
                                }
                            },
                            "Hierarchy": category_col.get(
                                "hierarchy", "Date Hierarchy"
                            ),
                        }
                    },
                    "Level": col_derivation,
                }
            },
            "queryRef": f"{entity}.{col_property}.{category_col.get('hierarchy', 'Default Hierarchy')}.{category_col.get('level', '')}",
            "nativeQueryRef": col_property,
            "active": True,
        }
    else:
        cat_projection = {
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": entity}},
                    "Property": col_property,
                }
            },
            "queryRef": f"{entity}.{col_property}",
            "nativeQueryRef": col_property,
            "active": True,
        }

    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": position,
        "visual": {
            "visualType": "lineStackedColumnComboChart",
            "query": {
                "queryState": {
                    "Category": {"projections": [cat_projection]},
                    "Y": {"projections": y_projections},
                },
                "sortDefinition": {
                    "sort": [
                        {"field": cat_projection["field"], "direction": "Ascending"}
                    ],
                    "isDefaultSort": True,
                },
            },
            "drillFilterOtherVisuals": True,
        },
    }

    if y2_projections:
        powerbi_json["visual"]["query"]["queryState"]["Y2"] = {
            "projections": y2_projections
        }

    return powerbi_json

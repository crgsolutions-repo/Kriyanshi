import re
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils.tableau_cleaning import clean_tableau_name, get_aggregation_map

AGGREGATION_MAP = get_aggregation_map()


# To be updated for multitable compatablity, Issue: Parser ISSUE
def clean_tableau_field_name(name: str) -> str:
    # Use existing cleaning utility first
    cleaned = clean_tableau_name(name)
    # Additional Tableau suffix removal as before
    if ":" in cleaned:
        base, suffix = cleaned.rsplit(":", 1)
        if len(suffix) <= 4 and suffix.isalpha():
            return base
    return cleaned


def extract_bracketed_expressions(text):
    return re.findall(r"\[(.*?)\]", text)


def normalise_agg(agg: str) -> str:
    synonyms = {"CNT": "COUNT", "AVERAGE": "AVG"}
    agg = agg.upper()
    return synonyms.get(agg, agg)


def infer_entity_and_property(expression, default_entity=None):
    agg_names_pattern = "|".join(
        re.escape(agg.lower()) for agg in AGGREGATION_MAP.keys()
    )
    expression_stripped = expression.strip().strip("[]")
    pattern = re.compile(
        rf"^({agg_names_pattern}):(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_\:\. ]+)$",
        re.IGNORECASE,
    )
    m = pattern.match(expression_stripped)
    if m:
        agg_func, entity, prop = m.groups()
        agg_func = normalise_agg(agg_func)
        entity = entity if entity else default_entity or "UnknownEntity"
        prop = clean_tableau_field_name(prop)
        return agg_func, entity, prop
    m = re.match(r"^(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_\:\. ]+)$", expression_stripped)
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


def is_valid_field_name(name: str) -> bool:
    """
    Ensures property name is usable (not blank/None).
    Extend with additional rules if needed.
    """
    return bool(name and isinstance(name, str) and name.strip())


# --- Normalization helpers ---
def _normalize(s: str) -> str:
    if not s:
        return ""
    # remove brackets, trim, collapse whitespace, remove non-alphanum
    s = s.replace("[", "").replace("]", "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\W+", "", s)  # keep only alphanumeric
    return s.lower()


def get_entity_for_property(
    property_name: str, current_entity: str, table_columns_map: dict
) -> str:
    """
    Robust lookup: normalize strings and try exact normalized match first,
    then fallback to partial/contains matches.
    """
    if not table_columns_map:
        return current_entity or "UnknownEntity"

    prop_norm = _normalize(property_name)

    # 1) If current_entity already contains the property (normalized) -> keep it
    if current_entity and any(
        _normalize(c) == prop_norm for c in table_columns_map.get(current_entity, [])
    ):
        return current_entity

    # 2) Exact normalized match across all tables
    for table_name, columns in table_columns_map.items():
        for col in columns:
            if _normalize(col) == prop_norm:
                return table_name

    # 3) Fallback: partial match (col contained within property or vice-versa)
    for table_name, columns in table_columns_map.items():
        for col in columns:
            col_norm = _normalize(col)
            if col_norm and (col_norm in prop_norm or prop_norm in col_norm):
                return table_name

    # 4) Nothing matched: return current (or UnknownEntity)
    return current_entity or "UnknownEntity"


# --- Improved extract_field_with_entity (robust) ---
def extract_field_with_entity(field):
    if not isinstance(field, dict):
        return None
    native_name = field.get("Native name", "")
    if isinstance(native_name, str) and native_name.strip().lower() == "calculated":
        return None

    col_name = field.get("column") or field.get("local-name")
    entity_name = field.get("parent-name", "")

    result = {
        "Entity": entity_name,
        "Property": col_name,
    }

    # Preserve derivation if present
    if "derivation" in field:
        result["Derivation"] = field["derivation"]

    return result


# --- Main conversion function (only category/cols logic changed; measures intact) ---
def convert_tableau_to_powerbi_CCBA(
    tableau_json,
    table_columns_map=None,  # optional, default None
    position=None,
    name=None,
    default_entity=None,
    entity_map=None,
    objects=None,
    debug: bool = False,  # set True to print diagnostic info
):
    worksheets = tableau_json.get("worksheets", [])
    if not worksheets or not worksheets[0]:
        raise ValueError("No worksheets found in Tableau JSON")
    worksheet = worksheets[0]
    if not default_entity:
        default_entity = extract_default_entity(tableau_json) or "People"

    rows = worksheet.get("rows", [])
    if not rows:
        raise ValueError("No rows found in Tableau worksheet")

    # Preprocess entity_map: normalize keys to lowercase for consistent lookup
    if entity_map:
        entity_map = {k.lower(): v for k, v in entity_map.items()}

    measures = []
    agg_names_pattern = "|".join(agg.lower() for agg in AGGREGATION_MAP.keys())

    for row in rows:
        row_name = row.get("name", "")
        bracketed_exprs = extract_bracketed_expressions(row_name)
        found_any = False
        for expr in bracketed_exprs:
            if "." in expr:
                _, right = expr.split(".", 1)
                expr_to_try = right.strip()
            else:
                expr_to_try = expr.strip()

            m = re.match(rf"({agg_names_pattern}):(.*)", expr_to_try, re.IGNORECASE)
            if m:
                found_any = True
                agg, field = m.groups()
                field = field.strip()
                field_norm = field.lower()

                used_entity = None
                if entity_map:
                    used_entity = entity_map.get(field_norm)
                if used_entity is None:
                    used_entity = default_entity

                agg, entity, prop = infer_entity_and_property(
                    f"{agg}:{field}", default_entity=used_entity
                )

                if table_columns_map:
                    entity = get_entity_for_property(prop, entity, table_columns_map)

                measures.append({"agg": agg, "entity": entity, "property": prop})
        if not found_any:
            pass

    if not measures:
        raise ValueError("No measures found in any row expressions.")

    cols = worksheet.get("cols", [])
    if not cols:
        raise ValueError("No columns found in Tableau worksheet")
    category_col = cols[0]

    # Use robust extractor
    mapped_col = extract_field_with_entity(category_col)
    if not mapped_col or not mapped_col.get("Property"):
        raise ValueError("Invalid category column in Tableau worksheet")

    # Debug: show raw
    if debug:
        print("DEBUG: raw category_col:", category_col)
        print("DEBUG: extracted mapped_col (before mapping):", mapped_col)

    # Correct entity using table_columns_map (robust)
    if table_columns_map:
        current_entity = mapped_col.get("Entity") or None
        mapped_entity = get_entity_for_property(
            mapped_col["Property"], current_entity, table_columns_map
        )
        mapped_col["Entity"] = mapped_entity

    if debug:
        print("DEBUG: mapped_col (after mapping):", mapped_col)
        # Also show normalized property & normalized mapper keys for quick inspection
        print("DEBUG: normalized property:", _normalize(mapped_col["Property"]))
        print("DEBUG: mapper normalized keys sample:")
        # show up to first 10 normalized mapper keys
        sample = []
        for tname, cols in (table_columns_map or {}).items():
            if len(sample) > 10:
                break
            for c in cols:
                sample.append((tname, c, _normalize(c)))
        print(sample[:10])

    # now build category projection using derivation/hierarchy or normal column
    deriv = mapped_col.get("Derivation")
    if (
        deriv
        and isinstance(deriv, str)
        and deriv.lower() in {"year", "quarter", "month", "day"}
    ):
        # Date hierarchy
        cat_projection = {
            "field": {
                "HierarchyLevel": {
                    "Expression": {
                        "Hierarchy": {
                            "Expression": {
                                "PropertyVariationSource": {
                                    "Expression": {
                                        "SourceRef": {"Entity": mapped_col["Entity"]}
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
        sort_field_entity = mapped_col["Entity"]
        sort_field_property = mapped_col["Property"]
    else:
        # Normal column
        cat_projection = {
            "field": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": mapped_col["Entity"]}},
                    "Property": mapped_col["Property"],
                }
            },
            "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}",
            "nativeQueryRef": mapped_col["Property"],
            "active": True,
        }
        sort_field_entity = mapped_col["Entity"]
        sort_field_property = mapped_col["Property"]

    sort_definition = {
        "sort": [
            {
                "field": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": sort_field_entity}},
                        "Property": sort_field_property,
                    }
                },
                "direction": "Descending",
            }
        ],
    }

    # position default
    position = position or {
        "x": 217.91,
        "y": 109.75,
        "z": 0,
        "height": 530.0,
        "width": 843.0,
    }

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

    default_objects = {
        "lineStyles": [
            {
                "properties": {
                    "strokeTransparency": {"expr": {"Literal": {"Value": "20D"}}},
                    "areaShow": {"expr": {"Literal": {"Value": "true"}}},
                }
            }
        ],
        "labels": [{"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}],
    }

    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": position,
        "visual": {
            "visualType": "lineClusteredColumnComboChart",
            "query": {
                "queryState": {
                    "Category": {"projections": [cat_projection]},
                    "Y": {"projections": y_projections},
                },
                "sortDefinition": sort_definition,
            },
            "objects": objects if objects else default_objects,
            "drillFilterOtherVisuals": True,
        },
    }

    if y2_projections:
        powerbi_json["visual"]["query"]["queryState"]["Y2"] = {
            "projections": y2_projections
        }

    return powerbi_json

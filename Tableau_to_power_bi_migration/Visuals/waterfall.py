import re
import sys
import os
import uuid


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import AGGREGATION_MAP, map_aggregation


def clean_tableau_field_name(name: str) -> str:
    """
    Remove short Tableau suffix tokens like ':qk', ':ok' etc if present.
    """
    if not name or not isinstance(name, str):
        return name
    if ":" in name:
        base, suffix = name.rsplit(":", 1)
        if len(suffix) <= 4 and suffix.isalpha():
            return base
    return name


def extract_base_property(prop: str) -> str:
    """
    Return a simple identifier from the end of prop.
    Example: 'table.col' -> 'col', 'User(Profit)' -> 'Profit' (if already cleaned).
    """
    if not prop or not isinstance(prop, str):
        return None
    last_seg = prop.split(".")[-1]
    m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)$", last_seg)
    if m:
        return m.group(1)
    return None


def normalise_agg(agg: str) -> str:
    synonyms = {"CNT": "COUNT", "AVERAGE": "AVG", "RUNNING_TOTAL": "SUM", "CUMM": "SUM"}
    if not agg or not isinstance(agg, str):
        return agg
    agg = agg.upper()
    return synonyms.get(agg, agg)


def map_aggregation(func_name, default=0):
    if not func_name or not isinstance(func_name, str):
        return default
    mapping = {"sum": 0, "avg": 1, "average": 1, "count": 2, "min": 3, "max": 4}
    return mapping.get(func_name.lower(), default)


def is_valid_field_name(name: str):
    """
    Basic checks to skip obviously invalid names.
    """
    return (
        bool(name)
        and isinstance(name, str)
        and name.strip() != ""
        and name.lower() not in {"none", "color", "text", ""}
    )


def extract_field_with_entity(field):
    """
    Normalize and extract column/entity/derivation from a tableau-style field descriptor.
    """
    if not isinstance(field, dict):
        return {"Property": None, "Entity": None, "Derivation": None}

    col_name = field.get("column")
    if isinstance(col_name, str):
        col_name = clean_tableau_field_name(col_name)
    # prefer explicit entity keys that Tableau may use
    entity_name = (
        field.get("entity")
        or field.get("parent-name")
        or field.get("table")
        or field.get("datasource")
    )
    derivation = field.get("derivation", None)
    return {"Property": col_name, "Entity": entity_name, "Derivation": derivation}


def map_worksheet_fields(worksheet):
    """
    Map categories, measures, series from a worksheet description.
    """
    result = {"categories": [], "measures": [], "series": None}
    for col in worksheet.get("cols", []):
        result["categories"].append(extract_field_with_entity(col))
    for row in worksheet.get("rows", []):
        result["measures"].append(extract_field_with_entity(row))
    color_enc = worksheet.get("encodings", {}).get("color")
    if color_enc:
        result["series"] = extract_field_with_entity(color_enc)
    return result


def extract_default_entity(tableau_json):
    """
    Attempt to find a sensible default entity/datasource/table name in the JSON.
    """
    worksheets = tableau_json.get("worksheets", [])
    if worksheets and isinstance(worksheets, list) and worksheets:
        ws = worksheets[0]
        ds = ws.get("datasource") or ws.get("table") or ws.get("datasourceName")
        if ds:
            return ds
    ds = (
        tableau_json.get("datasource")
        or tableau_json.get("table")
        or tableau_json.get("datasourceName")
    )
    if ds:
        return ds
    return None


def clean_series_property_name(name: str) -> str:
    """
    Robustly clean series property names.

    - Return None for non-string or empty input.
    - Extract the innermost parenthesized token if present (use last match).
    - Remove characters except alnum, underscore, and dot.
    - Take last dotted segment.
    - Return simple identifier only if it matches ^[A-Za-z_][A-Za-z0-9_]*$.
    - Otherwise return None.
    """
    if not name or not isinstance(name, str):
        return None

    # If there are nested parentheses, pick the innermost (last) match.
    inner_matches = re.findall(r"\(([^()]+)\)", name)
    token = inner_matches[-1] if inner_matches else name

    # Remove unwanted chars but keep dot for dotted notation handling
    token = re.sub(r"[^A-Za-z0-9_\.]", "", token)

    # If dotted, use last segment
    if "." in token:
        token = token.split(".")[-1]

    base = extract_base_property(token)
    if not base:
        return None

    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
        return base
    return None


# to be updated for multitable compatablity
def clean_tableau_field_name(name: str) -> str:
    # Remove Tableau suffixes like ":nk", ":qk" if any
    if ":" in name:
        base, suffix = name.rsplit(":", 1)
        if len(suffix) <= 4 and suffix.isalpha():
            return base
    return name


def extract_base_property(prop: str) -> str:
    """
    Extract a clean base property name from property string that may contain nested aggregations,
    e.g. "RUNNING_SUM(SUM(Profit))" -> "Profit"
    """
    # use regex to find innermost property name, fallback to prop itself
    match = re.search(r"\(?([A-Za-z_][A-Za-z0-9_]*)\)?\)?$", prop)
    if match:
        return match.group(1)
    return prop


def extract_bracketed_expressions(text):
    return re.findall(r"\[(.*?)\]", text)


def normalise_agg(agg: str) -> str:
    synonyms = {"CNT": "COUNT", "AVERAGE": "AVG", "RUNNING_TOTAL": "SUM", "CUMM": "SUM"}
    agg = agg.upper()
    return synonyms.get(agg, agg)


def infer_entity_and_property(expression, default_entity=None):
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
        prop = clean_tableau_field_name(prop)
        return agg_func, entity, prop
    m = re.match(r"^(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_:.\s]+)$", expression_stripped)
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


def has_hierarchy(category_col):
    derivation = category_col.get("derivation", "").lower()
    if derivation == "none" or derivation == "" or derivation == "user":
        return False
    else:
        return True


def _is_artificial_series_name(name: str) -> bool:
    """
    Detect artificial/invalid series property names like:
    - User(Profit)
    - -SUM(Profit)
    - SUM(Profit)
    - User(-SUM(...))
    """
    if not name or not isinstance(name, str):
        return True
    lowered = name.lower().strip()
    return any(
        lowered.startswith(prefix)
        for prefix in ["user(", "sum(", "-sum(", "avg(", "min(", "max("]
    )


def build_field_projection(
    entity_name: str, column_name: str, derivation: str = None, active: bool = True
):
    """
    Build a Power BI field projection:
    - If derivation in {Year, Quarter, Month, Day} → HierarchyLevel (Date Hierarchy).
    - Else → Column projection.
    """
    if derivation in {"Year", "Quarter", "Month", "Day"}:
        field = {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {"SourceRef": {"Entity": entity_name}},
                                "Name": "Variation",
                                "Property": column_name,
                            }
                        },
                        "Hierarchy": "Date Hierarchy",
                    }
                },
                "Level": derivation,
            }
        }
        query_ref = f"{entity_name}.{column_name}.Variation.Date Hierarchy.{derivation}"
        native_query_ref = f"{column_name} {derivation}"
    else:
        field = {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity_name}},
                "Property": column_name,
            }
        }
        query_ref = f"{entity_name}.{column_name}"
        native_query_ref = column_name

    return {
        "field": field,
        "queryRef": query_ref,
        "nativeQueryRef": native_query_ref,
        "active": active,
    }


def convert_tableau_to_powerbi_waterfall(
    twb_json, position=None, name=None, default_entity=None, entity_map=None
):
    """
    Convert Tableau-style JSON to Power BI waterfall visual JSON.
    Fixes invalid/malformed series names and adds date hierarchy support.
    """
    worksheets = twb_json.get("worksheets", [twb_json])
    all_categories, all_series, all_values = [], [], []
    entity_map = entity_map or {}
    global_measure_props = set()

    # --- Pass 1: collect measure property names to avoid duplicate series ---
    for worksheet in worksheets:
        mapped_fields = map_worksheet_fields(worksheet)
        for m in mapped_fields["measures"]:
            prop = m.get("Property")
            if prop and isinstance(prop, str):
                cleaned = extract_base_property(clean_tableau_field_name(prop))
                if cleaned:
                    global_measure_props.add(cleaned)

    # --- Pass 2: build projections ---
    for worksheet in worksheets:
        mapped_fields = map_worksheet_fields(worksheet)

        # Categories
        for cat in mapped_fields["categories"]:
            if not is_valid_field_name(cat.get("Property")):
                continue
            entity = (
                entity_map.get(cat["Property"])
                if cat["Property"] in entity_map
                else cat.get("Entity")
            )
            entity = (
                entity or default_entity or extract_default_entity(twb_json) or "Orders"
            )

            all_categories.append(
                build_field_projection(entity, cat["Property"], cat.get("Derivation"))
            )

        # Series
        s = mapped_fields.get("series")
        if s:
            raw_prop = s.get("Property")
            if not _is_artificial_series_name(raw_prop):
                cleaned = clean_series_property_name(raw_prop)
                if cleaned and cleaned not in global_measure_props:
                    entity = (
                        entity_map.get(s.get("Property"))
                        if s.get("Property") in entity_map
                        else (
                            entity_map.get(cleaned)
                            if cleaned in entity_map
                            else s.get("Entity")
                        )
                    )
                    entity = (
                        entity
                        or default_entity
                        or extract_default_entity(twb_json)
                        or "Orders"
                    )
                    all_series.append(
                        build_field_projection(
                            entity, cleaned, s.get("Derivation"), active=False
                        )
                    )

        # Measures (Y-axis)
        for m in mapped_fields["measures"]:
            if not is_valid_field_name(m.get("Property")):
                continue
            prop, deriv = m["Property"], m.get("Derivation") or "SUM"
            agg_code = map_aggregation(deriv)
            agg_labels = ["Sum", "Avg", "Count", "Min", "Max"]
            agg_label = agg_labels[agg_code] if agg_code < len(agg_labels) else "Sum"

            entity = entity_map.get(prop) if prop in entity_map else m.get("Entity")
            entity = (
                entity or default_entity or extract_default_entity(twb_json) or "Orders"
            )

            all_values.append(
                {
                    "field": {
                        "Aggregation": {
                            "Expression": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": entity}},
                                    "Property": prop,
                                }
                            },
                            "Function": agg_code,
                        }
                    },
                    "queryRef": f"{agg_label}({entity}.{prop})",
                    "nativeQueryRef": f"{agg_label} of {prop}",
                }
            )

    if not all_series:
        all_series = []

    position = position or {
        "x": 217.66419871029376,
        "y": 110.054931932171,
        "z": 0,
        "height": 544.16049677573449,
        "width": 855.98280391688559,
    }

    sort_definition = {
        "sort": (
            [{"field": all_values[0]["field"], "direction": "Descending"}]
            if all_values
            else []
        ),
        "isDefaultSort": True,
    }

    query_state = {
        "Category": {"projections": all_categories},
        "Series": {"projections": all_series},
        "Y": {"projections": all_values},
    }

    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json",
        "name": uuid.uuid4().hex[:20] if not name else name,
        "position": position,
        "visual": {
            "visualType": "waterfallChart",
            "query": {"queryState": query_state, "sortDefinition": sort_definition},
            "drillFilterOtherVisuals": True,
        },
    }

    return powerbi_json

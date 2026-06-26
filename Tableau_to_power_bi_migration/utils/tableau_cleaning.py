import re
import random

# ==========================
# Name Cleaning Utilities
# ==========================

def clean_tableau_name(name):

    if not name:
        return "Table1"

    s = str(name)

    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]

    s = s.replace("none:", "")
    s = s.replace("sum:", "")
    s = s.replace("avg:", "")
    s = s.replace("count:", "")
    s = s.replace(":qk", "")
    s = s.replace(":nk", "")
    s = s.replace(":ok", "")

    # REMOVE FILE EXTENSIONS
    s = re.sub(
        r"\.(csv|xlsx|xls|txt|json)$",
        "",
        s,
        flags=re.IGNORECASE
    )

    return s.strip()

def clean_field_name(field_name):
    """
    Cleans Tableau field names.
    Example:
        [sum:Sales:qk] -> Sales
        [none:Segment:nk] -> Segment
        [mn:Order Date:ok] -> Order Date
    """

    if not field_name or not isinstance(field_name, str):
        return None

    field_name = str(field_name)

    # Remove brackets
    field_name = field_name.replace("[", "").replace("]", "")

    # Split by :
    parts = field_name.split(":")

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
    }

    if len(parts) >= 2:

        first = parts[0].lower()

        if first in tableau_prefixes:
            return parts[1].strip()

    return parts[0].strip()


# ==========================
# Validation Helpers
# ==========================

def is_valid_field_name(name):

    invalid = {
        None,
        "",
        "none",
        "color",
        "text",
        "measure names",
        "measure values",
        "multiple values",
    }

    return (
        isinstance(name, str)
        and name.strip().lower() not in invalid
    )


# ==========================
# Aggregation Helpers
# ==========================

AGGREGATION_MAP = {

    "sum": 0,

    "avg": 1,
    "average": 1,

    "count": 2,
    "cnt": 2,

    "countd": 3,

    "min": 4,

    "max": 5,

    "median": 6,

    "var": 7,

    "varp": 8,

    "stdev": 9,

    "stdevp": 10,

    "attr": 11,

    "collect": 12,

    "corr": 13,

    "covar": 14,

    "covarp": 15,

    "none": None,
}


def get_aggregation_map():
    return AGGREGATION_MAP.copy()


def map_aggregation(func_name, default_code=0):

    if not func_name:
        return default_code

    key = str(func_name).strip().lower()
    if key in {"", "none", "null"}:
        return default_code

    code = AGGREGATION_MAP.get(key, default_code)
    return default_code if code is None else code


CODE_TO_AGG = {}

for k, v in AGGREGATION_MAP.items():

    if v is None:
        continue

    CODE_TO_AGG.setdefault(v, k.title())


def agg_code_to_str(code, default="Sum"):

    if code is None:
        return default

    return CODE_TO_AGG.get(code, default)


def parse_tableau_calc_formula(formula):
    """Parse common Tableau calculated aggregation formulas.

    Returns Derivation and Property for formulas like COUNTD([Customer ID]).
    """

    if not formula or not isinstance(formula, str):
        return None

    formula = formula.strip()

    match = re.match(
        r"^(?P<agg>sum|avg|average|countd|count|cnt|min|max|median)\s*\(\s*\[?(?P<prop>[^\]\)]+)\]?\s*\)",
        formula,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return {
        "Derivation": match.group("agg").lower(),
        "Property": clean_field_name(match.group("prop")),
    }


# ==========================
# Entity/Table Extraction
# ==========================

def get_entity(field, entity_map=None):

    entity_map = entity_map or {}

    candidate = "Table1"

    if isinstance(field, dict):

        candidate = (
            field.get("parent-name")
            or field.get("table")
            or "Table1"
        )

    elif isinstance(field, str):

        if "." in field:
            candidate = field.split(".")[0]
        else:
            candidate = field

    mapped = entity_map.get(candidate, candidate)

    return clean_tableau_name(mapped)


# ==========================
# Field Extraction
# ==========================

def extract_field_with_entity(field):

    if not field:
        return None

    # ------------------------------------
    # STRING FORMAT
    # ------------------------------------

    if isinstance(field, str):

        cleaned = clean_field_name(field)

        if not is_valid_field_name(cleaned):
            return None

        entity = get_entity(field)

        return {
            "Property": cleaned,
            "Entity": entity,
            "Derivation": None,
            "LocalType": "",
        }

    # ------------------------------------
    # DICT FORMAT
    # ------------------------------------

    if not isinstance(field, dict):
        return None

    native_name = field.get("Native name", "")

    if (
        isinstance(native_name, str)
        and native_name.strip().lower() == "calculated"
    ):
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

    if not is_valid_field_name(property_name):
        return None

    entity_name = get_entity(field)

    derivation = field.get("derivation")

    return {
        "Property": property_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": str(
            field.get("local-type", "")
        ).lower(),
    }


# ==========================
# Date Hierarchy Helpers
# ==========================

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


# ==========================
# Projection Builders
# ==========================

def build_dimension_projection(entity, prop):

    entity = clean_tableau_name(entity)
    prop = clean_field_name(prop)

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


def build_date_hierarchy_projection(entity, prop, level):

    entity = clean_tableau_name(entity)
    prop = clean_field_name(prop)

    level = str(level).capitalize()

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
        "queryRef": f"{entity}.{prop}.Variation.Date Hierarchy.{level}",
        "nativeQueryRef": f"{prop} {level}",
        "active": True,
    }


def build_measure_projection(entity, prop, agg_code):

    entity = clean_tableau_name(entity)
    prop = clean_field_name(prop)

    if agg_code is None:
        agg_code = 0

    agg_name = agg_code_to_str(agg_code)

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
        "queryRef": f"{agg_name}({entity}.{prop})",
        "nativeQueryRef": f"{agg_name} of {prop}",
    }


# ==========================
# Encoding Helper
# ==========================

def get_encoding(encodings, key):

    if not encodings:
        return None

    val = encodings.get(key)

    if isinstance(val, list):
        return val[0] if val else None

    return val


# ==========================
# Filter Builder
# ==========================

def build_filter(field_projection, filter_type):

    return {
        "name": re.sub(
            "-",
            "",
            str(random.random())
        )[:20],

        "field": field_projection["field"],

        "type": filter_type,
    }


# ==========================
# Visual Extraction Helper
# ==========================

def extract_fields(encodings):

    category_field = None

    for key in ["color", "columns", "rows"]:

        item = encodings.get(key)

        if isinstance(item, dict) and item.get("column"):

            category_field = item["column"]
            break

    size_info = encodings.get("size", {})

    measure_field = size_info.get("column")

    agg_func = size_info.get("derivation", "sum")

    agg_code = map_aggregation(agg_func, 0)

    return (
        category_field,
        measure_field,
        agg_func,
        agg_code,
    )


# ==========================
# Position Generator
# ==========================

def generate_position():

    return {
        "x": random.uniform(80, 250),

        "y": random.uniform(80, 250),

        "z": 0,

        "height": random.uniform(250, 450),

        "width": random.uniform(450, 750),
    }


# ==========================
# Table / Matrix Helpers
# ==========================

def calc_token_from_field_name(name):
    if not name:
        return None
    match = re.search(r"(Calculation_\d+)", str(name), re.IGNORECASE)
    return match.group(1) if match else None


def enrich_field_from_workbook(field, workbook):
    """Attach formula/caption from workbook.calculations for usr:/calc tokens."""
    if not isinstance(field, dict) or not workbook:
        return field
    if field.get("formula"):
        return field

    token = calc_token_from_field_name(
        field.get("name") or field.get("name_calc") or ""
    )
    if not token:
        return field

    for calc in workbook.get("calculations") or []:
        calc_name = str(calc.get("name") or "").strip().strip("[]")
        if calc_name and calc_name == token:
            merged = dict(field)
            if calc.get("caption"):
                merged.setdefault("caption", calc.get("caption"))
            if calc.get("formula"):
                merged.setdefault("formula", calc.get("formula"))
            merged.setdefault("name_calc", calc.get("name_calc") or f"[{calc_name}]")
            return merged

    return field


def recover_partial_tableau_field(field, default_entity="Orders"):
    """Recover dimension metadata when parser shelf tokens are split/corrupted."""
    if not isinstance(field, dict):
        return None
    if field.get("column") or field.get("local-name"):
        return field

    name = str(field.get("name") or "")
    match = re.search(
        r"(?:none|sum|avg|yr|mn|qtr|wk|day):([A-Za-z0-9 \-]+)",
        name,
        re.IGNORECASE,
    )
    if not match:
        tail = re.search(r"^([A-Za-z0-9 \-]+):n[ko]?\]", name)
        if tail:
            match = tail
    if not match:
        return field

    prop = match.group(1).strip()
    return {
        "column": prop,
        "local-name": prop,
        "parent-name": field.get("parent-name") or default_entity,
        "derivation": "None",
        "name": f"[none:{prop}:nk]",
        "local-type": "string",
    }


def is_measure_names_placeholder_field(field):
    if not isinstance(field, dict):
        return False
    name = str(field.get("name") or "").lower()
    return "measure names" in name or "measure values" in name or "multiple values" in name


def has_measure_names_context(ws):
    for filt in ws.get("filters") or []:
        if "measure names" in str(filt.get("column") or "").lower():
            return True
    for fld in (ws.get("rows") or []) + (ws.get("cols") or []):
        if is_measure_names_placeholder_field(fld):
            return True
    return bool(ws.get("measure_names"))


def expand_axis_fields(fields):
    """Split combined shelf tokens and Tableau hierarchy pipes."""
    expanded = []
    for fld in fields or []:
        if not isinstance(fld, dict):
            continue
        name = str(fld.get("name") or "")

        hier_match = re.match(r"^\[(?:none|sum|[^:]+):(.+)\]$", name)
        if hier_match and "|" in hier_match.group(1) and not fld.get("column"):
            inner = hier_match.group(1)
            suffix_match = re.search(r":(nk|ok|qk)$", inner)
            suffix = suffix_match.group(1) if suffix_match else "nk"
            body = inner[: suffix_match.start()] if suffix_match else inner
            for part in body.split("|"):
                part = part.strip()
                if part:
                    token_meta = {"name": f"[none:{part}:{suffix}]"}
                    if fld.get("parent-name"):
                        token_meta["parent-name"] = fld.get("parent-name")
                    expanded.append(token_meta)
            continue

        if "+" in name and not fld.get("column"):
            for part in re.split(r"\s*\+\s*", name):
                part = part.strip()
                if part:
                    token_meta = {"name": part}
                    if fld.get("parent-name"):
                        token_meta["parent-name"] = fld.get("parent-name")
                    expanded.append(token_meta)
        else:
            expanded.append(fld)
    return expanded


def build_named_model_measure(name):
    if not name:
        return None
    return {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": "_Measures"}},
                "Property": name,
            }
        },
        "queryRef": f"_Measures.{name}",
        "nativeQueryRef": name,
    }


def build_table_calc_model_measure(field, workbook=None):
    """Map Tableau quick table calcs (e.g. % of total) to _Measures references."""
    if not isinstance(field, dict):
        return None

    calc_type = str(field.get("table-calc:type") or "").lower()
    name_token = str(field.get("name") or "").lower()
    if not calc_type and "pcto:" not in name_token:
        return None

    prop = clean_field_name(field.get("column") or field.get("local-name") or "")
    if not prop:
        return None

    ordering = str(field.get("table-calc:ordering-type") or "").strip().lower()
    if calc_type == "pcttotal" or "pcto:" in name_token:
        if ordering == "columns":
            candidates = [
                f"{prop} % of Column Total",
                f"% of Column Total {prop}",
                f"{prop} % of Total",
                f"% of Total {prop}",
            ]
        elif ordering == "rows":
            candidates = [
                f"{prop} % of Row Total",
                f"% of Row Total {prop}",
                f"{prop} % of Total",
                f"% of Total {prop}",
            ]
        else:
            candidates = [
                f"{prop} % of Total",
                f"% of Total {prop}",
                f"{prop} Pct of Total",
            ]
    else:
        caption = str(field.get("caption") or "").strip()
        candidates = [caption] if caption else [prop]

    workbook_names = {
        str(c.get("caption") or "")
        for c in (workbook or {}).get("calculations") or []
        if c.get("caption")
    }
    for candidate in candidates:
        if candidate in workbook_names:
            return build_named_model_measure(candidate)

    return build_named_model_measure(candidates[0])


def resolve_measure_name_members(ws, workbook=None):
    """Resolve explicit Measure Names members for multi-measure matrix visuals."""
    members = []
    seen = set()

    def add_member(field_dict):
        if not isinstance(field_dict, dict):
            return
        token = field_dict.get("name") or field_dict.get("column")
        if not token or token in seen:
            return
        if is_measure_names_placeholder_field(field_dict):
            return
        seen.add(token)
        members.append(field_dict)

    for member in ws.get("measure_names") or []:
        add_member(member if isinstance(member, dict) else {"name": member})

    for filt in ws.get("filters") or []:
        if "measure names" not in str(filt.get("column") or "").lower():
            continue
        for raw_member in filt.get("members") or []:
            token = str(raw_member).replace("&quot;", "").strip()
            bracket_parts = re.findall(r"\[([^\]]+)\]", token)
            if bracket_parts:
                token = f"[{bracket_parts[-1]}]"
            elif token and not token.startswith("["):
                token = f"[{token}]"
            if token:
                add_member({"name": token})

    if workbook:
        for measure in workbook.get("available_measures") or []:
            add_member(measure)

        if not members:
            for other_ws in workbook.get("worksheets") or []:
                for key in ("text", "color", "size", "label"):
                    enc = (other_ws.get("encodings") or {}).get(key)
                    candidates = enc if isinstance(enc, list) else [enc] if isinstance(enc, dict) else []
                    for item in candidates:
                        add_member(item)

    return members


def build_model_measure_reference(calc_info):
    """Map COUNTD-style calcs to semantic-model _Measures references."""
    if not calc_info:
        return None

    deriv = str(calc_info.get("Derivation", "")).lower()
    prop = calc_info.get("Property", "Measure")
    prop_clean = re.sub(r"\bID\b$", "", prop, flags=re.IGNORECASE).strip()
    prop_clean = re.sub(r"\s+", " ", prop_clean).title()

    if deriv in {"countd"}:
        name = f"Distinct {prop_clean}"
    elif deriv in {"count", "cnt"}:
        name = f"Count {prop_clean}"
    elif deriv in {"sum"}:
        name = f"Sum {prop_clean}"
    elif deriv in {"avg", "average"}:
        name = f"Average {prop_clean}"
    else:
        name = prop_clean or "Measure"

    return {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": "_Measures"}},
                "Property": name,
            }
        },
        "queryRef": f"_Measures.{name}",
        "nativeQueryRef": name,
    }


def is_measure_like_table_field(field):
    if not isinstance(field, dict):
        return False

    name = str(field.get("name", "")).lower()
    if any(tok in name for tok in ("sum:", "avg:", "cnt:", "cntd:", "ctd:", "usr:", "pcto:")):
        return True

    deriv = str(field.get("derivation", "")).lower()
    if deriv in {"sum", "avg", "average", "count", "countd", "cnt", "min", "max", "median", "user"}:
        return True

    if parse_tableau_calc_formula(
        field.get("formula") or field.get("name_calc") or field.get("name") or ""
    ):
        return True

    return False


def table_field_to_measure_projection(field, workbook=None, default_entity="Orders"):
    """Build a Values projection from a Tableau measure field dict."""
    field = enrich_field_from_workbook(field, workbook)

    table_calc_proj = build_table_calc_model_measure(field, workbook)
    if table_calc_proj:
        return table_calc_proj

    calc_info = parse_tableau_calc_formula(
        field.get("formula") or field.get("name_calc") or field.get("name") or ""
    )
    if calc_info and str(calc_info.get("Derivation", "")).lower() in {
        "countd",
        "count",
        "cnt",
    }:
        return build_model_measure_reference(calc_info)

    field = recover_partial_tableau_field(field) or field
    mapped = extract_field_with_entity(field)
    if not mapped:
        name = str(field.get("name") or "")
        agg_match = re.search(
            r"(sum|avg|average|countd|count|cnt|min|max|pcto):([^:\]]+)",
            name,
            re.IGNORECASE,
        )
        if agg_match:
            mapped = {
                "Entity": field.get("parent-name") or default_entity,
                "Property": clean_field_name(agg_match.group(2)),
                "Derivation": agg_match.group(1).lower(),
            }

    if not mapped:
        return None

    entity = clean_tableau_name(mapped.get("Entity") or default_entity)
    prop = clean_field_name(mapped.get("Property"))
    if not prop:
        return None

    deriv = str(mapped.get("Derivation") or "sum").lower()
    if deriv.startswith("pcto"):
        deriv = "sum"

    agg_code = map_aggregation(deriv, 0)
    return build_measure_projection(entity, prop, agg_code)


def collect_table_measure_fields(ws, workbook=None):
    """Gather measure fields from encodings, measure_names, and workbook fallbacks."""
    encodings = ws.get("encodings") or {}
    measures = []
    seen = set()

    def add_measure(field):
        if not isinstance(field, dict):
            return
        enriched = enrich_field_from_workbook(field, workbook)
        if is_measure_names_placeholder_field(enriched):
            return
        if not (
            is_measure_like_table_field(enriched)
            or enriched.get("table-calc:type")
            or "pcto:" in str(enriched.get("name") or "").lower()
        ):
            return
        proj = table_field_to_measure_projection(enriched, workbook)
        if not proj:
            return
        ref = proj.get("queryRef")
        if ref and ref not in seen:
            seen.add(ref)
            measures.append((enriched, proj))

    if has_measure_names_context(ws):
        for member in resolve_measure_name_members(ws, workbook):
            add_measure(member)
        if measures:
            return measures

    for key in ("text", "color", "size", "label"):
        enc = encodings.get(key)
        if isinstance(enc, list):
            for item in enc:
                add_measure(item)
        elif isinstance(enc, dict):
            add_measure(enc)

    for member in ws.get("measure_names") or []:
        member_field = member if isinstance(member, dict) else {"name": member}
        add_measure(member_field)

    if not measures and workbook:
        for other_ws in workbook.get("worksheets") or []:
            if other_ws is ws:
                continue
            text_enc = (other_ws.get("encodings") or {}).get("text")
            candidates = []
            if isinstance(text_enc, dict):
                candidates = [text_enc]
            elif isinstance(text_enc, list):
                candidates = text_enc
            for item in candidates:
                before = len(measures)
                add_measure(item)
                if len(measures) > before:
                    break
            if measures:
                break

    return measures
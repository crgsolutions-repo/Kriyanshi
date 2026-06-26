import uuid
import re
import random

from utils.tableau_cleaning import (
    clean_tableau_name,
    clean_field_name,
    map_aggregation,
    agg_code_to_str,
    get_encoding as util_get_encoding,
    parse_tableau_calc_formula,
)

# =====================================================
# HELPERS
# =====================================================

def get_encoding(encodings, key):
    return util_get_encoding(encodings, key)

def extract_field_with_entity(field):

    if not isinstance(field, dict):
        return None

    raw_col = field.get("column") or field.get("local-name")

    if not raw_col:
        return None

    property_name = clean_field_name(raw_col)

    if not property_name:
        return None

    entity_name = clean_tableau_name(field.get("parent-name") or field.get("table") or "Table1")

    derivation = field.get("derivation")

    # If the field is a user calc, try parsing simple aggregate formula
    if str(derivation).lower() in {"user", "none"}:
        calc = parse_tableau_calc_formula(field.get("formula") or field.get("name_calc") or field.get("name") or "")
        if calc:
            derivation = calc.get("Derivation")
            property_name = calc.get("Property", property_name)

    return {
        "Property": property_name,
        "Entity": entity_name,
        "Derivation": derivation,
        "LocalType": str(field.get("local-type", "")).lower(),
    }

def normalize_extracted_field(raw_field, rows, cols, encodings):
    extracted = extract_field_with_entity(raw_field) if isinstance(raw_field, dict) else None
    if not extracted:
        return None

    if extracted["Entity"] == "Table1":
        # try infer entity from other fields
        candidates = list(rows + cols)
        for val in encodings.values():
            if isinstance(val, list):
                candidates.extend(val)
            elif isinstance(val, dict):
                candidates.append(val)

        default_entity = None
        for candidate in candidates:
            c = extract_field_with_entity(candidate) if isinstance(candidate, dict) else None
            if not c:
                continue
            if c["Entity"] != "Table1" and default_entity is None:
                default_entity = c["Entity"]
            if c["Property"] == extracted["Property"] and c["Entity"] != "Table1":
                extracted["Entity"] = c["Entity"]
                return extracted

        if default_entity:
            extracted["Entity"] = default_entity

    return extracted

# =====================================================
# PROJECTIONS
# =====================================================

def resolve_date_category_properties(field):
    """Resolve date field to list of property names for split projections (Month-Trunc only)."""
    deriv = str(field.get("Derivation", "")).lower()
    local_type = str(field.get("LocalType", "")).lower()

    props = []
    if local_type == "date" or "date" in deriv:
        # Only split on month-trunc; single date levels use HierarchyLevel
        if "month-trunc" in deriv or "month_trunc" in deriv:
            props = ["Year_", "Month_"]

    return props


def get_date_hierarchy_level(field):
    """Map derivation to date hierarchy level name for HierarchyLevel projections."""
    deriv = str(field.get("Derivation", "")).lower()
    
    if "month" in deriv and "month-trunc" not in deriv and "month_trunc" not in deriv:
        return "Month"
    elif "year" in deriv:
        return "Year"
    elif "quarter" in deriv:
        return "Quarter"
    elif "day" in deriv:
        return "Day"
    elif "week" in deriv:
        return "Week"
    
    return None

def build_category_projection_hierarchy(field):
    """Build HierarchyLevel projection for single date levels (Month, Year, etc.)."""
    level = get_date_hierarchy_level(field)
    if not level:
        return None
    
    date_field_prop = field["Property"]
    # Construct hierarchy reference
    hierarchy_ref = f"{field['Entity']}.{date_field_prop}.Variation.Date Hierarchy.{level}"
    native_ref = f"{date_field_prop} {level}"
    return {
        "field": {
            "HierarchyLevel": {
                "Expression": {
                    "Hierarchy": {
                        "Expression": {
                            "PropertyVariationSource": {
                                "Expression": {
                                    "SourceRef": {"Entity": field["Entity"]}
                                },
                                "Name": "Variation",
                                "Property": date_field_prop,
                            }
                        },
                        "Hierarchy": "Date Hierarchy",
                    }
                },
                "Level": level,
            }
        },
        "queryRef": hierarchy_ref,
        "nativeQueryRef": native_ref,
        "active": True,
    }

def build_category_projections(field):
    """Build category projections: HierarchyLevel for simple date levels, Column split for Month-Trunc."""
    # Try HierarchyLevel for simple date levels
    hierarchy_proj = build_category_projection_hierarchy(field)
    if hierarchy_proj:
        return [hierarchy_proj]
    
    # Fall back to split properties for Month-Trunc or non-date fields
    properties = resolve_date_category_properties(field) or [field["Property"]]
    projections = []
    for prop in properties:
        projections.append({
            "field": {"Column": {"Expression": {"SourceRef": {"Entity": field["Entity"]}}, "Property": prop}},
            "queryRef": f"{field['Entity']}.{prop}",
            "nativeQueryRef": prop,
            "active": True,
        })
    return projections

def build_measure_projection(field):
    agg_code = map_aggregation(field.get("Derivation"))
    agg_name = agg_code_to_str(agg_code)

    return {
        "field": {"Aggregation": {"Expression": {"Column": {"Expression": {"SourceRef": {"Entity": field["Entity"]}}, "Property": field["Property"]}}, "Function": agg_code}},
        "queryRef": f"{agg_name}({field['Entity']}.{field['Property']})",
        "nativeQueryRef": f"{agg_name} of {field['Property']}",
    }

def build_measure_reference_from_calc(calc_info):
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
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}},
        "queryRef": f"_Measures.{name}",
        "nativeQueryRef": name,
    }


def _parse_calc_info_from_field(field):
    if not isinstance(field, dict):
        return None
    return parse_tableau_calc_formula(
        field.get("formula")
        or field.get("name_calc")
        or field.get("name")
        or ""
    )


def _is_countd_style_calc(calc_info):
    if not calc_info:
        return False
    return str(calc_info.get("Derivation", "")).lower() in {"countd", "count", "cnt"}


def _projection_query_refs(projections):
    return {
        p.get("queryRef")
        for p in (projections or [])
        if isinstance(p, dict) and p.get("queryRef")
    }


def _find_secondary_measures_calc_projection(encodings, measure_projections):
    """
    Tableau often puts COUNTD calcs on Text/Color while Sum(Sales) stays on Rows.
    Map those to Power BI secondary Y-axis (_Measures.*) when not already on Y.
    """
    existing_refs = _projection_query_refs(measure_projections)

    for key in ("text", "color", "label", "detail"):
        enc = get_encoding(encodings, key)
        candidates = []
        if isinstance(enc, list):
            candidates = [c for c in enc if isinstance(c, dict)]
        elif isinstance(enc, dict):
            candidates = [enc]

        for item in candidates:
            if key == "color" and not _is_measure_like_field(item):
                continue
            calc_info = _parse_calc_info_from_field(item)
            if not _is_countd_style_calc(calc_info):
                continue
            proj = build_measure_reference_from_calc(calc_info)
            if proj and proj.get("queryRef") not in existing_refs:
                return proj

    return None

# =====================================================
# MAIN BUILDER
# =====================================================

def _find_countd_calc_in_workbook(workbook):
    if not workbook or not isinstance(workbook.get('worksheets', []), list):
        return None
    for ws in workbook.get('worksheets', []):
        enc = ws.get('encodings', {}) or {}
        # check text and color encodings for calc formulas
        for key in ('text', 'color'):
            val = enc.get(key)
            if isinstance(val, dict):
                formula = val.get('formula') or val.get('name_calc') or val.get('name') or ''
                calc = parse_tableau_calc_formula(formula)
                if calc and str(calc.get('Derivation','')).lower() in {'countd'}:
                    return calc
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        formula = item.get('formula') or item.get('name_calc') or item.get('name') or ''
                        calc = parse_tableau_calc_formula(formula)
                        if calc and str(calc.get('Derivation','')).lower() in {'countd'}:
                            return calc
    return None

def _find_measures_from_matching_worksheets(category, workbook):
    found_measures = []
    found_calcs = []
    if not workbook or not isinstance(workbook.get('worksheets', []), list) or not category:
        return found_measures, found_calcs

    cat_prop = category.get("Property")
    cat_entity = category.get("Entity")
    cat_deriv = str(category.get("Derivation", "")).lower()

    for ws in workbook.get('worksheets', []):
        rows = ws.get("rows", [])
        cols = ws.get("cols", [])
        encodings = ws.get("encodings") or ws.get("table", {}).get("encodings") or {}

        # Detect category in this other worksheet
        other_cat_field = None
        for fld in cols + rows:
            if not isinstance(fld, dict):
                continue
            if extract_field_with_entity(fld):
                other_cat_field = fld
                break
        if not other_cat_field:
            continue

        other_cat = extract_field_with_entity(other_cat_field)
        if not other_cat:
            continue

        # Check if category matches
        if (other_cat.get("Property") == cat_prop and 
            other_cat.get("Entity") == cat_entity and 
            str(other_cat.get("Derivation", "")).lower() == cat_deriv):
            
            # This worksheet is a match! Let's extract its measures
            for member in ws.get("measure_names") or []:
                field = member if isinstance(member, dict) else {"name": member}
                formula = field.get("formula") or field.get("name_calc") or field.get("name") or ""
                calc_info = parse_tableau_calc_formula(formula)
                if calc_info and str(calc_info.get("Derivation", "")).lower() in {"countd"}:
                    if field not in found_calcs:
                        found_calcs.append(field)
                    continue
                m = normalize_extracted_field(field, rows, cols, encodings)
                if m and m not in found_measures:
                    found_measures.append(m)

            # 1. Look in rows + cols for measures
            for fld in rows + cols:
                if not isinstance(fld, dict):
                    continue
                local_type = str(fld.get("local-type", "")).lower()
                deriv = str(fld.get("derivation", "")).lower()
                if deriv in {"sum", "avg", "average", "count", "min", "max", "median"} or local_type in {"real", "integer", "numeric"}:
                    m = normalize_extracted_field(fld, rows, cols, encodings)
                    if m and m not in found_measures:
                        found_measures.append(m)

            # 2. Look in encodings for measures/calcs
            for key, val in encodings.items():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            formula = item.get("formula") or item.get("name_calc") or item.get("name") or ""
                            calc_info = parse_tableau_calc_formula(formula)
                            if calc_info:
                                if item not in found_calcs:
                                    found_calcs.append(item)
                            else:
                                local_type = str(item.get("local-type", "")).lower()
                                deriv = str(item.get("derivation", "")).lower()
                                if deriv in {"sum", "avg", "average", "count", "min", "max", "median"} or local_type in {"real", "integer", "numeric"}:
                                    m = normalize_extracted_field(item, rows, cols, encodings)
                                    if m and m not in found_measures:
                                        found_measures.append(m)
                elif isinstance(val, dict):
                    formula = val.get("formula") or val.get("name_calc") or val.get("name") or ""
                    calc_info = parse_tableau_calc_formula(formula)
                    if calc_info:
                        if val not in found_calcs:
                            found_calcs.append(val)
                    else:
                        local_type = str(val.get("local-type", "")).lower()
                        deriv = str(val.get("derivation", "")).lower()
                        if deriv in {"sum", "avg", "average", "count", "min", "max", "median"} or local_type in {"real", "integer", "numeric"}:
                            m = normalize_extracted_field(val, rows, cols, encodings)
                            if m and m not in found_measures:
                                found_measures.append(m)

    return found_measures, found_calcs

def _is_measure_names_multi_line(ws):
    """
    Detect Tableau pattern:
    - rows contains [Multiple Values]
    - color encoding uses [:Measure Names]

    This should generate ALL measures inside Y projections only.
    """

    rows = ws.get("rows", [])
    encodings = ws.get("encodings") or ws.get("table", {}).get("encodings") or {}

    has_multiple_values = any(
        isinstance(r, dict)
        and str(r.get("name", "")).lower().startswith("[multiple")
        for r in rows
    )

    color_enc = encodings.get("color")

    has_measure_names = (
        isinstance(color_enc, dict)
        and color_enc.get("name") == "[:Measure Names]"
    )

    return has_multiple_values and has_measure_names


def _is_multiple_values_placeholder(field):
    if not isinstance(field, dict):
        return False
    name = str(field.get("name", "")).lower()
    return name.startswith("[multiple") or name in {"multiple values", "[multiple values]"}


def _field_dict_to_projection(field, rows, cols, encodings):
    """Map a Tableau field dict (or measure-name member) to a Power BI Y projection."""
    if not isinstance(field, dict):
        return None

    formula = field.get("formula") or field.get("name_calc") or ""
    calc_info = parse_tableau_calc_formula(formula)
    if not calc_info:
        calc_info = parse_tableau_calc_formula(field.get("name") or "")

    name = str(field.get("name") or "")
    if not calc_info:
        agg_match = re.search(
            r"(sum|avg|average|countd|count|cnt|min|max|median)\s*:\s*([^:\]]+)",
            name,
            re.IGNORECASE,
        )
        if agg_match:
            calc_info = {
                "Derivation": agg_match.group(1).lower(),
                "Property": clean_field_name(agg_match.group(2)),
            }

    if calc_info:
        deriv = str(calc_info.get("Derivation", "")).lower()
        if deriv in {"countd", "count", "cnt"}:
            return build_measure_reference_from_calc(calc_info)
        if deriv in {"sum", "avg", "average", "min", "max", "median"}:
            entity = "Orders"
            for candidate in rows + cols:
                if not isinstance(candidate, dict):
                    continue
                extracted = extract_field_with_entity(candidate)
                if extracted and extracted.get("Entity") not in {None, "Table1"}:
                    entity = extracted["Entity"]
                    break
            return build_measure_projection(
                {
                    "Property": calc_info.get("Property"),
                    "Entity": entity,
                    "Derivation": deriv,
                    "LocalType": "real",
                }
            )

    normalized = normalize_extracted_field(field, rows, cols, encodings)
    if not normalized:
        return None

    deriv = str(normalized.get("Derivation") or "").lower()
    if deriv in {"countd"}:
        return build_measure_reference_from_calc(
            {"Derivation": "countd", "Property": normalized["Property"]}
        )

    local_type = str(normalized.get("LocalType", "")).lower()
    if (
        deriv in {"sum", "avg", "average", "count", "min", "max", "median"}
        or local_type in {"real", "integer", "numeric"}
    ):
        return build_measure_projection(normalized)

    return None


def _collect_measure_name_fields(ws, rows, cols, encodings):
    """Gather measure field dicts from measure_names, slices, and expanded rows."""
    fields = []
    seen = set()

    def add_field(field):
        if not isinstance(field, dict):
            return
        key = field.get("name") or field.get("column") or field.get("local-name")
        if not key or key in seen:
            return
        seen.add(key)
        fields.append(field)

    for member in ws.get("measure_names") or []:
        add_field(member if isinstance(member, dict) else {"name": member})

    for slc in ws.get("slices") or []:
        if isinstance(slc, dict):
            add_field(slc)

    for row in rows:
        if isinstance(row, dict) and not _is_multiple_values_placeholder(row):
            add_field(row)

    return fields


def _resolve_measure_names_multi_projections(ws, workbook, category, rows, cols, encodings):
    """
  Build Y projections for Tableau Measure Names / Multiple Values line charts.
  Prefer explicit measure_names on the sheet, then slices/rows, then other worksheets.
    """
    projections = []
    seen_refs = set()

    def add_projection(proj):
        if not proj:
            return
        ref = proj.get("queryRef")
        if ref and ref not in seen_refs:
            seen_refs.add(ref)
            projections.append(proj)

    for field in _collect_measure_name_fields(ws, rows, cols, encodings):
        add_projection(_field_dict_to_projection(field, rows, cols, encodings))

    # Only scan other worksheets when this sheet has no explicit measure list.
    if workbook and len(projections) < 2:
        found_measures, found_calcs = _find_measures_from_matching_worksheets(
            category, workbook
        )
        for m in found_measures:
            add_projection(build_measure_projection(m))
        for calc_field in found_calcs:
            calc_info = parse_tableau_calc_formula(
                calc_field.get("formula")
                or calc_field.get("name_calc")
                or calc_field.get("name")
                or ""
            )
            if calc_info:
                add_projection(build_measure_reference_from_calc(calc_info))

        if len(projections) < 2:
            wb_calc = _find_countd_calc_in_workbook(workbook)
            if wb_calc:
                add_projection(build_measure_reference_from_calc(wb_calc))

    return projections


LINE_MEASURE_COLORS = ("#0CA430", "#03901A", "#118DFF", "#E66C37")


def _is_measure_like_field(f):
    if not isinstance(f, dict):
        return False
    name = str(f.get("name", "")).lower()
    if any(tok in name for tok in ("sum:", "avg:", "cnt:", "cntd:", "ctd:", "usr:")):
        return True
    local_type = str(f.get("local-type", "")).lower()
    deriv = str(f.get("derivation", "")).lower()
    if deriv in {"sum", "avg", "average", "count", "countd", "cnt", "min", "max", "median"}:
        return True
    if local_type in {"real", "integer", "numeric"}:
        return True
    if deriv in {"user", "none"} and parse_tableau_calc_formula(
        f.get("formula") or f.get("name_calc") or f.get("name") or ""
    ):
        return True
    return False


def _is_date_like_field(f):
    if not isinstance(f, dict):
        return False
    local_type = str(f.get("local-type", "")).lower()
    deriv = str(f.get("derivation", "")).lower()
    return (
        local_type == "date"
        or deriv in {"year", "quarter", "month", "week", "day"}
        or "month" in deriv
    )


def _expand_axis_fields(fields):
    """Split Tableau combined shelf expressions like '[sum:Sales:qk] + [sum:Profit:qk]'."""
    expanded = []
    for fld in fields or []:
        if not isinstance(fld, dict):
            continue
        name = str(fld.get("name") or "")
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


def _has_measure_names_color(encodings):
    color = encodings.get("color") if isinstance(encodings, dict) else None
    if isinstance(color, dict):
        return color.get("name") == "[:Measure Names]"
    if isinstance(color, list):
        return any(
            isinstance(c, dict) and c.get("name") == "[:Measure Names]" for c in color
        )
    return False


def _is_multi_measure_rows_line(ws, rows, cols, encodings):
    """Multiple measures on rows (e.g. Sales + Profit) with a date axis on columns."""
    if _is_measure_names_multi_line(ws) or _is_year_split_countd_line(ws, rows, cols, encodings):
        return False
    row_measures = [f for f in rows if isinstance(f, dict) and _is_measure_like_field(f)]
    col_dates = [f for f in cols if isinstance(f, dict) and _is_date_like_field(f)]
    return len(row_measures) >= 2 and bool(col_dates)


def _is_countd_multi_date_columns(ws, rows, cols, encodings):
    """COUNTD on rows with multiple date levels on columns (Year + Month), not year-split."""
    if _is_year_split_countd_line(ws, rows, cols, encodings):
        return False
    row_measures = [f for f in rows if isinstance(f, dict) and _is_measure_like_field(f)]
    row_dims = [
        f
        for f in rows
        if isinstance(f, dict)
        and not _is_measure_like_field(f)
        and extract_field_with_entity(f)
    ]
    col_dates = [f for f in cols if isinstance(f, dict) and _is_date_like_field(f)]
    if len(row_measures) != 1 or row_dims or len(col_dates) < 2:
        return False
    calc_info = parse_tableau_calc_formula(
        row_measures[0].get("formula")
        or row_measures[0].get("name_calc")
        or row_measures[0].get("name")
        or ""
    )
    return bool(calc_info) and str(calc_info.get("Derivation", "")).lower() in {
        "countd",
        "count",
        "cnt",
    }


def _resolve_row_multi_measure_projections(rows, cols, encodings):
    projections = []
    seen = set()
    for fld in rows:
        if not isinstance(fld, dict) or not _is_measure_like_field(fld):
            continue
        proj = _field_dict_to_projection(fld, rows, cols, encodings)
        if proj and proj.get("queryRef") not in seen:
            seen.add(proj["queryRef"])
            projections.append(proj)
    return projections


def _is_year_split_countd_line(ws, rows, cols, encodings):
    """
    Sheet 6 pattern:
    - measure (COUNTD calc) on rows
    - Month on cols
    - Year on color
  Produces per-year measures on Y (Distinct 2024 / Distinct 2025), Month_ on Category.
    """
    row_measures = [f for f in rows if isinstance(f, dict) and _is_measure_like_field(f)]
    row_dims = [
        f
        for f in rows
        if isinstance(f, dict)
        and not _is_measure_like_field(f)
        and extract_field_with_entity(f)
    ]
    col_months = [
        f
        for f in cols
        if isinstance(f, dict)
        and _is_date_like_field(f)
        and str(f.get("derivation", "")).lower().startswith("month")
    ]
    col_years = [
        f
        for f in cols
        if isinstance(f, dict)
        and _is_date_like_field(f)
        and str(f.get("derivation", "")).lower() == "year"
    ]
    color_enc = encodings.get("color") if isinstance(encodings, dict) else None
    color_field = (
        normalize_extracted_field(color_enc, rows, cols, encodings)
        if isinstance(color_enc, dict)
        else None
    )

    if not row_measures or row_dims or not col_months or col_years:
        return False
    if not color_field or str(color_field.get("Derivation", "")).lower() != "year":
        return False
    if not (_extract_year_filter_members(ws, encodings, rows, cols) or ws.get("filters")):
        return False

    calc_info = parse_tableau_calc_formula(
        row_measures[0].get("formula")
        or row_measures[0].get("name_calc")
        or row_measures[0].get("name")
        or ""
    )
    return bool(calc_info) and str(calc_info.get("Derivation", "")).lower() in {
        "countd",
        "count",
        "cnt",
    }


def _extract_year_filter_members(ws, encodings, rows, cols):
    """Read year member values (e.g. 2024, 2025) from worksheet filters."""
    years = []
    for filt in ws.get("filters") or []:
        field = filt.get("field") if isinstance(filt, dict) else None
        if isinstance(field, dict):
            deriv = str(field.get("derivation", "")).lower()
            col = str(field.get("column", "")).lower()
            name = str(field.get("name", "")).lower()
            is_year = deriv == "year" or ":yr:" in name or "year" in col
        else:
            col_raw = str(filt.get("column", "")).lower()
            is_year = ":yr:" in col_raw or "year" in col_raw

        if is_year:
            for member in filt.get("members") or []:
                if member and str(member) not in years:
                    years.append(str(member))

    if not years:
        color_enc = encodings.get("color") if isinstance(encodings, dict) else None
        if isinstance(color_enc, dict):
            for key in ("members", "filter_members", "values"):
                for member in color_enc.get(key) or []:
                    if member and str(member) not in years:
                        years.append(str(member))

    return years


def _build_month_column_category(entity):
    return {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": "Month_",
            }
        },
        "queryRef": f"{entity}.Month_",
        "nativeQueryRef": "Count of Month_",
        "active": True,
    }


def _build_year_split_measure_projection(year_value):
    measure_name = f"Distinct {year_value}"
    return {
        "field": {
            "Measure": {
                "Expression": {"SourceRef": {"Entity": "_Measures"}},
                "Property": measure_name,
            }
        },
        "queryRef": f"_Measures.{measure_name}",
        "nativeQueryRef": str(year_value),
        "displayName": str(year_value),
    }


def _build_year_categorical_filter(entity, years):
    return {
        "name": uuid.uuid4().hex[:20],
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": "Year_",
            }
        },
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "o", "Entity": entity, "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "In": {
                            "Expressions": [
                                {
                                    "Column": {
                                        "Expression": {
                                            "SourceRef": {"Source": "o"}
                                        },
                                        "Property": "Year_",
                                    }
                                }
                            ],
                            "Values": [
                                [{"Literal": {"Value": f"{y}L"}}] for y in years
                            ],
                        }
                    }
                }
            ],
        },
        "howCreated": "User",
        "objects": {"general": [{"properties": {}}]},
    }


def _build_year_split_visual_objects(y_refs):
    """Build labels/lineStyles/dataPoint objects for year-split line charts."""
    objects = {
        "labels": [
            {
                "properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "fontSize": {"expr": {"Literal": {"Value": "11D"}}},
                }
            }
        ],
        "lineStyles": [
            {
                "properties": {
                    "showMarker": {"expr": {"Literal": {"Value": "false"}}},
                }
            }
        ],
        "dataPoint": [],
    }

    if len(y_refs) >= 1:
        objects["lineStyles"].insert(
            0,
            {
                "properties": {
                    "strokeWidth": {"expr": {"Literal": {"Value": "5D"}}},
                    "showMarker": {"expr": {"Literal": {"Value": "true"}}},
                    "markerColor": {
                        "solid": {
                            "color": {
                                "expr": {
                                    "ThemeDataColor": {
                                        "ColorId": 8,
                                        "Percent": 0.2,
                                    }
                                }
                            }
                        }
                    },
                },
                "selector": {"metadata": y_refs[0]},
            },
        )
        objects["dataPoint"].append(
            {
                "properties": {
                    "fill": {
                        "solid": {
                            "color": {
                                "expr": {
                                    "ThemeDataColor": {
                                        "ColorId": 8,
                                        "Percent": 0.2,
                                    }
                                }
                            }
                        }
                    }
                },
                "selector": {"metadata": y_refs[0]},
            }
        )

    if len(y_refs) >= 2:
        green = "'#03901A'"
        objects["lineStyles"].append(
            {
                "properties": {
                    "showMarker": {"expr": {"Literal": {"Value": "true"}}},
                    "markerColor": {
                        "solid": {
                            "color": {
                                "expr": {"Literal": {"Value": green}}
                            }
                        }
                    },
                },
                "selector": {"metadata": y_refs[1]},
            }
        )
        objects["dataPoint"].append(
            {
                "properties": {
                    "fill": {
                        "solid": {
                            "color": {
                                "expr": {"Literal": {"Value": green}}
                            }
                        }
                    }
                },
                "selector": {"metadata": y_refs[1]},
            }
        )

    return objects


def build_line_chart_for_worksheet(ws, workbook=None):
    visual_id = uuid.uuid4().hex[:20]

    rows = _expand_axis_fields(ws.get("rows", []))
    cols = _expand_axis_fields(ws.get("cols", []))
    encodings = ws.get("encodings") or ws.get("table", {}).get("encodings") or {}

    # -----------------------------------------------------
    # CATEGORY DETECTION
    # -----------------------------------------------------
    # Special Tableau pattern we need to preserve (Sheet 4 style):
    # rows:   dimension (e.g., Region) + COUNTD calc
    # cols:   date level (e.g., Order Date Month)
    # color:  same dimension (Region)
    #
    # Expected Power BI structure for this project:
    # Category contains BOTH (dimension, date level) and Y contains the COUNTD measure.
    year_split_multi = _is_year_split_countd_line(ws, rows, cols, encodings)

    row_dims = [
        f
        for f in rows
        if isinstance(f, dict)
        and not _is_measure_like_field(f)
        and extract_field_with_entity(f)
    ]
    col_dates = [
        f
        for f in cols
        if isinstance(f, dict)
        and _is_date_like_field(f)
        and extract_field_with_entity(f)
    ]
    multi_category_dim_date = bool(row_dims) and bool(col_dates)

    # Default category detection (first valid field in cols+rows)
    category_field = None
    if not multi_category_dim_date:
        for fld in cols + rows:
            if not isinstance(fld, dict):
                continue
            if extract_field_with_entity(fld):
                category_field = fld
                break
    else:
        # Prefer date as primary category for downstream defaults, but we'll build
        # a 2-field Category projection list (dimension + date) below.
        category_field = col_dates[0]

    if not category_field:
        category_field = get_encoding(encodings, "path") or get_encoding(encodings, "detail") or get_encoding(encodings, "label") or get_encoding(encodings, "color")

    category = normalize_extracted_field(category_field, rows, cols, encodings) if category_field else None
    if not category:
        raise ValueError("Line chart category field not found.")

    # Multi-measure line charts: rows=[Multiple Values] AND color=[:Measure Names]
    measure_names_multi = _is_measure_names_multi_line(ws)
    multi_measure_rows = _is_multi_measure_rows_line(ws, rows, cols, encodings)
    countd_multi_date_cols = _is_countd_multi_date_columns(ws, rows, cols, encodings)

    # Build category projections.
    # If we have BOTH a dimension on rows and a date level on cols, include BOTH in Category.
    if year_split_multi:
        entity = category.get("Entity", "Orders")
        category_projections = [_build_month_column_category(entity)]
    elif countd_multi_date_cols:
        category_projections = []
        for date_fld in col_dates:
            date_norm = normalize_extracted_field(date_fld, rows, cols, encodings)
            if date_norm:
                category_projections.extend(build_category_projections(date_norm))
        if not category_projections:
            category_projections = build_category_projections(category)
    elif multi_category_dim_date and not measure_names_multi:
        dim = normalize_extracted_field(row_dims[0], rows, cols, encodings)
        date = normalize_extracted_field(col_dates[0], rows, cols, encodings)
        if dim and date:
            category_projections = build_category_projections(dim) + build_category_projections(date)
        else:
            category_projections = build_category_projections(category)
    else:
        category_projections = build_category_projections(category)

    if measure_names_multi:
        # if category is a Month derivation, use Column Month_ instead of HierarchyLevel
        if str(category.get('Derivation','')).lower().startswith('month'):
            category_projections = [{
                "field": {"Column": {"Expression": {"SourceRef": {"Entity": category["Entity"]}}, "Property": "Month_"}},
                "queryRef": f"{category['Entity']}.Month_",
                "nativeQueryRef": "Month_",
                "active": True,
            }]

    measure_projections = []
    calc_measure_projection = None
    measure = None
    year_split_years = []

    if year_split_multi:
        year_split_years = _extract_year_filter_members(ws, encodings, rows, cols)
        if not year_split_years:
            year_split_years = ["2024", "2025"]
        measure_projections = [
            _build_year_split_measure_projection(y) for y in year_split_years
        ]
        measure = {"Entity": category.get("Entity", "Orders"), "Property": "Customer", "Derivation": "countd"}
    elif multi_measure_rows:
        measure_projections = _resolve_row_multi_measure_projections(rows, cols, encodings)
        if measure_projections:
            measure = normalize_extracted_field(
                [f for f in rows if _is_measure_like_field(f)][0], rows, cols, encodings
            )
        if not measure_projections:
            measure = {
                "Property": category["Property"],
                "Entity": category["Entity"],
                "Derivation": "Count",
                "LocalType": "integer",
            }
            measure_projections.append(build_measure_projection(measure))
    elif countd_multi_date_cols:
        row_measure = [f for f in rows if _is_measure_like_field(f)][0]
        calc_info = parse_tableau_calc_formula(
            row_measure.get("formula")
            or row_measure.get("name_calc")
            or row_measure.get("name")
            or ""
        )
        measure_projections = [build_measure_reference_from_calc(calc_info)]
        measure = {
            "Entity": category.get("Entity", "Orders"),
            "Property": calc_info.get("Property", "Customer"),
            "Derivation": calc_info.get("Derivation"),
        }
    elif measure_names_multi:
        measure_projections = _resolve_measure_names_multi_projections(
            ws, workbook, category, rows, cols, encodings
        )
        measure_name_fields = _collect_measure_name_fields(ws, rows, cols, encodings)
        if measure_projections:
            if measure_name_fields:
                measure = normalize_extracted_field(
                    measure_name_fields[0], rows, cols, encodings
                )
            if not measure:
                measure = {
                    "Property": "Sales",
                    "Entity": category["Entity"],
                    "Derivation": "Sum",
                    "LocalType": "real",
                }
        else:
            measure = {
                "Property": category["Property"],
                "Entity": category["Entity"],
                "Derivation": "Count",
                "LocalType": "integer",
            }
            measure_projections.append(build_measure_projection(measure))
    else:
        # standard single measure detection
        measure_field = None
        for fld in rows + cols:
            if isinstance(fld, dict) and _is_measure_like_field(fld):
                measure_field = fld
                break

        if not measure_field and encodings:
            for val in encodings.values():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and _is_measure_like_field(item):
                            measure_field = item
                            break
                    if measure_field:
                        break
                elif isinstance(val, dict) and _is_measure_like_field(val):
                    measure_field = val
                    break

        if not measure_field:
            measure_field = get_encoding(encodings, "size")

        # If the chosen measure is a COUNTD calc (e.g., COUNTD([Customer ID])),
        # represent it as a model measure (expected output uses _Measures.Distinct Customer).
        calc_info_for_measure = _parse_calc_info_from_field(measure_field)
        if _is_countd_style_calc(calc_info_for_measure):
            measure_projections.append(build_measure_reference_from_calc(calc_info_for_measure))
            measure = {
                "Entity": category["Entity"],
                "Property": calc_info_for_measure.get("Property", "Customer"),
                "Derivation": calc_info_for_measure.get("Derivation"),
                "LocalType": "",
            }
        else:
            measure = normalize_extracted_field(measure_field, rows, cols, encodings) if measure_field else None
            if not measure:
                measure = {"Property": category["Property"], "Entity": category["Entity"], "Derivation": "Count", "LocalType": "integer"}
            measure_projections.append(build_measure_projection(measure))

        # Secondary axis: COUNTD / _Measures from Text/Color/Label (e.g. Sales on rows + Distinct Customer on text)
        calc_measure_projection = _find_secondary_measures_calc_projection(
            encodings, measure_projections
        )

        if not calc_measure_projection and workbook:
            wb_calc = _find_countd_calc_in_workbook(workbook)
            if wb_calc:
                wb_proj = build_measure_reference_from_calc(wb_calc)
                if wb_proj and wb_proj.get("queryRef") not in _projection_query_refs(
                    measure_projections
                ):
                    calc_measure_projection = wb_proj

    query_state = {
        "Category": {"projections": category_projections},
        "Y": {"projections": measure_projections},
    }

    if year_split_multi:
        query_state["Series"] = {"projections": []}

    if (
        calc_measure_projection
        and calc_measure_projection.get("queryRef")
        not in _projection_query_refs(measure_projections)
        and not measure_names_multi
        and not year_split_multi
        and not multi_measure_rows
        and not countd_multi_date_cols
    ):
        query_state["Y2"] = {"projections": [calc_measure_projection]}

    # build base JSON
    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
        "name": visual_id,
        "position": {
            "x": random.uniform(50, 150),
            "y": random.uniform(50, 150),
            "z": 0,
            "height": random.uniform(250, 450),
            "width": random.uniform(450, 900),
            "tabOrder": 0,
        },
        "visual": {
            "visualType": "lineChart",
            "query": {
                "queryState": query_state,
            },
            "objects": {},
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": {"filters": []},
    }

    # Always sort chronologically by category projections for line charts
    if category_projections and not year_split_multi:
        powerbi_json["visual"]["query"]["sortDefinition"] = {
            "sort": [{"field": proj["field"], "direction": "Ascending"} for proj in category_projections]
        }

    # Set up objects dynamically
    if year_split_multi and measure_projections:
        y_measure_refs = [p["queryRef"] for p in measure_projections if p.get("queryRef")]
    elif measure_names_multi and measure_projections:
        y_measure_refs = [p["queryRef"] for p in measure_projections if p.get("queryRef")]
    else:
        y_measure_refs = []
        if measure_projections:
            y_measure_refs.append(measure_projections[0]["queryRef"])
        y2_projs = query_state.get("Y2", {}).get("projections") or []
        if y2_projs:
            y_measure_refs.append(y2_projs[0]["queryRef"])

    y_measure_name = y_measure_refs[0] if y_measure_refs else None
    y2_measure_name = y_measure_refs[1] if len(y_measure_refs) > 1 else None

    if year_split_multi:
        y_refs = y_measure_refs or []
        powerbi_json["visual"]["objects"] = _build_year_split_visual_objects(y_refs)
        powerbi_json["visualContainerObjects"] = {
            "border": [
                {
                    "properties": {
                        "show": {"expr": {"Literal": {"Value": "true"}}},
                    }
                }
            ]
        }
        filter_list = []
        if category_projections:
            filter_list.append(
                {
                    "name": uuid.uuid4().hex[:20],
                    "field": category_projections[0]["field"],
                    "type": "Categorical",
                }
            )
        if year_split_years:
            filter_list.append(
                _build_year_categorical_filter(
                    category.get("Entity", "Orders"), year_split_years
                )
            )
        powerbi_json["filterConfig"] = {"filters": filter_list}
        return powerbi_json

    objects = {
        "legend": [
            {
                "properties": {
                    "show": {
                        "expr": {
                            "Literal": {
                                "Value": "false"
                            }
                        }
                    }
                }
            }
        ],
        "categoryAxis": [
            {
                "properties": {
                    "fontSize": {
                        "expr": {
                            "Literal": {
                                "Value": "12D"
                            }
                        }
                    }
                }
            }
        ],
        "valueAxis": [
            {
                "properties": {
                    "show": {
                        "expr": {
                            "Literal": {
                                "Value": "true"
                            }
                        }
                    }
                }
            }
        ],
    }

    # lineStyles
    line_styles = []
    if y_measure_name:
        line_styles.append({
            "properties": {
                "showMarker": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y_measure_name
            }
        })
    if y2_measure_name:
        line_styles.append({
            "properties": {
                "showMarker": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y2_measure_name
            }
        })
    line_styles.append({
        "properties": {
            "areaShow": {
                "expr": {
                    "Literal": {
                        "Value": "false"
                    }
                }
            }
        }
    })
    objects["lineStyles"] = line_styles

    # markers
    markers = []
    if y_measure_name:
        markers.append({
            "properties": {
                "transparency": {
                    "expr": {
                        "Literal": {
                            "Value": "0D"
                        }
                    }
                },
                "borderShow": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y_measure_name
            }
        })
    if y2_measure_name:
        markers.append({
            "properties": {
                "borderShow": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y2_measure_name
            }
        })
    objects["markers"] = markers

    # labels
    labels = [
        {
            "properties": {
                "show": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                },
                "labelDisplayUnits": {
                    "expr": {
                        "Literal": {
                            "Value": "1000D"
                        }
                    }
                }
            }
        }
    ]
    if y_measure_name:
        labels.append({
            "properties": {
                "labelPrecision": {
                    "expr": {
                        "Literal": {
                            "Value": "0L"
                        }
                    }
                },
                "fontSize": {
                    "expr": {
                        "Literal": {
                            "Value": "11D"
                        }
                    }
                },
                "enableBackground": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y_measure_name
            }
        })
    if y2_measure_name:
        labels.append({
            "properties": {
                "fontSize": {
                    "expr": {
                        "Literal": {
                            "Value": "11D"
                        }
                    }
                },
                "labelDisplayUnits": {
                    "expr": {
                        "Literal": {
                            "Value": "1D"
                        }
                    }
                },
                "enableBackground": {
                    "expr": {
                        "Literal": {
                            "Value": "true"
                        }
                    }
                }
            },
            "selector": {
                "metadata": y2_measure_name
            }
        })
    objects["labels"] = labels

    # dataPoint
    data_points = []
    if y_measure_name:
        data_points.append({
            "properties": {
                "fill": {
                    "solid": {
                        "color": {
                            "expr": {
                                "Literal": {
                                    "Value": "'#0CA430'"
                                }
                            }
                        }
                    }
                }
            },
            "selector": {
                "metadata": y_measure_name
            }
        })
    if y2_measure_name:
        data_points.append({
            "properties": {
                "fill": {
                    "solid": {
                        "color": {
                            "expr": {
                                "Literal": {
                                    "Value": "'#03901A'"
                                }
                            }
                        }
                    }
                }
            },
            "selector": {
                "metadata": y2_measure_name
            }
        })
    if data_points:
        objects["dataPoint"] = data_points

    powerbi_json["visual"]["objects"] = objects

    # visualContainerObjects
    powerbi_json["visualContainerObjects"] = {
        "border": [
            {
                "properties": {
                    "show": {
                        "expr": {
                            "Literal": {
                                "Value": "true"
                            }
                        }
                    }
                }
            }
        ]
    }

    # series projection if present
    possible_series = get_encoding(encodings, "color")
    series = None
    # If we already included a row dimension in Category (Region + Month pattern),
    # don't also create Series from color (it would duplicate Region).
    if (
        isinstance(possible_series, dict)
        and not measure_names_multi
        and not multi_category_dim_date
        and not year_split_multi
        and not multi_measure_rows
        and not countd_multi_date_cols
        and not _has_measure_names_color(encodings)
    ):
        if not parse_tableau_calc_formula(possible_series.get("formula") or possible_series.get("name_calc") or possible_series.get("name") or ""):
            local_type = str(possible_series.get("local-type", "")).lower()
            deriv = str(possible_series.get("derivation", "")).lower()
            is_series_measure = deriv in {"sum", "avg", "average", "count", "min", "max", "median"} or local_type in {"real", "integer", "numeric"}
            if not is_series_measure:
                series = normalize_extracted_field(possible_series, rows, cols, encodings)

    if series and series.get("Property"):
        series_proj = {"field": {"Column": {"Expression": {"SourceRef": {"Entity": series["Entity"]}}, "Property": series["Property"]}}, "queryRef": f"{series['Entity']}.{series['Property']}", "nativeQueryRef": series["Property"]}
        powerbi_json["visual"]["query"]["queryState"]["Series"] = {"projections": [series_proj]}

    # filters
    filters = []
    if category_projections:
        filters.append({"name": uuid.uuid4().hex[:20], "field": category_projections[0]["field"], "type": "Categorical"})
    if measure_projections:
        filters.append({"name": uuid.uuid4().hex[:20], "field": measure_projections[0]["field"], "type": "Advanced"})
    y2_state = query_state.get("Y2", {}).get("projections") or []
    if y2_state:
        filters.append(
            {"name": uuid.uuid4().hex[:20], "field": y2_state[0]["field"], "type": "Advanced"}
        )
    if series and series.get("Property"):
        filters.append({"name": uuid.uuid4().hex[:20], "field": series_proj["field"], "type": "Categorical"})

    powerbi_json["filterConfig"] = {"filters": filters}

    return powerbi_json

def convert_line_chart_dynamic(tableau_json):
    worksheets = tableau_json.get("worksheets", [tableau_json])
    workbook = tableau_json.get("workbook") or tableau_json
    visuals = []
    for ws in worksheets:
        visuals.append(build_line_chart_for_worksheet(ws, workbook=workbook))
    return visuals[0] if len(visuals) == 1 else visuals

convert_line_chart_dynamic_2T = convert_line_chart_dynamic
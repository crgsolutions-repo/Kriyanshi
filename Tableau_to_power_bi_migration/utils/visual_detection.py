import os
import sys
import logging
import random
import string

# Import Tableau_Parser
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# === Imports ===
from Visuals.bar import convert_tableau_bar_to_powerbi
from Visuals.pie import convert_tableau_to_powerbi
from Visuals.line import convert_line_chart_dynamic
from Visuals.pivot import convert_tableau_pivot_to_powerbi
from Visuals.StackedBar import convert_tableau_to_powerbi_stacked_bar_2T
from Visuals.table import convert_tableau_to_powerbi_table
from Visuals.scatter import convert_scatter_chart_dynamic
from Visuals.donut import convert_tableau_to_powerbi_donut
from Visuals.area import convert_area_chart
from Visuals.heatmap import convert_tableau_heatmap_to_powerbi
from Visuals.treemap import convert_tableau_treemap_to_powerbi
from Visuals.combo_chart_bar_line import convert_tableau_to_powerbi_CC
from Visuals.dual_axis import convert_tableau_to_powerbi_dual_axis
from Visuals.funnel_chart import convert_tableau_funnel_to_powerbi
from Visuals.combo_line_area import convert_tableau_to_powerbi_CCLA
from Visuals.combo_bar_area import convert_tableau_to_powerbi_CCBA
from Visuals.waterfall import convert_tableau_to_powerbi_waterfall
from Visuals.KPI_card import convert_kpi_to_powerbi_json
from Visuals.multicard import convert_tableau_to_powerbi_multirow

logging.basicConfig(level=logging.INFO)


# ======== Utility ========
def generate_random_id(length: int = 20) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


# ======== Visual Type Mapping ========
keywords_mapping = {
    "bar": "bar chart",
    "stacked": "stacked bar chart",
    "line": "line chart",
    "text": "highlighted table",
    "square": "heatmap",
    "table": "table",
    "shape": "scatter chart",
    "pie": "pie chart",
    "donut": "donut chart",
    "area": "area chart",
    "tree map": "tree map",
    "dual axis": "dual axis chart",
    "combo": "combo chart",
    "combo bar line": "combo chart (bar and line)",
    "funnel": "funnel chart",
    "combo line area": "combo chart (line and area)",
    "combo bar area": "combo chart (bar and area)",
    "waterfall": "waterfall chart",
    "KPI Card": "kpi card",
    "multiRowCard": "multirow card",
}

converters = {
    "bar chart": convert_tableau_bar_to_powerbi,
    "stacked bar chart": convert_tableau_to_powerbi_stacked_bar_2T,
    "line chart": convert_line_chart_dynamic,
    "highlighted table": convert_tableau_pivot_to_powerbi,
    "heatmap": convert_tableau_heatmap_to_powerbi,
    "table": convert_tableau_to_powerbi_table,
    "scatter chart": convert_scatter_chart_dynamic,
    "pie chart": convert_tableau_to_powerbi,
    "donut chart": convert_tableau_to_powerbi_donut,
    "area chart": convert_area_chart,
    "tree map": convert_tableau_treemap_to_powerbi,
    "dual axis chart": convert_tableau_to_powerbi_dual_axis,
    "combo chart": convert_tableau_to_powerbi_CC,
    "combo chart (bar and line)": convert_tableau_to_powerbi_CC,
    "funnel chart": convert_tableau_funnel_to_powerbi,
    "combo chart (line and area)": convert_tableau_to_powerbi_CCLA,
    "combo chart (bar and area)": convert_tableau_to_powerbi_CCBA,
    "waterfall chart": convert_tableau_to_powerbi_waterfall,
    "kpi card": convert_kpi_to_powerbi_json,
    "multirow card": convert_tableau_to_powerbi_multirow,
}


# ======== Dynamic Visual Detection (with match-case) ========
def resolve_effective_mark_type(marks_list):
    """
    Tableau dual-axis / multi-pane worksheets often list marks like
    ['Automatic', 'Line', 'Circle']. Use the most specific mark, not only marks[0].
    """
    if not marks_list or not isinstance(marks_list, list):
        return ""

    normalized = [str(m).strip().lower() for m in marks_list if m]

    # Combo / dual-axis combinations (multi-pane)
    if "line" in normalized and "circle" in normalized:
        return "dual_axis_line_circle"
    if "line" in normalized and "area" in normalized:
        return "automatic line area"
    if "bar" in normalized and "line" in normalized:
        return "automatic bar line"

    priority = ("line", "area", "bar", "square", "circle", "pie", "shape", "text", "automatic")
    for mark in priority:
        if mark in normalized:
            return mark

    return normalized[0] if normalized else ""


def _has_date_on_axes(rows, cols):
    date_derivations = {
        "year",
        "quarter",
        "month",
        "day",
        "week",
        "month-trunc",
        "month_trunc",
    }
    for fld in rows + cols:
        if not isinstance(fld, dict):
            continue
        deriv = str(fld.get("derivation", "")).lower()
        local_type = str(fld.get("local-type", "")).lower()
        if deriv in date_derivations or local_type == "date":
            return True
    return False


def _expand_combined_axis_fields(fields):
    expanded = []
    for fld in fields or []:
        if not isinstance(fld, dict):
            continue
        name = str(fld.get("name") or "")
        if "+" in name and not fld.get("column"):
            import re

            for part in re.split(r"\s*\+\s*", name):
                if part.strip():
                    expanded.append({"name": part.strip()})
        else:
            expanded.append(fld)
    return expanded


def _field_looks_like_measure(fld):
    if not isinstance(fld, dict):
        return False
    name = str(fld.get("name", "")).lower()
    deriv = str(fld.get("derivation", "")).lower()
    local_type = str(fld.get("local-type", "")).lower()
    if any(tok in name for tok in ("sum:", "avg:", "cnt:", "cntd:", "ctd:", "usr:")):
        return True
    if deriv in {"sum", "avg", "average", "count", "countd", "cnt", "user"}:
        return True
    if local_type in {"real", "integer", "numeric"}:
        return True
    if fld.get("formula"):
        return True
    return False


def _looks_like_line_chart_structure(rows, cols):
    """Detect line-chart layout even when Tableau marks are Automatic / Area."""
    rows_x = _expand_combined_axis_fields(rows)
    measures_on_rows = sum(1 for f in rows_x if _field_looks_like_measure(f))
    if measures_on_rows >= 1 and _has_date_on_axes(rows, cols):
        return True
    measures_on_cols = sum(1 for f in cols if _field_looks_like_measure(f))
    dims_on_rows = sum(
        1
        for f in rows_x
        if isinstance(f, dict) and not _field_looks_like_measure(f) and f.get("column")
    )
    if measures_on_cols >= 1 and (_has_date_on_axes(rows, cols) or dims_on_rows >= 1):
        return True
    return False


def detect_visual_type(worksheet):
    ws_name = (worksheet.get("worksheet") or "").strip().lower()
    ws_title = (worksheet.get("title") or "").strip().lower()
    encodings = worksheet.get("encodings", {})
    filters = worksheet.get("filters", [])
    rows = worksheet.get("rows", [])
    cols = worksheet.get("cols", [])
    marks = worksheet.get("marks", [])

    marks_list = worksheet.get("marks", [])
    mark_type = resolve_effective_mark_type(marks_list)
    if marks_list and isinstance(marks_list, list):
        normalized_marks = " ".join(m.lower() for m in marks_list if isinstance(m, str))
    else:
        normalized_marks = mark_type

    logging.debug(
        f"[detect_visual_type] ws_name={ws_name}, ws_title={ws_title}, "
        f"mark_type={mark_type}, raw_marks={marks_list}, "
        f"encodings={list(encodings.keys())}, filters={len(filters)}"
    )

    # Helper to check if any field is a measure
    def is_measure(f):
        if not isinstance(f, dict):
            return False

        loc_type = str(f.get("local-type", "")).lower()
        name = str(f.get("name", "")).lower()

        return loc_type in ["real", "integer"] or any(agg in name for agg in ["sum:", "avg:", "min:", "max:", "cnt:", "cntd:"])

    all_fields = []
    all_fields.extend(rows)
    all_fields.extend(cols)
    for val in encodings.values():
        if isinstance(val, list):
            all_fields.extend(val)
        elif isinstance(val, dict):
            all_fields.append(val)

    has_measure_on_axes = any(is_measure(f) for f in rows + cols)
    has_measure_anywhere = any(is_measure(f) for f in all_fields)

    # Priority check for explicit user-defined chart types in the title/name
    for key, vtype in keywords_mapping.items():
        if key.lower() in ws_title or key.lower() in ws_name:
            logging.info(f"[detect_visual_type] Keyword '{key}' matched in title/name. Returning {vtype}.")
            return vtype

    # Pre-checks before match
    if "pie" in normalized_marks and "circle" in normalized_marks:
        return "donut chart"
    if "dual axis" in ws_name or "dual axis" in ws_title:
        return "dual axis chart"
    if mark_type == "dual_axis_line_circle":
        return "dual axis chart"

    # Line-like worksheets even when marks say Automatic / Area (common in TWB exports)
    if _looks_like_line_chart_structure(rows, cols) and mark_type in {
        "automatic",
        "area",
        "",
    }:
        return "line chart"

    # Modern switch-style logic
    match mark_type:
        case "area":
            if _looks_like_line_chart_structure(rows, cols):
                return "line chart"
            return "area chart"
        case "pie":
            return "pie chart"
        case "line":
            return "line chart"
        case "bar":
            if "funnel" in ws_name or "funnel" in ws_title:
                return "funnel chart"
            return "bar chart"
        case "square":
            if not rows and not cols:
                return "tree map"
            return "heatmap"
        case "text":

    
            # =====================================================
            # MULTIROW CARD
            # =====================================================

            text_encoding = encodings.get("text", [])

            if (
                not rows
                and len(cols) == 1
                and isinstance(text_encoding, list)
                and len(text_encoding) > 1
            ):

                logging.info(
                    f"[detect_visual_type] "
                    f"Detected Multirow Card for '{ws_name}'"
                )

                return "multirow card"

            # =====================================================
            # KPI CARD
            # =====================================================

            text_encoding_name = ""

            if isinstance(encodings, dict):

                text_encoding_obj = encodings.get("text", {})

                if isinstance(text_encoding_obj, dict):

                    text_encoding_name = (
                        text_encoding_obj.get("name") or ""
                    ).strip()

            if (
                not rows
                and mark_type == "text"
                and text_encoding_name == "[:Measure Names]"
            ):

                logging.info(
                    f"[detect_visual_type] "
                    f"Detected KPI Card for '{ws_name}'"
                )

                return "KPI card"

            # =====================================================
            # COUNT DIMENSIONS + MEASURES
            # =====================================================

            all_fields = []

            all_fields.extend(rows)
            all_fields.extend(cols)

            for val in encodings.values():

                if isinstance(val, list):
                    all_fields.extend(val)

                elif isinstance(val, dict):
                    all_fields.append(val)

            dimension_count = 0
            measure_count = 0

            for fld in all_fields:

                if not isinstance(fld, dict):
                    continue

                if is_measure(fld):
                    measure_count += 1
                else:
                    dimension_count += 1

            logging.info(
                f"[detect_visual_type] "
                f"dimensions={dimension_count}, "
                f"measures={measure_count}"
            )

            # =====================================================
            # MATRIX RULE
            # =====================================================

            """
            MATRIX IF:
            - at least 1 dimension
            - at least 1 measure

            Handles:
            - 1 dimension + 1 measure
            - multiple dimensions
            - date hierarchy
            - nested rows/columns
            """

            has_measure_names_context = any(
                "measure names" in str(filt.get("column") or "").lower()
                for filt in filters
                if isinstance(filt, dict)
            ) or bool(worksheet.get("measure_names"))

            if (
                dimension_count >= 1
                and (measure_count >= 1 or has_measure_names_context)
            ):

                logging.info(
                    f"[detect_visual_type] "
                    f"Routing to MATRIX"
                )

                return "highlighted table"

            # =====================================================
            # ELSE TABLE
            # =====================================================

            logging.info(
                f"[detect_visual_type] "
                f"Routing to TABLE"
            )

            return "table"
        case "shape":
            return "scatter chart"
        case "ganttbar":
            return "waterfall chart"
        case "automatic bar line" | "automatic line bar":
            return "combo chart (bar and line)"
        case "automatic area line" | "automatic line area":
            return "combo chart (line and area)"
        case "automatic area bar" | "automatic bar area" | "bar bar area":
            return "combo chart (bar and area)"
        case "circle":
            return "scatter chart"
        case "automatic" | "":
            if "line" in normalized_marks:
                return "line chart"
            if _has_date_on_axes(rows, cols):
                return "line chart"
            if has_measure_anywhere:
                if "area" in normalized_marks:
                    return "combo chart (line and area)"
                return "bar chart"
            if "text" in encodings:
                return "table"
            if rows or cols:
                return "table"

            logging.warning(
                f"⚠️ Could not determine visual type for worksheet '{ws_title or ws_name}', defaulting to 'table'"
            )
            return "table"
        case _:
            logging.warning(
                f"⚠️ Could not determine visual type for worksheet '{ws_title or ws_name}', defaulting to 'table'"
            )
            return "table"


# ======== Visual Processor ========
def process_visual(worksheet, visual_type, tableau_data=None):
    visual_type = (visual_type or "").strip().lower()

    if visual_type not in converters:
        logging.error(f"❌ Unsupported visual type: {visual_type}")
        logging.error(f"Available converter keys: {list(converters.keys())}")
        return None

    converter_func = converters[visual_type]
    logging.info(f"✅ Dispatching {visual_type} -> {converter_func.__name__}")

    if (
        visual_type == "donut chart"
        and converter_func.__name__ != "convert_tableau_to_powerbi_donut"
    ):
        raise RuntimeError(
            f"🚨 Mapping mismatch: {visual_type} routed to {converter_func.__name__}"
        )

    try:
        if visual_type == "line chart" and tableau_data:
            return converter_func(
                {"worksheets": [worksheet], "workbook": tableau_data}
            )
        if visual_type in {"highlighted table", "table", "heatmap"} and tableau_data:
            return converter_func(
                {"worksheets": [worksheet], "workbook": tableau_data}
            )
        return converter_func({"worksheets": [worksheet]})
    except TypeError:
        return converter_func(worksheet)

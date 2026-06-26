from typing import Dict
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Semantic_Model.Semantic_utils import new_guid


# -------------Generate-Column-TMDL------------#
def get_format_string(datatype: str, column_name: str) -> str:
    if datatype == "int64":
        return "0"
    elif datatype == "dateTime":
        return "Long Date"
    elif "ID" in column_name.upper():
        return None
    else:
        return None


def generate_column_tmdl(
    column: Dict[str, str],
    datatype_mapping: Dict[str, str],
    aggregation_mapping: Dict[str, str],
) -> str:
    """Generate TMDL snippet for a single column."""

    col_name = column["name"]
    col_datatype = datatype_mapping.get(column["datatype"].lower(), "string")
    col_aggregation = aggregation_mapping.get(column.get("aggregation", "Sum"), "none")
    col_lineage = new_guid()

    if " " in col_name or "-" in col_name or "/" in col_name:
        col_display_name = f"'{col_name}'"
    else:
        col_display_name = col_name

    tmdl = f"\tcolumn {col_display_name}\n"
    tmdl += f"\t\tdataType: {col_datatype}\n"

    fmt = get_format_string(col_datatype, col_name)
    if fmt:
        tmdl += f"\t\tformatString: {fmt}\n"

    tmdl += f"\t\tlineageTag: {col_lineage}\n"
    tmdl += f"\t\tsummarizeBy: {col_aggregation}\n"
    tmdl += f"\t\tsourceColumn: {col_name}\n\n"

    # Add Summarization annotation
    tmdl += f"\t\tannotation SummarizationSetBy = Automatic\n"

    # Special handling for dateTime
    if col_datatype == "dateTime":
        variation_rel_guid = new_guid()
        variation_table_guid = new_guid()

        tmdl += f"""
\t\tvariation Variation
\t\t\tisDefault
\t\t\trelationship: {variation_rel_guid}
\t\t\tdefaultHierarchy: LocalDateTable_{variation_table_guid}.'Date Hierarchy'
"""

        tmdl += f"\n\t\tannotation UnderlyingDateTimeDataType = Date\n"

    # Special handling for doubles with aggregation
    if col_datatype == "double" and col_aggregation != "none":
        tmdl += f'\n\t\tannotation PBI_FormatHint = {{"isGeneralNumber":true}}\n'

    tmdl += "\n"
    return tmdl

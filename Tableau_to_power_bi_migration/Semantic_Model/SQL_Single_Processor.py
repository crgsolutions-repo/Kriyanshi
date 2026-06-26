import xml.etree.ElementTree as ET
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from typing import Dict, Any, Tuple
from Semantic_Model.Semantic_utils import new_guid, extract_table_names


# === SQL Single Processor ===
# ------------- SQL Single Processor (Fixed Version)-----------#
import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple
import uuid
import re


def extract_table_names(twb_file: str) -> list:
    """Extract table names from TWB file."""
    tree = ET.parse(twb_file)
    root = tree.getroot()

    table_names = []
    for connection in root.findall(".//connection"):
        table = connection.get("table") or connection.get("tablename")
        if table:
            table_names.append(table.strip("[]"))

    return table_names  # if table_names else ["Orders"]


def process_sql_single(
    twb_file: str,
    datasource_info: Dict[str, Any],
    output_dir: str = None,
    write_local_date_table_tmdl=None,
    **kwargs,
) -> Tuple[str, Dict[str, Any]]:
    """
    Process single SQL Server datasource and return TMDL content.

    Args:
        twb_file: Path to Tableau TWB file
        datasource_info: Dictionary with datasource connection info
        output_dir: Directory for LocalDateTable files (optional)
        write_local_date_table_tmdl: Function to generate LocalDateTable (optional)
        **kwargs: Additional parameters (sql_server, database, schema)

    Returns:
        (tmdl_content, metadata_dict)
    """

    def infer_dtype(datatype):
        """Map Tableau datatypes to TMDL datatypes with SQL properties."""
        if datatype is None:
            return "string", None, "none", "nvarchar(50)", False, {}

        dt = datatype.lower()

        if any(x in dt for x in ["real", "float", "double", "decimal", "number"]):
            return (
                "double",
                None,
                "sum",
                "float",
                False,
                {"PBI_FormatHint": '{"isGeneralNumber":true}'},
            )
        elif "int" in dt:
            return ("int64", "0", "sum", "smallint", False, {})
        elif "date" in dt and "time" in dt:
            return (
                "dateTime",
                "Long Date",
                "none",
                "datetime",
                False,
                {"UnderlyingDateTimeDataType": "Date"},
            )
        elif "date" in dt:
            return (
                "dateTime",
                "Long Date",
                "none",
                "date",
                False,
                {"UnderlyingDateTimeDataType": "Date"},
            )
        elif "time" in dt:
            return ("dateTime", "Long Time", "none", "time", False, {})
        elif "bool" in dt:
            return ("boolean", None, "none", "bit", False, {})
        elif any(x in dt for x in ["string", "char", "text"]):
            return ("string", None, "none", "nvarchar(50)", False, {})
        return ("string", None, "none", "nvarchar(max)", False, {})

    # --- Parse TWB file ---
    tree = ET.parse(twb_file)
    root = tree.getroot()
    ns = {"t": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

    columns: Dict[str, Dict[str, Any]] = {}
    date_columns_info = {}

    for col in root.findall(".//column", ns):
        col_name = col.get("caption") or col.get("name")
        if not col_name:
            continue

        col_name = col_name.strip("[]").replace(" ", "_")
        dtype, fmt, summarize_by, provider_type, nullable, annotations = infer_dtype(
            col.get("datatype")
        )

        if col_name not in columns:
            lineage_tag = new_guid()
            columns[col_name] = {
                "dataType": dtype,
                "formatString": fmt,
                "summarizeBy": summarize_by,
                "sourceColumn": col_name,
                "sourceProviderType": provider_type,
                "isNullable": nullable,
                "annotations": annotations,
                "lineageTag": lineage_tag,
            }

            if dtype == "dateTime":
                date_columns_info[col_name] = lineage_tag

    # --- Connection Info ---
    sql_server = kwargs.get("sql_server") or datasource_info.get(
        "server", "YourSQLServer"
    )
    database = kwargs.get("database") or datasource_info.get("database", "YourDatabase")
    schema = kwargs.get("schema") or datasource_info.get("schema", "dbo")

    # --- Table name ---
    table_names = extract_table_names(twb_file)
    table_name = table_names[0] if table_names else "Orders"
    # table_guid = new_guid()

    # --- Build TMDL content ---
    content = f"table {table_name}\n"
    # content += f"\tlineageTag: {table_guid}\n"

    for name, props in columns.items():
        content += f"\n\tcolumn {name}\n"
        content += f"\t\tdataType: {props['dataType']}\n"
        if props["formatString"]:
            content += f"\t\tformatString: {props['formatString']}\n"
        content += f"\t\tlineageTag: {props['lineageTag']}\n"
        content += f"\t\tsummarizeBy: {props['summarizeBy']}\n"
        content += f"\t\tsourceColumn: {props['sourceColumn']}\n"

        # Insert placeholder
        if props["dataType"] == "dateTime":
            content += f"\t\t###VARIATION_PLACEHOLDER_{name}###\n"

        content += f"\t\tannotation SummarizationSetBy = Automatic\n"
        for ann_key, ann_val in props["annotations"].items():
            content += f"\t\tannotation {ann_key} = {ann_val}\n"

    # --- Partition for DirectQuery ---
    content += f"\n\tpartition {table_name} = m\n"
    content += "\t\tmode: directQuery\n"
    content += "\t\tsource =\n"
    content += "\t\t\t\tlet\n"
    content += f'\t\t\t\t    Source = Sql.Databases("{sql_server}", [HierarchicalNavigation=true]),\n'
    content += f'\t\t\t\t    DB = Source{{[Name="{database}"]}}[Data],\n'
    content += f'\t\t\t\t    Schema = DB{{[Schema="{schema}"]}}[Data],\n'
    content += f'\t\t\t\t    {table_name}1 = Schema{{[Name="{table_name}"]}}[Data]\n'
    content += "\t\t\t\tin\n"
    content += f"\t\t\t\t    {table_name}1\n"
    content += "\n\tannotation PBI_ResultType = Table\n"

    # --- LocalDateTable handling ---
    date_columns_metadata = []

    if date_columns_info and output_dir and write_local_date_table_tmdl:
        print(
            f"[+] Found {len(date_columns_info)} date column(s): {list(date_columns_info.keys())}"
        )

        for col_name in date_columns_info.keys():
            try:
                metadata = write_local_date_table_tmdl(
                    output_dir=output_dir, source_table=table_name, date_column=col_name
                )

                # Validate metadata
                if (
                    not metadata
                    or "relationship_guid" not in metadata
                    or "local_table_name" not in metadata
                ):
                    print(f"[!] Invalid metadata for {col_name}: {metadata}")
                    continue

                relationship_guid = metadata["relationship_guid"]
                local_table_name = metadata["local_table_name"]

                # Define placeholder and variation block
                placeholder_pattern = rf"###VARIATION_PLACEHOLDER_{col_name}###"
                variation_block = (
                    f"\t\tvariation Variation\n"
                    f"\t\t\tisDefault\n"
                    f"\t\t\trelationship: {relationship_guid}\n"
                    f"\t\t\tdefaultHierarchy: {local_table_name}.'Date Hierarchy'\n"
                )

                # Replace using regex (handles indentation/newlines)
                new_content, count = re.subn(
                    placeholder_pattern, variation_block, content
                )
                if count == 0:
                    print(f"[!] Placeholder not found for {col_name} — check naming")
                else:
                    print(
                        f"[+] Added variation block for {col_name} -> {local_table_name}"
                    )

                content = new_content
                date_columns_metadata.append(metadata)

            except Exception as e:
                print(f"[!] Error creating LocalDateTable for {col_name}: {e}")
                import traceback

                traceback.print_exc()

    else:
        if date_columns_info:
            print(
                f"[!] Warning: {len(date_columns_info)} date column(s) found but LocalDateTable not generated"
            )
            print(f"    - output_dir: {output_dir}")
            print(f"    - write_local_date_table_tmdl: {write_local_date_table_tmdl}")
        # Remove all placeholders if LocalDateTable skipped
        for col_name in date_columns_info.keys():
            content = re.sub(rf"###VARIATION_PLACEHOLDER_{col_name}###", "", content)

    # --- Final metadata ---
    metadata_dict = {
        "table_name": table_name,
        "date_columns_metadata": date_columns_metadata,
        "date_columns": list(date_columns_info.keys()),
    }

    return content, metadata_dict

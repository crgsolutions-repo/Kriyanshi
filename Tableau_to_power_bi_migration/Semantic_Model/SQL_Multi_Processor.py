import xml.etree.ElementTree as ET
from typing import Dict, Any
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Semantic_Model.Semantic_utils import new_guid, extract_table_names


# === SQL Multi Processor ===
# ---------- SQL Multi Processor Module ----------#

import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, List
import os
import uuid


# ---------- Helper Function: Extract Table Names ----------#
def extract_table_names_sql(twb_file: str) -> List[str]:
    """Extract unique table names from TWB file."""
    tree = ET.parse(twb_file)
    root = tree.getroot()

    table_names = set()

    # Method 1: From metadata-records
    for metadata in root.findall(".//metadata-record[@class='column']"):
        parent_elem = metadata.find("parent-name")
        if parent_elem is not None and parent_elem.text:
            table_name = parent_elem.text.strip("[]")
            if table_name:
                table_names.add(table_name)

    # Method 2: From relation elements
    for relation in root.findall(".//relation"):
        table = relation.get("table")
        if table:
            table_names.add(table.strip("[]"))

    return list(table_names)


# ---------- Helper Function: Group Columns by Parent Table ----------#
def group_columns_by_parent_sql(twb_file: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parse metadata-records and group columns by their parent table.
    Returns: {parent_table: [column_info1, column_info2, ...]}
    """
    tree = ET.parse(twb_file)
    root = tree.getroot()

    table_columns = {}

    # Find all metadata-records of class 'column'
    for metadata in root.findall(".//metadata-record[@class='column']"):
        parent_name_elem = metadata.find("parent-name")
        remote_name_elem = metadata.find("remote-name")

        if parent_name_elem is None or remote_name_elem is None:
            continue

        parent_name = (
            parent_name_elem.text.strip("[]") if parent_name_elem.text else None
        )
        column_name = remote_name_elem.text.strip() if remote_name_elem.text else None

        if not parent_name or not column_name:
            continue

        # Extract SQL datatype from DebugRemoteType
        sql_type = None
        for attr in metadata.findall("./attributes/attribute"):
            if attr.get("name") == "DebugRemoteType":
                if attr.text:
                    sql_type = attr.text.strip('"')
                break

        # Fallback to local-type if DebugRemoteType not found
        if not sql_type:
            local_type_elem = metadata.find("local-type")
            sql_type = (
                local_type_elem.text if local_type_elem is not None else "nvarchar(50)"
            )

        # Initialize list for this parent if not exists
        if parent_name not in table_columns:
            table_columns[parent_name] = []

        table_columns[parent_name].append({"name": column_name, "datatype": sql_type})

    for parent, cols in table_columns.items():
        print(f"[+] Found {len(cols)} columns for table: {parent}")

    return table_columns


# ---------- Helper Function: Map SQL Types to TMDL ----------#
def map_sql_to_tmdl(sql_type: str, col_name: str) -> Tuple[str, str, str]:
    """
    Map SQL data types to TMDL schema.
    Returns: (dataType, formatString, summarizeBy)
    """
    if not sql_type:
        return "string", None, "none"

    sql_type = sql_type.lower()
    col_name_clean = col_name.strip().lower()

    # Integer types
    if any(x in sql_type for x in ["int", "bigint", "smallint", "tinyint"]):
        dataType = "int64"
        formatString = "0"
        summarizeBy = "count" if "id" in col_name_clean else "sum"

    # Decimal / float
    elif any(
        x in sql_type
        for x in ["decimal", "numeric", "float", "real", "money", "double"]
    ):
        dataType = "double"
        formatString = None  # Will be handled by annotation
        summarizeBy = "sum"

    # Date/time
    elif any(
        x in sql_type
        for x in ["date", "datetime", "datetime2", "smalldatetime", "timestamp"]
    ):
        dataType = "dateTime"
        formatString = "Long Date"
        summarizeBy = "none"

    # Boolean
    elif "bit" in sql_type or "bool" in sql_type:
        dataType = "boolean"
        formatString = None
        summarizeBy = "none"

    # String types
    elif any(
        x in sql_type for x in ["char", "varchar", "nchar", "nvarchar", "text", "ntext"]
    ):
        dataType = "string"
        formatString = None
        summarizeBy = "none"

    # Fallback
    else:
        dataType = "string"
        formatString = None
        summarizeBy = "none"

    return dataType, formatString, summarizeBy


# ---------- Helper Function: Generate TMDL for Single Table ----------#
def generate_single_table_tmdl_sql(
    table_name: str,
    columns: List[Dict[str, Any]],
    sql_server: str,
    database: str,
    schema: str = "dbo",
) -> Tuple[str, Dict[str, str]]:
    """
    Generate TMDL content for a single SQL table.
    Returns: (tmdl_content, date_columns_info)
    """

    columns_dict = {}
    date_columns_info = {}

    # Generate lineage tag for table
    table_lineage = str(uuid.uuid4())

    # Process each column
    for col_info in columns:
        col_name = col_info["name"]
        sql_type = col_info["datatype"]

        dtype, format_string, summarize_by = map_sql_to_tmdl(sql_type, col_name)

        lineage_tag = str(uuid.uuid4())
        columns_dict[col_name] = {
            "dataType": dtype,
            "formatString": format_string,
            "summarizeBy": summarize_by,
            "sourceColumn": col_name,
            "lineageTag": lineage_tag,
        }

        # Track date columns
        if dtype == "dateTime":
            date_columns_info[col_name] = lineage_tag

    # Build TMDL content
    content = f"table {table_name}\n"
    content += f"\tlineageTag: {table_lineage}\n"

    # Add columns
    for name, props in columns_dict.items():
        content += f"\tcolumn {name}\n"
        content += f"\t\tdataType: {props['dataType']}\n"

        if props["formatString"]:
            content += f"\t\tformatString: {props['formatString']}\n"

        content += f"\t\tlineageTag: {props['lineageTag']}\n"
        content += f"\t\tsummarizeBy: {props['summarizeBy']}\n"
        content += f"\t\tsourceColumn: {props['sourceColumn']}\n"

        # Add variation placeholder for date columns
        if props["dataType"] == "dateTime":
            content += f"\t\t### VARIATION_PLACEHOLDER_{name} ###\n"

        content += "\n\t\tannotation SummarizationSetBy = Automatic\n"

        # Add special annotations for date columns
        if props["dataType"] == "dateTime":
            content += "\t\tannotation UnderlyingDateTimeDataType = Date\n"

        # Add PBI_FormatHint for doubles
        if props["dataType"] == "double" and props["summarizeBy"] != "none":
            content += '\t\tannotation PBI_FormatHint = {"isGeneralNumber":true}\n'

    # Add partition section with correct Sql.Database format
    content += f"\tpartition {table_name} = m\n"
    content += "\t\tmode: import\n"
    content += "\t\tsource =\n"
    content += "\t\t\t\tlet\n"
    content += f'\t\t\t\t    Source = Sql.Database("{sql_server}", "{database}"),\n'
    content += f'\t\t\t\t    {schema}_{table_name} = Source{{[Schema="{schema}",Item="{table_name}"]}}[Data]\n'
    content += "\t\t\t\tin\n"
    content += f"\t\t\t\t    {schema}_{table_name}\n"
    content += "\n\tannotation PBI_ResultType = Table\n"

    return content, date_columns_info


# ---------- Main Multi-SQL Processor ----------#
def process_sql_multi(
    twb_file: str,
    datasource_info: Dict[str, Any],
    output_dir: str = None,
    write_local_date_table_tmdl=None,
    **kwargs,
) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, str]]]]:
    """
    Process multiple SQL Server tables from TWB → generate Power BI TMDL files.

    Args:
        twb_file: Path to Tableau TWB file
        datasource_info: Dict with server, database, schema info
        output_dir: Directory to write TMDL files (optional, None = return content only)
        write_local_date_table_tmdl: Function to generate LocalDateTable (optional)
        **kwargs: Override sql_server, database, schema

    Returns:
        (table_contents, all_metadata)
        - table_contents: {table_name: tmdl_content_string}
        - all_metadata: {table_name: [date_columns_metadata, ...]}
    """

    # Get connection info - prioritize kwargs
    sql_server = kwargs.get("sql_server") or datasource_info.get(
        "server", "YourSQLServer"
    )
    database = kwargs.get("database") or datasource_info.get("database", "YourDatabase")
    schema = kwargs.get("schema") or datasource_info.get("schema", "dbo")

    print(f"\n[+] Connecting to SQL Server: {sql_server}")
    print(f"[+] Database: {database}")
    print(f"[+] Schema: {schema}\n")

    # Step 1: Extract table names
    table_names = extract_table_names_sql(twb_file)
    print(f"[+] Found {len(table_names)} table(s): {table_names}\n")

    # Step 2: Group columns by parent table
    table_columns = group_columns_by_parent_sql(twb_file)
    print(f"[+] Extracted columns for {len(table_columns)} table(s)\n")

    # Step 3: Generate TMDL for each table
    all_metadata = {}
    table_contents = {}

    for table_name in table_names:
        # Get columns for this table
        columns = table_columns.get(table_name, [])

        if not columns:
            print(
                f"[!] Warning: No columns found for table '{table_name}', skipping..."
            )
            continue

        # Generate TMDL for this table
        tmdl_content, date_columns_info = generate_single_table_tmdl_sql(
            table_name=table_name,
            columns=columns,
            sql_server=sql_server,
            database=database,
            schema=schema,
        )

        # Step 4: Handle LocalDateTable creation if function provided
        date_columns_metadata = []

        if date_columns_info and write_local_date_table_tmdl:
            for col_name in date_columns_info.keys():
                # Generate LocalDateTable
                metadata = write_local_date_table_tmdl(
                    output_dir, source_table=table_name, date_column=col_name
                )

                date_columns_metadata.append(metadata)

                # Replace variation placeholder
                relationship_guid = metadata["relationship_guid"]
                local_table_name = metadata["local_table_name"]

                placeholder = f"\t\t### VARIATION_PLACEHOLDER_{col_name} ###\n"
                variation_block = f"""\t\tvariation Variation
\t\t\tisDefault
\t\t\trelationship: {relationship_guid}
\t\t\tdefaultHierarchy: {local_table_name}.'Date Hierarchy'
"""
                tmdl_content = tmdl_content.replace(placeholder, variation_block)

        # Store the content
        table_contents[table_name] = tmdl_content
        all_metadata[table_name] = date_columns_metadata

        # Step 5: Write TMDL file if output_dir provided
        if output_dir:
            output_path = os.path.join(output_dir, f"{table_name}.tmdl")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(tmdl_content)
            print(f"[+] TMDL written to: {output_path}")

    print(f"\n[+] Successfully processed {len(table_contents)} table(s)")

    return table_contents, all_metadata

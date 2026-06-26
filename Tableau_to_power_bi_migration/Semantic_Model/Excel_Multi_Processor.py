import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Tuple
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Semantic_Model.Semantic_utils import new_guid

from Semantic_Model.Genereate_columns import generate_column_tmdl

from Semantic_Model.Calculation_Integration import extract_and_generate_measures

# === XLSX Multi Processor ===
# ---------- Excel Multi Processor Module ----------#

import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, List
import os
import uuid


# ---------- Helper Function: Extract Data Sources from TWB ----------#
def extract_data_sources_from_twb(twb_file: str) -> Dict[str, Dict[str, str]]:
    """
    Extract all Excel data sources from TWB file.
    Returns: {table_name: {"file_path": path, "sheet_name": name}}
    """
    tree = ET.parse(twb_file)
    root = tree.getroot()

    data_sources = {}

    # Find all named-connections with Excel
    for named_conn in root.findall(".//named-connection"):
        caption = named_conn.get("caption", "").strip()

        # Find the connection element within named-connection
        connection = named_conn.find("connection[@class='excel-direct']")
        if connection is None:
            connection = named_conn.find("connection[@class='excel']")

        if connection is not None:
            file_path = connection.get("filename", "")

            if caption and file_path:
                # Use caption as table name (clean it)
                table_name = caption.replace(" ", "_")

                # Extract sheet name from file name (default to Sheet1)
                sheet_name = "Sheet1"  # You might want to parse this from TWB

                data_sources[table_name] = {
                    "file_path": file_path,
                    "sheet_name": sheet_name,
                }

                print(f"[+] Found data source: {table_name} -> {file_path}")

    return data_sources


# ---------- Helper Function: Group Columns by Parent Table ----------#
def group_columns_by_parent(twb_file: str) -> Dict[str, List[Dict[str, Any]]]:
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
        local_type_elem = metadata.find("local-type")

        if parent_name_elem is None or remote_name_elem is None:
            continue

        parent_name = (
            parent_name_elem.text.strip("[]") if parent_name_elem.text else None
        )
        column_name = remote_name_elem.text.strip() if remote_name_elem.text else None
        datatype = local_type_elem.text if local_type_elem is not None else "string"

        if not parent_name or not column_name:
            continue

        # Initialize list for this parent if not exists
        if parent_name not in table_columns:
            table_columns[parent_name] = []

        table_columns[parent_name].append({"name": column_name, "datatype": datatype})

    for parent, cols in table_columns.items():
        print(f"[+] Found {len(cols)} columns for parent table: {parent}")

    return table_columns


# ---------- Helper Function: Infer Data Type ----------#
def infer_dtype(datatype):
    """Map Tableau datatypes to expected TMDL datatypes."""
    if datatype is None:
        return "string", None, "none"

    datatype = datatype.lower()

    # Numeric types
    if (
        "real" in datatype
        or "float" in datatype
        or "double" in datatype
        or "decimal" in datatype
        or "number" in datatype
    ):
        return "double", None, "sum"
    elif "int" in datatype or "integer" in datatype:
        return "int64", "0", "sum"

    # Date and time types
    elif "date" in datatype and "time" in datatype:
        return "dateTime", "General Date", "none"
    elif "date" in datatype:
        return "dateTime", "Long Date", "none"
    elif "time" in datatype:
        return "dateTime", "Long Time", "none"

    # Boolean
    elif "bool" in datatype:
        return "boolean", None, "none"

    # String / categorical
    elif "string" in datatype or "char" in datatype or "text" in datatype:
        return "string", None, "none"

    # Fallback
    else:
        return "string", None, "none"


# ---------- Helper Function: Generate TMDL for Single Table ----------#
def generate_single_table_tmdl(
    table_name: str, columns: List[Dict[str, Any]], file_path: str, sheet_name: str
) -> Tuple[str, Dict[str, str]]:
    """
    Generate TMDL content for a single table.
    Returns: (tmdl_content, date_columns_info)
    """

    columns_dict = {}
    date_columns_info = {}

    # Process each column
    for col_info in columns:
        col_name = col_info["name"]
        dtype, format_string, summarize_by = infer_dtype(col_info["datatype"])

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

    for name, props in columns_dict.items():
        content += f"\n\tcolumn '{name}'\n"
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

        # Add UnderlyingDateTimeDataType for date columns
        if props["dataType"] == "dateTime":
            content += "\t\tannotation UnderlyingDateTimeDataType = Date\n"

    # Add partition section
    content += f"\n\tpartition {table_name} = m\n"
    content += "\t\tmode: import\n"
    content += "\t\tsource =\n"
    content += "\t\t\t\tlet\n"
    content += f'\t\t\t\t    Source = Excel.Workbook(File.Contents("{file_path}"), null, true),\n'
    content += f'\t\t\t\t    {sheet_name}_Sheet = Source{{[Item="{sheet_name}",Kind="Sheet"]}}[Data],\n'
    content += f'\t\t\t\t    #"Promoted Headers" = Table.PromoteHeaders({sheet_name}_Sheet, [PromoteAllScalars=true]),\n'
    content += f'\t\t\t\t    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers",{{\n'

    for i, (name, props) in enumerate(columns_dict.items()):
        comma = "," if i < len(columns_dict) - 1 else ""
        if props["dataType"] == "int64":
            dtype = "Int64.Type"
        elif props["dataType"] == "double":
            dtype = "type number"
        elif props["dataType"] == "dateTime":
            dtype = "type date"
        elif props["dataType"] == "boolean":
            dtype = "type logical"
        else:
            dtype = "type text"
        content += f'\t\t\t\t        {{"{name}", {dtype}}}{comma}\n'

    content += "\t\t\t\t    })\n"
    content += "\t\t\t\tin\n"
    content += f'\t\t\t\t    #"Changed Type"\n'
    content += "\n\tannotation PBI_ResultType = Table\n"

    return content, date_columns_info


# ---------- Helper Function: Match Parent Names to Data Sources ----------#
def match_parent_to_datasource(
    parent_name: str, data_sources: Dict[str, Dict[str, str]]
) -> Tuple[str, Dict[str, str]]:
    """
    Try to match a parent table name with a data source.
    Returns: (matched_table_name, source_info)
    """
    # Direct match
    if parent_name in data_sources:
        return parent_name, data_sources[parent_name]

    # Try flexible matching (case-insensitive, substring)
    parent_lower = parent_name.lower()
    for source_name, source_info in data_sources.items():
        source_lower = source_name.lower()
        if parent_lower in source_lower or source_lower in parent_lower:
            print(f"[+] Matched parent '{parent_name}' to data source '{source_name}'")
            return source_name, source_info

    # No match found - use first available source as fallback
    if data_sources:
        fallback = list(data_sources.items())[0]
        print(
            f"[!] Warning: No data source found for parent '{parent_name}', using '{fallback[0]}'"
        )
        return fallback

    # No data sources at all - return defaults
    print(f"[!] Warning: No data sources available, using defaults for '{parent_name}'")
    return parent_name, {
        "file_path": "C:\\Path\\To\\Excel\\File.xlsx",
        "sheet_name": "Sheet1",
    }


# ---------- Main Multi-Excel Processor ----------#
def process_xlsx_multi(
    twb_file: str,
    output_dir: str = None,
    write_local_date_table_tmdl=None,
    include_measures: bool = True,  # NEW PARAMETER
    use_llm_for_measures: bool = False,  # NEW PARAMETER
    openai_api_key: str = None,  # NEW PARAMETER
) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, str]]]]:
    """
    Process multiple Excel files from TWB → generate Power BI TMDL files.

    Args:
        twb_file: Path to Tableau TWB file
        output_dir: Directory to write TMDL files (optional, None = return content only)
        write_local_date_table_tmdl: Function to generate LocalDateTable (optional)
        include_measures: Whether to extract and add calculated fields as measures
        use_llm_for_measures: Use LLM for measure conversion (requires openai_api_key)
        openai_api_key: OpenAI API key for LLM-based conversion

    Returns:
        (table_contents, all_metadata)
        - table_contents: {table_name: tmdl_content_string}
        - all_metadata: {table_name: [date_columns_metadata, ...]}
    """

    # Extract measures once at the beginning
    measures_content = ""
    if include_measures:
        measures_content = extract_and_generate_measures(
            twb_file, use_llm=use_llm_for_measures, api_key=openai_api_key
        )

    # Step 1: Extract all data sources from TWB
    data_sources = extract_data_sources_from_twb(twb_file)
    print(f"\n[+] Extracted {len(data_sources)} data source(s) from TWB")

    # Step 2: Group columns by parent table
    table_columns = group_columns_by_parent(twb_file)
    print(f"[+] Found columns for {len(table_columns)} parent table(s)\n")

    # If no columns found, try to infer from data sources
    if not table_columns and data_sources:
        print("[!] No metadata-records found, inferring structure from data sources")
        # Create a basic structure for each data source
        for source_name in data_sources.keys():
            table_columns[source_name] = []

    # Step 3: Match parent names with data sources and generate TMDL
    all_metadata = {}
    table_contents = {}

    for parent_name, columns in table_columns.items():
        # Match parent to data source
        table_name, source_info = match_parent_to_datasource(parent_name, data_sources)

        # Step 4: Generate TMDL for this table
        tmdl_content, date_columns_info = generate_single_table_tmdl(
            table_name=table_name,
            columns=columns,
            file_path=source_info.get("file_path", ""),
            sheet_name=source_info.get("sheet_name", "Sheet1"),
        )

        # Step 5: Handle LocalDateTable creation if function provided
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

        # Step 5.5: Append measures before the annotation at the end (MOVED HERE)
        if measures_content:
            # Insert measures before the final annotation
            parts = tmdl_content.rsplit("\n\tannotation PBI_ResultType = Table\n", 1)
            if len(parts) == 2:
                tmdl_content = (
                    parts[0]
                    + measures_content
                    + "\n\tannotation PBI_ResultType = Table\n"
                    + parts[1]
                )
            else:
                # Fallback: append at the end if annotation not found
                tmdl_content += measures_content

        # Store the content (MOVED AFTER measures insertion)
        table_contents[table_name] = tmdl_content
        all_metadata[table_name] = date_columns_metadata

        # Step 6: Write TMDL file if output_dir provided
        if output_dir:
            output_path = os.path.join(output_dir, f"{table_name}.tmdl")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(tmdl_content)
            print(f"[+] TMDL written to: {output_path}")

    print(f"\n[+] Successfully processed {len(table_contents)} table(s)")

    return table_contents, all_metadata

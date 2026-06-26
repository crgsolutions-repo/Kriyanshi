import xml.etree.ElementTree as ET
import os
from pathlib import Path
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Semantic_Model.Semantic_utils import (
    extract_datasource_info,
    extract_excel_file_info,
    extract_table_names,
    create_folder_structure,
)
from Semantic_Model.Semantic_File_Writting_Functions import (
    write_database_tmdl,
    write_model_tmdl,
    write_relationships_tmdl,
)
from Semantic_Model.Excel_Multi_Processor import process_xlsx_multi
from Semantic_Model.Excel_Single_Processor import process_xlsx_single
from Semantic_Model.SQL_Multi_Processor import process_sql_multi
from Semantic_Model.SQL_Single_Processor import process_sql_single
from Semantic_Model.Genereate_columns import generate_column_tmdl
from Semantic_Model.Semantic_utils import new_guid
from Semantic_Model.Semantic_File_Writting_Functions import (
    write_local_date_table_tmdl,
    write_date_table_template_tmdl,
)
from Semantic_Model.Semantic_utils import extract_relationships_from_file
import xml.etree.ElementTree as ET
import os
import uuid
from typing import Dict, List, Any
import sys
import os


from collections import defaultdict
from Semantic_Model.Semantic_utils import new_guid, extract_table_names


# ==== Helper Functions ===#


def extract_all_table_columns_with_type(twb_file_path: str) -> dict:
    """
    Extracts all table names and their columns (with data types) from a TWB file.
    Returns:
        Dict[str, Dict[str, Dict[str, str]]] = {
            "TableName": {
                "Column1": {"dataType": "string"},
                "Column2": {"dataType": "integer"},
                ...
            }
        }
    """

    if not os.path.exists(twb_file_path):
        raise FileNotFoundError(f"TWB file not found: {twb_file_path}")

    tree = ET.parse(twb_file_path)
    root = tree.getroot()

    table_columns = {}

    # Tableau's XML often has <column> inside <datasource> or <relation>
    for datasource in root.findall(".//datasource"):
        ds_name = datasource.get("name") or "UnnamedDatasource"

        for column in datasource.findall(".//column"):
            col_name = column.get("name")
            datatype = column.get("datatype", "").lower() or "string"

            # Normalize Tableau datatypes to Power BI-like types
            if "char" in datatype or "string" in datatype or datatype == "":
                datatype = "string"
            elif "int" in datatype or "number" in datatype:
                datatype = "integer"
            elif "date" in datatype:
                datatype = "date"
            elif "bool" in datatype:
                datatype = "boolean"
            elif "float" in datatype or "real" in datatype:
                datatype = "decimal"

            # Add table-column structure
            if ds_name not in table_columns:
                table_columns[ds_name] = {}
            table_columns[ds_name][col_name] = {"dataType": datatype}

    # Include relation tables if defined but not already captured
    for relation in root.findall(".//relation"):
        table_name = relation.get("table") or relation.get("name")
        if table_name and table_name not in table_columns:
            table_columns[table_name] = {}

    print(f"Extracted columns for {len(table_columns)} table(s)")
    return table_columns


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


# === Main Controller Function (public API) ===
def run_semantic_model(
    twb_file_path: str,
    sql_server: str = None,
    database: str = None,
    schema: str = None,
    output_dir: str = None,
    include_measures: bool = True,
    use_llm_for_measures: bool = False,
    openai_api_key: str = None,
) -> str:
    """
    Robust semantic model generator.
    Handles multiple datasources, parameter-only sources, and federated connections.
    """

    # === Setup ===
    if output_dir is None:
        desktop = str(Path.home() / "Desktop")
        base_output = os.path.join(desktop, "Test.SemanticModel")
    else:
        base_output = output_dir

    os.makedirs(base_output, exist_ok=True)
    print("\n=== Starting Semantic Model Generation ===")
    print(f"TWB File: {twb_file_path}")
    print(f"Output Directory: {base_output}")

    if include_measures:
        print(f"Measures: Enabled (LLM: {'Yes' if use_llm_for_measures else 'No'})")

    if not os.path.exists(twb_file_path):
        raise FileNotFoundError(f"TWB file not found: {twb_file_path}")

    definition_dir, tables_dir = create_folder_structure(base_output)
    print("Created folder structure: definition/ and tables/")

    # === Parse TWB XML ===
    tree = ET.parse(twb_file_path)
    root = tree.getroot()
    print("Parsed TWB XML successfully")

    # === Locate a valid datasource ===
    datasource_elem = None
    for ds in root.findall(".//datasource"):
        ds_name = ds.get("name")
        has_conn = ds.get("hasconnection", "true")

        if has_conn == "false":
            print(f"Skipping parameter-only datasource: {ds_name}")
            continue

        conn = ds.find(".//connection")
        if conn is not None:
            datasource_elem = ds
            print(f"Selected datasource: {ds_name}")
            break

    if datasource_elem is None:
        raise ValueError("No datasource with a valid <connection> found in TWB file.")

    connection_elem = datasource_elem.find(".//connection")
    conn_class = (connection_elem.get("class", "") or "").lower()
    print(f"Detected datasource class: {conn_class}")

    # === Gather additional info ===
    named_connections = root.findall(".//named-connection")
    relation_elem = datasource_elem.find(".//relation")
    relation_type = relation_elem.get("type") if relation_elem is not None else None

    # === Table names ===
    table_names = extract_table_names(twb_file_path)
    print(f"Extracted {len(table_names)} table(s): {table_names}")

    # === Identify datasource type ===
    file_info = {}
    datasource_info = {}
    ds_type = None

    # --- SQL Server ---
    if conn_class in ["sqlserver"] or (
        conn_class == "federated"
        and any(
            (nc.find("connection") is not None)
            and nc.find("connection").get("class", "").lower() == "sqlserver"
            for nc in named_connections
        )
    ):
        ds_type = "sql_multi" if relation_type == "collection" else "sql_single"
        datasource_info = extract_datasource_info(twb_file_path)
        print(f"Detected datasource type: {ds_type}")

    # --- Excel ---
    elif conn_class in ["excel", "excel-direct"] or (
        conn_class == "federated"
        and any(
            (nc.find("connection") is not None)
            and nc.find("connection").get("class", "").lower()
            in ["excel", "excel-direct"]
            for nc in named_connections
        )
    ):
        ds_type = "xlsx_multi"
        file_info = extract_excel_file_info(twb_file_path)
        print(f"Detected datasource type: {ds_type}")

    # --- Unknown ---
    else:
        raise ValueError(f"Unsupported or unrecognized datasource class: {conn_class}")

    sql_kwargs = {
        "sql_server": sql_server,
        "database": database,
        "schema": schema or "dbo",
    }

    all_date_columns_metadata = []

    # === Process by Type ===
    if ds_type == "xlsx_multi":
        print("Processing Excel datasource...")
        table_contents, date_metadata_dict = process_xlsx_multi(
            twb_file=twb_file_path,
            output_dir=tables_dir,
            write_local_date_table_tmdl=write_local_date_table_tmdl,
            include_measures=include_measures,
            use_llm_for_measures=use_llm_for_measures,
            openai_api_key=openai_api_key,
        )
        for table_name, metadata_list in date_metadata_dict.items():
            all_date_columns_metadata.extend(metadata_list)
        print(f"Processed {len(table_contents)} Excel table(s)")

    elif ds_type == "sql_single":
        print("Processing single SQL table...")
        model_content, metadata_dict = process_sql_single(
            twb_file_path,
            datasource_info,
            output_dir=tables_dir,
            write_local_date_table_tmdl=write_local_date_table_tmdl,
            include_measures=include_measures,
            use_llm_for_measures=use_llm_for_measures,
            openai_api_key=openai_api_key,
            **sql_kwargs,
        )

        table_name = metadata_dict.get("table_name") or (
            table_names[0] if table_names else "Table"
        )
        with open(
            os.path.join(tables_dir, f"{table_name}.tmdl"), "w", encoding="utf-8"
        ) as f:
            f.write(model_content)

        all_date_columns_metadata = metadata_dict.get("date_columns_metadata", [])
        print(f"Processed SQL table: {table_name}")

    elif ds_type == "sql_multi":
        print("Processing multiple SQL tables...")
        table_contents, _ = process_sql_multi(
            twb_file_path,
            datasource_info,
            output_dir=tables_dir,
            write_local_date_table_tmdl=write_local_date_table_tmdl,
            include_measures=include_measures,
            use_llm_for_measures=use_llm_for_measures,
            openai_api_key=openai_api_key,
            **sql_kwargs,
        )
        for table_name, content in table_contents.items():
            with open(
                os.path.join(tables_dir, f"{table_name}.tmdl"), "w", encoding="utf-8"
            ) as f:
                f.write(content)
        print(f"Processed {len(table_contents)} SQL table(s)")

    # === Date Template ===
    # date_template_name = None
    # if all_date_columns_metadata:
    #   print(
    #        f"Creating DateTableTemplate for {len(all_date_columns_metadata)} date column(s)..."
    #    )
    #      date_template_file = write_date_table_template_tmdl(tables_dir)
    #     date_template_name = os.path.splitext(os.path.basename(date_template_file))[0]
    #      print(f"DateTableTemplate created: {date_template_name}")
    # else:
    #     print("No date columns found - skipping DateTableTemplate")
    date_template_name = None
    if all_date_columns_metadata:
        print(f"Found {len(all_date_columns_metadata)} date column(s)")
        # Don't call write_date_table_template_tmdl here since it's already
        # been called inside the processor functions
        date_template_name = "DateTableTemplate"  # Use consistent name

    # === Relationships ===
    relationships = []
    if len(table_names) > 1 or all_date_columns_metadata:
        print("Extracting relationships...")
        try:
            relationships = extract_relationships_from_file(twb_file_path)
            print(f"Found {len(relationships)} relationship(s)")
        except Exception as e:
            print(f"Warning: Could not extract relationships: {e}")
            relationships = []

        if relationships or all_date_columns_metadata:
            print("Writing relationships.tmdl...")
            write_relationships_tmdl(
                definition_dir,
                relationships=relationships if relationships else None,
                date_columns_metadata=all_date_columns_metadata or None,
            )

    # === Write Model Files ===
    print("Writing database.tmdl and model.tmdl...")
    write_database_tmdl(definition_dir)
    write_model_tmdl(
        definition_dir,
        table_names,
        date_columns_metadata=all_date_columns_metadata,
        date_template_name=date_template_name,
    )

    print("\n===============================================")
    print(f"✅ Semantic model created in: {base_output}")
    print(f"   📂 definition/ → database.tmdl, model.tmdl, relationships.tmdl")
    print(f"   📂 definition/tables/ → {len(table_names)} table(s) + date tables")
    if include_measures:
        print(f"   📊 Calculated fields converted to measures")
    print("===============================================\n")

    return base_output

"""
semantic_model_twb.py

Refactored module for processing Tableau TWB files into semantic model TMDL files.

Public API:
    run_semantic_model(twb_file_path: str) -> str

This module keeps the original helper functions, datatype mappings and detailed
comments as requested, while organizing them into a reusable module.
"""

import xml.etree.ElementTree as ET
import os
import uuid
from typing import Dict, List, Any
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# === Utility Functions ===
import xml.etree.ElementTree as ET
import os
import uuid
from typing import Dict, List, Any
import sys
import os


# === Utility Functions ===
def new_guid() -> str:
    """Generate a new GUID for lineage tags."""
    return str(uuid.uuid4())


def remove_duplicates_preserve_order(items: List[str]) -> List[str]:
    """Remove duplicates from list while preserving order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def detect_datasource_type(twb_file: str) -> str:
    """
    Parse TWB file to detect datasource type (xlsx/sql, single/multi).
    Returns one of: 'xlsx_single', 'xlsx_multi', 'sql_single', 'sql_multi'.
    """
    tree = ET.parse(twb_file)
    root = tree.getroot()

    datasources = root.findall(".//datasource")
    if not datasources:
        raise ValueError("No datasource found in TWB file.")

    ds = datasources[0]
    connection = ds.find(".//connection")
    if connection is None:
        raise ValueError("No <connection> element found in datasource.")

    conn_class = connection.get("class", "").lower()

    if conn_class == "excel":
        relations = ds.findall(".//relation")
        return "xlsx_multi" if len(relations) > 1 else "xlsx_single"

    elif conn_class == "federated":
        named_conn = ds.find(".//named-connection/connection")
        if named_conn is None:
            raise ValueError("No <named-connection> for federated source")

        inner_class = named_conn.get("class", "").lower()

        # Handle SQLServer as before
        if inner_class in ["sqlserver"]:
            relations = ds.findall(".//relation")
            return "sql_multi" if len(relations) > 1 else "sql_single"
        # Treat excel-direct as xlsx
        elif inner_class in ["excel-direct", "excel"]:
            relations = ds.findall(".//relation")
            return "xlsx_multi" if len(relations) > 1 else "xlsx_single"
        else:
            raise ValueError(f"Unsupported federated class: {inner_class}")

    else:
        raise ValueError(f"Unsupported datasource class: {conn_class}")


def extract_table_names(twb_file: str) -> List[str]:
    """Return list of unique table names from TWB for model.tmdl and annotations."""
    tree = ET.parse(twb_file)
    root = tree.getroot()
    table_names = []
    for rel in root.findall(".//relation[@type='table']"):
        name = rel.get("name")
        if name:
            # Clean table name
            clean_name = name.replace("[", "").replace("]", "").replace("$", "")
            table_names.append(clean_name)

    # Remove duplicates while preserving order
    return remove_duplicates_preserve_order(table_names)


def extract_excel_file_info(twb_file: str) -> Dict[str, Dict[str, str]]:
    """
    Extract Excel file paths and sheet information from TWB file.
    Returns dict mapping table names to their file info.
    """
    tree = ET.parse(twb_file)
    root = tree.getroot()

    file_info: Dict[str, Dict[str, str]] = {}

    # For federated connections (multi-table Excel)
    for named_conn in root.findall(".//named-connection"):
        caption = named_conn.get("caption", "")
        connection = named_conn.find("connection")

        if connection is not None:
            conn_class = connection.get("class", "").lower()
            if conn_class in ["excel-direct", "excel"]:
                filename = connection.get("filename", "")
                if filename and caption:
                    # Extract sheet name from relation if available
                    sheet_name = caption  # Default to caption

                    # Try to find the actual sheet name from relation
                    for relation in root.findall(".//relation[@type='table']"):
                        rel_name = (
                            relation.get("name", "")
                            .replace("[", "")
                            .replace("]", "")
                            .replace("$", "")
                        )
                        if rel_name == caption:
                            # Look for sheet name in table attribute or use caption
                            sheet_name = caption
                            break

                    file_info[caption] = {
                        "file_path": filename,
                        "sheet_name": sheet_name,
                    }

    # For single Excel files (direct connection)
    if not file_info:
        connection = root.find(".//connection[@class='excel']")
        if connection is not None:
            filename = connection.get("filename", "")
            if filename:
                # Get table name
                table_names = extract_table_names(twb_file)
                table_name = table_names[0] if table_names else "Sheet1"
                file_info[table_name] = {
                    "file_path": filename,
                    "sheet_name": table_name,
                }

    return file_info


def extract_datasource_info(twb_file: str) -> Dict[str, Any]:
    """Extract datasource connection information for SQL cases."""
    tree = ET.parse(twb_file)
    root = tree.getroot()

    info: Dict[str, Any] = {}

    # Find connection details
    connection = root.find(".//connection")
    if connection is not None:
        conn_class = connection.get("class", "").lower()

        if conn_class == "federated":
            named_conn = root.find(".//named-connection/connection")
            if named_conn is not None:
                info["server"] = named_conn.get("server", "")
                info["database"] = named_conn.get("dbname", "")
                info["schema"] = "dbo"  # Default schema
        else:
            info["server"] = connection.get("server", "")
            info["database"] = connection.get("dbname", "")
            info["schema"] = "dbo"

    return info


def create_folder_structure(base_dir: str):
    """
    Create the following structure:
    Test.SemanticModel/
        definition/
            tables/
    """
    definition_dir = os.path.join(base_dir, "definition")
    tables_dir = os.path.join(definition_dir, "tables")
    os.makedirs(tables_dir, exist_ok=True)
    return definition_dir, tables_dir


def get_table_name_from_parent(parent_name: str, twb_file: str) -> str:
    """Map parent/datasource names to clean table names from object-graph."""
    tree = ET.parse(twb_file)
    root = tree.getroot()

    # Get caption from object-graph
    for obj in root.findall(".//object-graph/objects/object"):
        obj_caption = obj.get("caption", "")
        relation = obj.find(".//relation")
        if relation is not None:
            rel_name = relation.get("name", "")
            if rel_name == parent_name or obj_caption.lower() == parent_name.lower():
                return obj_caption

    return parent_name


def clean_table_id(table_id: str) -> str:
    # Clean table ID by keeping substring before underscore
    return table_id.split("_")[0]


def extract_relationships_from_file(file_path: str):
    """Parse a Tableau TWB file at given path and extract relationships with cleaned table names."""
    tree = ET.parse(file_path)
    root = tree.getroot()

    def clean_table_id(table_id: str) -> str:
        return table_id.split("_")[0] if table_id else None

    relationships_list = []

    for rel in root.findall(".//relationships/relationship"):
        expr = rel.find("expression")
        if expr is None:
            continue

        cols = expr.findall("expression")
        if len(cols) != 2:
            continue

        # Get column names from 'op' attribute, not text content
        col1_name = cols[0].get("op")
        col2_name = cols[1].get("op")

        first = rel.find("first-end-point")
        second = rel.find("second-end-point")
        if first is None or second is None:
            continue

        first_obj_id = first.attrib.get("object-id")
        second_obj_id = second.attrib.get("object-id")

        first_table = clean_table_id(first_obj_id)
        second_table = clean_table_id(second_obj_id)

        if col1_name and col2_name:
            # FIXED: Return in the correct format
            relationships_list.append(
                {
                    "from_table": first_table,
                    "from_column": col1_name,
                    "to_table": second_table,
                    "to_column": col2_name,
                }
            )

    return relationships_list

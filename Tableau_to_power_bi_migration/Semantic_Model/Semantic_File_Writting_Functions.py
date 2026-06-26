import os
from typing import List, Dict
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Semantic_Model.Semantic_utils import (
    remove_duplicates_preserve_order,
)
from Semantic_Model.Genereate_columns import generate_column_tmdl

# === Database Writer ===
from typing import Optional


# ------file writting functions-------#
# === Database Writer ===
def write_database_tmdl(output_dir: str) -> str:
    """Write database.tmdl file."""
    db_file = os.path.join(output_dir, "database.tmdl")
    with open(db_file, "w", encoding="utf-8") as f:
        f.write("database\n\tcompatibilityLevel: 1550\n")
    return db_file


# === Table Writers ===
def write_table_tmdls(
    output_dir: str, table_columns: Dict[str, List[Dict[str, str]]]
) -> List[str]:
    """
    Generate one .tmdl file per table using column definitions.

    table_columns example:
    {
        "Orders": [
            {"name": "OrderID", "dataType": "int64", "formatString": "0"},
            {"name": "Region", "dataType": "string"}
        ],
        "People": [
            {"name": "PersonID", "dataType": "int64"},
            {"name": "Region", "dataType": "string"}
        ]
    }
    """
    written_files = []
    for table_name, columns in table_columns.items():
        table_file = os.path.join(output_dir, f"{table_name}.tmdl")
        with open(table_file, "w", encoding="utf-8") as f:
            f.write(f"table {table_name}\n")
            for col in columns:
                f.write(
                    generate_column_tmdl(col)
                )  # your utility will format each column block
                f.write("\n")
        written_files.append(table_file)
    return written_files


# === Master Writer ===
def write_semantic_tmdls(
    output_dir: str,
    table_columns: Dict[str, List[Dict[str, str]]],
    relationships: List[Dict[str, str]],
) -> Dict[str, str]:
    """
    Master function to generate all semantic model files.

    Returns dict of written file paths.
    """
    os.makedirs(output_dir, exist_ok=True)

    files = {}
    files["database"] = write_database_tmdl(output_dir)
    files["model"] = write_model_tmdl(output_dir, list(table_columns.keys()))
    files["tables"] = write_table_tmdls(output_dir, table_columns)
    files["relationships"] = write_relationships_tmdl(output_dir, relationships)

    return files


# === Local Date File ===


def write_local_date_table_tmdl(
    output_dir: str, source_table: str, date_column: str
) -> Dict[str, str]:
    """
    Write a LocalDateTable TMDL file for a specific date column.

    Returns metadata dict with ALL necessary info:
    {
        'table': source_table,
        'column': date_column,
        'filename': filename,
        'table_uuid': table_uuid,
        'relationship_guid': relationship_guid,  # ← KEY ADDITION
        'local_table_name': f"LocalDateTable_{table_uuid}"
    }
    """
    # Generate consistent UUIDs
    table_uuid = str(uuid.uuid4()).replace("-", "_")
    relationship_guid = str(uuid.uuid4())  # ← Generate relationship GUID here

    filename = f"LocalDateTable_{table_uuid}.tmdl"
    file_path = os.path.join(output_dir, filename)
    local_table_name = f"LocalDateTable_{table_uuid}"

    content = f"""table {local_table_name}
\tisHidden
\tshowAsVariationsOnly
\tlineageTag: {str(uuid.uuid4())}

\tcolumn Date
\t\tdataType: dateTime
\t\tisHidden
\t\tformatString: General Date
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: PaddedDateTableDates
\t\tsummarizeBy: none
\t\tisNameInferred
\t\tisDataTypeInferred
\t\tsourceColumn: [Date]

\t\tannotation SummarizationSetBy = User

\tcolumn Year = YEAR([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: Years
\t\tsummarizeBy: none
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = Year

\tcolumn MonthNo = MONTH([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: MonthOfYear
\t\tsummarizeBy: none
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = MonthNumber

\tcolumn Month = FORMAT([Date], "MMMM")
\t\tdataType: string
\t\tisHidden
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: Months
\t\tsummarizeBy: none
\t\tsortByColumn: MonthNo
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = Month

\tcolumn QuarterNo = INT(([MonthNo] + 2) / 3)
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: QuarterOfYear
\t\tsummarizeBy: none
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = QuarterNumber

\tcolumn Quarter = "Qtr " & [QuarterNo]
\t\tdataType: string
\t\tisHidden
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: Quarters
\t\tsummarizeBy: none
\t\tsortByColumn: QuarterNo
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = Quarter

\tcolumn Day = DAY([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: {str(uuid.uuid4())}
\t\tdataCategory: DayOfMonth
\t\tsummarizeBy: none
\t\tisDataTypeInferred

\t\tannotation SummarizationSetBy = User
\t\tannotation TemplateHintText = Day

\thierarchy 'Date Hierarchy'
\t\tlineageTag: {str(uuid.uuid4())}

\t\tlevel Year
\t\t\tcolumn: Year

\t\tlevel Quarter
\t\t\tcolumn: Quarter

\t\tlevel Month
\t\t\tcolumn: Month

\t\tlevel Day
\t\t\tcolumn: Day

\t\tannotation TemplateHintText = Date Hierarchy

\tpartition {local_table_name} = calculated
\t\tmode: import
\t\tsource = Calendar(Date(Year(MIN('{source_table}'[{date_column}])), 1, 1), Date(Year(MAX('{source_table}'[{date_column}])), 12, 31))

\tannotation __PBI_LocalDateTable = true
"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Return comprehensive metadata with relationship_guid
    return {
        "table": source_table,
        "column": date_column,
        "filename": filename,
        "table_uuid": table_uuid,
        "relationship_guid": relationship_guid,  # ← CRITICAL
        "local_table_name": local_table_name,
    }


# === Synced Relationship Writer ===

import os
import re
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Any


# =========================================================
# 1️⃣ UNIVERSAL RELATIONSHIP EXTRACTOR
# =========================================================
def extract_relationships_auto(source_path: str) -> Optional[List[Dict[str, str]]]:
    """
    Automatically detect and extract table relationships from various data sources:
    - Tableau (.twb)
    - Excel (.xlsx, .xls)
    - SQL (.sql)
    - Generic JSON metadata (future-proof)

    Returns a list of relationships:
    [
        {'from_table': 'Orders', 'from_column': 'CustomerID',
         'to_table': 'Customers', 'to_column': 'CustomerID'}
    ]
    or None if none found.
    """

    if not os.path.exists(source_path):
        print(f"[!] File not found: {source_path}")
        return None

    ext = os.path.splitext(source_path)[1].lower()
    relationships = []

    try:
        # ---- Tableau (.twb) ----
        if ext == ".twb":
            tree = ET.parse(source_path)
            root = tree.getroot()
            for rel in root.findall(".//relation[@type='join']"):
                expr = rel.get("join_clause") or ""
                # Extract [Table].[Column] patterns
                matches = re.findall(r"\[([^\]]+)\]\.\[([^\]]+)\]", expr)
                if len(matches) == 2:
                    relationships.append(
                        {
                            "from_table": matches[0][0],
                            "from_column": matches[0][1],
                            "to_table": matches[1][0],
                            "to_column": matches[1][1],
                        }
                    )

        # ---- Excel ----
        elif ext in [".xls", ".xlsx"]:
            import pandas as pd

            xl = pd.ExcelFile(source_path)
            sheet_names = xl.sheet_names
            # Simple heuristic: if multiple sheets share common column names
            # assume relationship
            tables = {
                sheet: set(pd.read_excel(source_path, sheet_name=sheet).columns)
                for sheet in sheet_names
            }
            for t1, cols1 in tables.items():
                for t2, cols2 in tables.items():
                    if t1 != t2:
                        common_cols = cols1 & cols2
                        for col in common_cols:
                            relationships.append(
                                {
                                    "from_table": t1,
                                    "from_column": col,
                                    "to_table": t2,
                                    "to_column": col,
                                }
                            )

        # ---- SQL ----
        elif ext == ".sql":
            with open(source_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Detect JOIN ON clauses
            join_matches = re.findall(
                r"JOIN\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
                content,
                re.IGNORECASE,
            )
            for jm in join_matches:
                relationships.append(
                    {
                        "from_table": jm[1],
                        "from_column": jm[2],
                        "to_table": jm[3],
                        "to_column": jm[4],
                    }
                )

        # ---- Unknown/Unsupported ----
        else:
            print(f"[!] Unsupported file type: {ext}")
            return None

    except Exception as e:
        print(f"[!] Relationship extraction failed: {e}")
        return None

    return relationships if relationships else None


# =========================================================
# 2️⃣ LOCAL DATE TABLE EXTRACTOR (uses external metadata writer)
# =========================================================
def extract_local_date_metadata(
    source_path: str, date_columns: List[str]
) -> Optional[List[Dict[str, str]]]:
    """
    Identify date columns in a source file and prepare metadata
    for local date table generation.

    Returns a list of metadata dicts (same structure as write_local_date_table_tmdl)
    or None if no date columns found.
    """

    if not date_columns:
        return None

    metadata_list = []
    for col in date_columns:
        table_name = os.path.splitext(os.path.basename(source_path))[0]
        table_uuid = str(uuid.uuid4())
        relationship_guid = str(uuid.uuid4())
        local_table_name = f"LocalDateTable_{table_uuid}"
        filename = f"{local_table_name}.tmdl"

        metadata_list.append(
            {
                "table": table_name,
                "column": col,
                "filename": filename,
                "table_uuid": table_uuid,
                "relationship_guid": relationship_guid,
                "local_table_name": local_table_name,
            }
        )

    return metadata_list if metadata_list else None


# =========================================================
# 3️⃣ RELATIONSHIP FILE WRITER
# =========================================================
def write_relationships_tmdl(
    output_dir: str,
    relationships: Optional[List[Dict[str, str]]] = None,
    date_columns_metadata: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Dynamically create relationships.tmdl file based on whatever metadata is available.
    Writes nothing if both are None.
    """

    if not relationships and not date_columns_metadata:
        print("[!] No relationships or date metadata found — skipping write.")
        return None

    os.makedirs(output_dir, exist_ok=True)
    rel_file = os.path.join(output_dir, "relationships.tmdl")

    date_rels = []
    regular_rels = []

    with open(rel_file, "w", encoding="utf-8") as f:
        # ---- Write Local Date Relationships ----
        if date_columns_metadata:
            for meta in date_columns_metadata:
                f.write(f"relationship {meta['relationship_guid']}\n")
                f.write("\tjoinOnDateBehavior: datePartOnly\n")
                f.write(f"\tfromColumn: {meta['table']}.'{meta['column']}'\n")
                f.write(f"\ttoColumn: {meta['local_table_name']}.Date\n\n")

                date_rels.append(
                    {
                        "relationship": meta["relationship_guid"],
                        "local_table": meta["local_table_name"],
                        "date_column": meta["column"],
                    }
                )

        # ---- Write Regular Relationships ----
        if relationships:
            for rel in relationships:
                rel_uuid = str(uuid.uuid4())
                f.write(f"relationship Auto_{rel_uuid}\n")
                f.write(f"\tfromColumn: {rel['from_table']}.{rel['from_column']}\n")
                f.write(f"\ttoColumn: {rel['to_table']}.{rel['to_column']}\n\n")

                regular_rels.append(
                    {
                        "relationship": f"Auto_{rel_uuid}",
                        "from": f"{rel['from_table']}.{rel['from_column']}",
                        "to": f"{rel['to_table']}.{rel['to_column']}",
                    }
                )

    print(f"[+] relationships.tmdl written to {rel_file}")

    return {
        "filename": rel_file,
        "date_relationships": date_rels,
        "regular_relationships": regular_rels,
    }


# === Dynamic Model Writer - SIMPLIFIED ===
def write_model_tmdl(
    output_dir: str,
    table_names: List[str],
    date_columns_metadata: List[Dict[str, str]] = None,
    date_template_name: str = None,
) -> str:
    """
    Write a model.tmdl file with dynamic table references.

    Parameters:
        output_dir: Directory to write model.tmdl
        table_names: List of main table names
        date_columns_metadata: List of metadata dicts from write_local_date_table_tmdl()
        date_template_name: Full name of DateTableTemplate (e.g., "DateTableTemplate_8d35227e...")
                           If None, won't add DateTableTemplate reference

    Returns:
        Path to the generated model.tmdl file
    """
    unique_table_names = remove_duplicates_preserve_order(table_names)
    model_file = os.path.join(output_dir, "model.tmdl")
    indent = "    "  # 4 spaces

    with open(model_file, "w", encoding="utf-8") as f:
        f.write("model Model\n")
        f.write(f"{indent}culture: en-IN\n")
        f.write(f"{indent}defaultPowerBIDataSourceVersion: powerBI_V3\n")
        f.write(f"{indent}sourceQueryCulture: en-IN\n")
        f.write(f"{indent}dataAccessOptions\n")
        f.write(f"{indent*2}legacyRedirects\n")
        f.write(f"{indent*2}returnErrorValuesAsNull\n\n")

        # Add annotations
        f.write("/// Errors in queries that were loaded dynamically.\n")
        f.write("queryGroup 'Dynamic Query Errors'\n\n")
        f.write(f"{indent}annotation PBI_QueryGroupOrder = 0\n\n")
        f.write(f"annotation __PBI_TimeIntelligenceEnabled = 0\n\n")
        f.write(f"annotation PBI_QueryOrder = {unique_table_names}\n")
        f.write('annotation PBI_ProTooling = ["DevMode"]\n\n')

        # Reference main tables
        for t in unique_table_names:
            f.write(f"ref table {t}\n")

        # DYNAMIC: Reference DateTableTemplate if provided
        if date_template_name:
            f.write(f"ref table {date_template_name}\n")

        # DYNAMIC: Reference LocalDateTables from metadata
        if date_columns_metadata:
            for metadata in date_columns_metadata:
                local_table_name = metadata["local_table_name"]
                f.write(f"ref table {local_table_name}\n")

        f.write("\n")
        f.write("ref cultureInfo en-IN\n")

    print(f"[+] Model.tmdl written to: {model_file}")
    return model_file


# === Helper function to remove duplicates while preserving order ===
def remove_duplicates_preserve_order(items: List[str]) -> List[str]:
    """Remove duplicates from list while preserving order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ===Date Table Tempelate===#


def write_date_table_template_tmdl(output_dir: str) -> str:
    """Write DateTableTemplate_<UUID>.tmdl file with fixed date columns and hierarchy."""
    import uuid

    table_uuid = str(uuid.uuid4())
    table_lineage_uuid = str(uuid.uuid4())

    filename = f"DateTableTemplate_{table_uuid}.tmdl"
    file_path = os.path.join(output_dir, filename)

    content = f"""table DateTableTemplate_{table_uuid}
\tisHidden
\tisPrivate
\tlineageTag: {table_lineage_uuid}

\tcolumn Date
\t\tdataType: dateTime
\t\tisHidden
\t\tformatString: General Date
\t\tlineageTag: 5e6947ba-6834-4363-a7b9-2d746007c739
\t\tdataCategory: PaddedDateTableDates
\t\tsummarizeBy: none
\t\tisNameInferred
\t\tsourceColumn: [Date]

\t\tannotation SummarizationSetBy = User

\tcolumn Year = YEAR([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: 472674a3-f653-47c9-86ac-6e9bd8e3ee50
\t\tdataCategory: Years
\t\tsummarizeBy: none

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = Year

\tcolumn MonthNo = MONTH([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: 4bfee77a-723e-4501-b87a-8a73c31995d9
\t\tdataCategory: MonthOfYear
\t\tsummarizeBy: none

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = MonthNumber

\tcolumn Month = FORMAT([Date], "MMMM")
\t\tdataType: string
\t\tisHidden
\t\tlineageTag: 66b58ddb-9c69-45c0-a89f-623f9c970a55
\t\tdataCategory: Months
\t\tsummarizeBy: none
\t\tsortByColumn: MonthNo

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = Month

\tcolumn QuarterNo = INT(([MonthNo] + 2) / 3)
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: ad9994d3-99aa-4a4f-9f68-6cc5a99c5ff5
\t\tdataCategory: QuarterOfYear
\t\tsummarizeBy: none

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = QuarterNumber

\tcolumn Quarter = "Qtr " & [QuarterNo]
\t\tdataType: string
\t\tisHidden
\t\tlineageTag: 82610c46-ab39-4182-9018-a231e92dc4cb
\t\tdataCategory: Quarters
\t\tsummarizeBy: none
\t\tsortByColumn: QuarterNo

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = Quarter

\tcolumn Day = DAY([Date])
\t\tdataType: int64
\t\tisHidden
\t\tformatString: 0
\t\tlineageTag: 752767fb-ea65-4e0f-8070-f1876c340be2
\t\tdataCategory: DayOfMonth
\t\tsummarizeBy: none

\t\tannotation SummarizationSetBy = User

\t\tannotation TemplateId = Day

\thierarchy 'Date Hierarchy'
\t\tlineageTag: de74101f-20d2-4d08-a70e-17056146b22c

\t\tlevel Year
\t\t\tlineageTag: c3b88090-5981-44a6-9167-86c6207d50b4
\t\t\tcolumn: Year

\t\tlevel Quarter
\t\t\tlineageTag: be28da7f-62f0-4e5d-bd6e-8b0e15386af0
\t\t\tcolumn: Quarter

\t\tlevel Month
\t\t\tlineageTag: 62ff37ad-d104-42cf-bda3-2bb3217070ff
\t\t\tcolumn: Month

\t\tlevel Day
\t\t\tlineageTag: 6bf01455-42d9-43e1-8fb0-7774cc5813b2
\t\t\tcolumn: Day

\t\tannotation TemplateId = DateHierarchy

\tpartition DateTableTemplate_{table_uuid} = calculated
\t\tmode: import
\t\tsource = Calendar(Date(2015,1,1), Date(2015,1,1))

\tannotation __PBI_TemplateDateTable = true

\tannotation DefaultItem = DateHierarchy
"""

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path

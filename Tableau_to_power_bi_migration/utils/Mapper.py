from collections import defaultdict
import xml.etree.ElementTree as ET


def extract_table_columns_mapping(xml_path: str) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    table_columns = defaultdict(set)  # Use set to avoid duplicates

    for datasource in root.findall(".//datasource"):
        for relation in datasource.findall(".//relation"):
            table_name = relation.attrib.get("name", "")
            if table_name:
                columns_elem = relation.find("columns")
                if columns_elem is not None:
                    for col in columns_elem.findall("column"):
                        col_name = col.attrib.get("name", "")
                        if col_name:
                            table_columns[table_name].add(col_name)  # add to set

    # Convert sets to lists for output
    return {k: list(v) for k, v in table_columns.items()}

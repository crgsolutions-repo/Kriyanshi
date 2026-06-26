import xml.etree.ElementTree as ET


def extract_worksheet_names(xml_path):
    """
    Extracts all worksheet names from a Tableau .twb (XML) file.

    Args:
        xml_path (str): Path to the XML (.twb) file

    Returns:
        list[str]: List of worksheet names
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Find all worksheet elements
        worksheets = root.findall(".//worksheet")

        # Extract their 'name' attribute
        names = [ws.get("name") for ws in worksheets if ws.get("name")]

        return names

    except ET.ParseError as e:
        print(f"XML parsing error: {e}")
        return []
    except FileNotFoundError:
        print(f"File not found: {xml_path}")
        return []
    except Exception as e:
        print(f"Unexpected error: {e}")
        return []

import xml.etree.ElementTree as ET


def parse_twb_dashboard(file_path):
    """
    Parse a Tableau .twb file and extract non-redundant:
      - Dashboard name
      - Chart names
      - Coordinates (x, y, w, h) as integers (if possible)
    Only from the 'active' device layout (usually Desktop).
    Falls back to root dashboard layout if not found.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        raise RuntimeError(f"Could not parse TWB: {e}")

    dashboards_data = []

    for dashboard in root.findall(".//dashboard"):
        dash_name = dashboard.attrib.get("name")
        dash_info = {"dashboard_name": dash_name, "charts": []}

        active_layout = dashboard.find(".//devicelayout[@active='true']")
        search_root = active_layout if active_layout is not None else dashboard

        seen = set()
        for zone in search_root.findall(".//zone"):
            name = zone.attrib.get("name")
            if not name or zone.attrib.get("type-v2") == "color":
                continue

            def parse_int(val):
                try:
                    return int(val) if val is not None else None
                except Exception:
                    return val

            chart_data = {
                "chart_name": name,
                "x": parse_int(zone.attrib.get("x")),
                "y": parse_int(zone.attrib.get("y")),
                "width": parse_int(zone.attrib.get("w")),
                "height": parse_int(zone.attrib.get("h")),
            }
            key = tuple(chart_data.values())
            if key not in seen:
                seen.add(key)
                dash_info["charts"].append(chart_data)

        dashboards_data.append(dash_info)

    return dashboards_data

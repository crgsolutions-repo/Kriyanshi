import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    clean_tableau_name,
    clean_field_name,
    is_valid_field_name,
    map_aggregation,
)


def convert_scatter_chart_dynamic(tableau_json):
    import random, string

    DATE_HIERARCHY_LEVELS = {
        "year": "Year",
        "month": "Month",
        "quarter": "Quarter",
        "day": "Day",
    }

    visual_id = "".join(random.choices(string.hexdigits.lower(), k=12))
    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json",
        "name": visual_id,
        "position": {"x": 10, "y": 0, "z": 0, "height": 280, "width": 280},
        "visual": {
            "visualType": "scatterChart",
            "query": {
                "queryState": {
                    "X": {"projections": []},
                    "Y": {"projections": []},
                }
            },
            "drillFilterOtherVisuals": True,
        },
    }

    worksheets = tableau_json.get("worksheets", [tableau_json])

    all_x = []
    all_y = []
    all_series = []

    for worksheet in worksheets:
        # --- X-axis (cols) ---
        for col in worksheet.get("cols", []):
            col_name = clean_field_name(col.get("column") or col.get("name") or "")
            entity = clean_tableau_name(
                col.get("parent-name")
                or worksheet.get("datasource")
                or worksheet.get("name")
                or "Orders"
            )
            if not is_valid_field_name(col_name):
                continue

            deriv = str(col.get("derivation", "")).lower()
            matched_level = None
            for key, level in DATE_HIERARCHY_LEVELS.items():
                if key in deriv:
                    matched_level = level
                    break

            if matched_level:
                x_projection = {
                    "field": {
                        "HierarchyLevel": {
                            "Expression": {
                                "Hierarchy": {
                                    "Expression": {
                                        "PropertyVariationSource": {
                                            "Expression": {
                                                "SourceRef": {"Entity": entity}
                                            },
                                            "Name": "Variation",
                                            "Property": col_name,
                                        }
                                    },
                                    "Hierarchy": "Date Hierarchy",
                                }
                            },
                            "Level": matched_level,
                        }
                    },
                    "queryRef": f"{entity}.{col_name}.Variation.Date Hierarchy.{matched_level}",
                    "nativeQueryRef": f"{col_name} {matched_level}",
                    "active": True,
                }
            else:
                if deriv and deriv != "none":
                    agg_code = map_aggregation(deriv) or 0
                    agg_str = (
                        ["Sum", "Count", "Avg"][agg_code] if agg_code < 3 else "Sum"
                    )
                    x_projection = {
                        "field": {
                            "Aggregation": {
                                "Expression": {
                                    "Column": {
                                        "Expression": {"SourceRef": {"Entity": entity}},
                                        "Property": col_name,
                                    }
                                },
                                "Function": agg_code,
                            }
                        },
                        "queryRef": f"{agg_str}({entity}.{col_name})",
                        "nativeQueryRef": f"{agg_str} of {col_name}",
                        "active": True,
                    }
                else:
                    x_projection = {
                        "field": {
                            "Column": {
                                "Expression": {"SourceRef": {"Entity": entity}},
                                "Property": col_name,
                            }
                        },
                        "queryRef": f"{entity}.{col_name}",
                        "nativeQueryRef": col_name,
                        "active": True,
                    }
            all_x.append(x_projection)

        # --- Y-axis (rows) ---
        for row in worksheet.get("rows", []):
            row_name = clean_field_name(row.get("column") or row.get("name") or "")
            entity = clean_tableau_name(
                row.get("parent-name")
                or worksheet.get("datasource")
                or worksheet.get("name")
                or "Orders"
            )
            deriv = str(row.get("derivation", "")).lower()
            if not row_name:
                continue
            if deriv and deriv != "none":
                agg_code = map_aggregation(deriv) or 0
                agg_str = ["Sum", "Count", "Avg"][agg_code] if agg_code < 3 else "Sum"
                y_projection = {
                    "field": {
                        "Aggregation": {
                            "Expression": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": entity}},
                                    "Property": row_name,
                                }
                            },
                            "Function": agg_code,
                        }
                    },
                    "queryRef": f"{agg_str}({entity}.{row_name})",
                    "nativeQueryRef": f"{agg_str} of {row_name}",
                }
            else:
                y_projection = {
                    "field": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": entity}},
                            "Property": row_name,
                        }
                    },
                    "queryRef": f"{entity}.{row_name}",
                    "nativeQueryRef": row_name,
                }
            all_y.append(y_projection)

        # --- Series (Encoding, prefer color, then shape) ---
        encodings = worksheet.get("encodings", {})
        # Do not map Shape or Color to Legend (Series)
        series_encoding = None
        if series_encoding:
            f_name = clean_field_name(
                series_encoding.get("column") or series_encoding.get("name") or ""
            )
            entity = clean_tableau_name(
                series_encoding.get("parent-name")
                or worksheet.get("datasource")
                or worksheet.get("name")
                or "Orders"
            )
            deriv = str(series_encoding.get("derivation", "")).lower()
            matched_level = None
            for key, level in DATE_HIERARCHY_LEVELS.items():
                if key in deriv:
                    matched_level = level
                    break

            if is_valid_field_name(f_name):
                if matched_level:
                    all_series.append(
                        {
                            "field": {
                                "HierarchyLevel": {
                                    "Expression": {
                                        "Hierarchy": {
                                            "Expression": {
                                                "PropertyVariationSource": {
                                                    "Expression": {
                                                        "SourceRef": {"Entity": entity}
                                                    },
                                                    "Name": "Variation",
                                                    "Property": f_name,
                                                }
                                            },
                                            "Hierarchy": "Date Hierarchy",
                                        }
                                    },
                                    "Level": matched_level,
                                }
                            },
                            "queryRef": f"{entity}.{f_name}.Variation.Date Hierarchy.{matched_level}",
                            "nativeQueryRef": f"{f_name} {matched_level}",
                            "active": True,
                        }
                    )
                else:
                    all_series.append(
                        {
                            "field": {
                                "Column": {
                                    "Expression": {"SourceRef": {"Entity": entity}},
                                    "Property": f_name,
                                }
                            },
                            "queryRef": f"{entity}.{f_name}",
                            "nativeQueryRef": f_name,
                            "active": True,
                        }
                    )

    powerbi_json["visual"]["query"]["queryState"]["X"]["projections"] = all_x
    powerbi_json["visual"]["query"]["queryState"]["Y"]["projections"] = all_y
    if all_series:
        powerbi_json["visual"]["query"]["queryState"]["Series"] = {
        "projections": all_series
    }
    return powerbi_json

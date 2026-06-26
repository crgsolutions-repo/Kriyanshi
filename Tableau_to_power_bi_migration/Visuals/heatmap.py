import uuid
import random
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.tableau_cleaning import (
    agg_code_to_str,
    is_valid_field_name,
    map_aggregation,
    collect_table_measure_fields,
)


def extract_field_with_entity(field):
    if not isinstance(field, dict):
        return None
    native_name = field.get("Native name", "")
    if isinstance(native_name, str) and native_name.strip().lower() == "calculated":
        return None
    col_name = field.get("column")
    entity_name = field.get("parent-name", "")
    derivation = field.get("derivation", None)
    return {"Property": col_name, "Entity": entity_name, "Derivation": derivation}


def convert_tableau_heatmap_to_powerbi(json_in):
    powerbi_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
        "name": uuid.uuid4().hex[:20],
        "position": {
            "x": random.uniform(100, 400),
            "y": random.uniform(100, 400),
            "z": 0,
            "height": random.uniform(130, 160),
            "width": random.uniform(320, 370),
        },
        "visual": {
            "visualType": "pivotTable",
            "query": {
                "queryState": {
                    "Columns": {"projections": []},
                    "Rows": {"projections": []},
                    "Values": {"projections": []},
                }
            },
            "drillFilterOtherVisuals": True,
            "objects": {},
        },
    }

    worksheets = json_in.get("worksheets", [json_in])
    ws = worksheets[0]

    # ----------- Columns section -----------
    columns = []
    for col in ws.get("cols", []):
        mapped_col = extract_field_with_entity(col)
        if mapped_col and is_valid_field_name(mapped_col["Property"]):
            deriv = mapped_col.get("Derivation")
            if (
                deriv
                and isinstance(deriv, str)
                and deriv.lower() in {"year", "quarter", "month", "day"}
            ):
                columns.append(
                    {
                        "field": {
                            "HierarchyLevel": {
                                "Expression": {
                                    "Hierarchy": {
                                        "Expression": {
                                            "PropertyVariationSource": {
                                                "Expression": {
                                                    "SourceRef": {
                                                        "Entity": mapped_col["Entity"]
                                                    }
                                                },
                                                "Name": "Variation",
                                                "Property": mapped_col["Property"],
                                            }
                                        },
                                        "Hierarchy": "Date Hierarchy",
                                    }
                                },
                                "Level": deriv.capitalize(),
                            }
                        },
                        "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}.Variation.Date Hierarchy.{deriv.capitalize()}",
                        "nativeQueryRef": f"{mapped_col['Property']} {deriv.capitalize()}",
                        "active": True,
                    }
                )
            else:
                columns.append(
                    {
                        "field": {
                            "Column": {
                                "Expression": {
                                    "SourceRef": {"Entity": mapped_col["Entity"]}
                                },
                                "Property": mapped_col["Property"],
                            }
                        },
                        "queryRef": f"{mapped_col['Entity']}.{mapped_col['Property']}",
                        "nativeQueryRef": mapped_col["Property"],
                        "active": True,
                    }
                )
    powerbi_json["visual"]["query"]["queryState"]["Columns"]["projections"] = columns

    # ----------- Rows section -----------
    rows = []
    for row in ws.get("rows", []):
        mapped_row = extract_field_with_entity(row)
        if mapped_row and is_valid_field_name(mapped_row["Property"]):
            deriv = mapped_row.get("Derivation")
            if (
                deriv
                and isinstance(deriv, str)
                and deriv.lower() in {"year", "quarter", "month", "day"}
            ):
                rows.append(
                    {
                        "field": {
                            "HierarchyLevel": {
                                "Expression": {
                                    "Hierarchy": {
                                        "Expression": {
                                            "PropertyVariationSource": {
                                                "Expression": {
                                                    "SourceRef": {
                                                        "Entity": mapped_row["Entity"]
                                                    }
                                                },
                                                "Name": "Variation",
                                                "Property": mapped_row["Property"],
                                            }
                                        },
                                        "Hierarchy": "Date Hierarchy",
                                    }
                                },
                                "Level": deriv.capitalize(),
                            }
                        },
                        "queryRef": f"{mapped_row['Entity']}.{mapped_row['Property']}.Variation.Date Hierarchy.{deriv.capitalize()}",
                        "nativeQueryRef": f"{mapped_row['Property']} {deriv.capitalize()}",
                        "active": True,
                    }
                )
            else:
                rows.append(
                    {
                        "field": {
                            "Column": {
                                "Expression": {
                                    "SourceRef": {"Entity": mapped_row["Entity"]}
                                },
                                "Property": mapped_row["Property"],
                            }
                        },
                        "queryRef": f"{mapped_row['Entity']}.{mapped_row['Property']}",
                        "nativeQueryRef": mapped_row["Property"],
                        "active": True,
                    }
                )
    powerbi_json["visual"]["query"]["queryState"]["Rows"]["projections"] = rows

    # ----------- Values section -----------
    measures = []
    workbook = json_in.get("workbook") or json_in
    collected = collect_table_measure_fields(ws, workbook)
    values_proj = collected[0][1] if collected else None

    if values_proj and values_proj.get("field", {}).get("Aggregation"):
        agg_field = values_proj["field"]["Aggregation"]
        agg_code = agg_field.get("Function")
        if agg_code is None:
            agg_code = 0
            agg_field["Function"] = agg_code

        property_name = agg_field["Expression"]["Column"]["Property"]
        entity_name = agg_field["Expression"]["Column"]["Expression"]["SourceRef"]["Entity"]
        agg_str = agg_code_to_str(agg_code)
        query_ref = values_proj.get("queryRef") or f"{agg_str}({entity_name}.{property_name})"

        measures.append(values_proj)
        powerbi_json["visual"]["query"]["queryState"]["Values"][
            "projections"
        ] = measures

        powerbi_json["visual"]["objects"] = {
            "values": [
                {
                    "properties": {
                        "backColor": {
                            "solid": {
                                "color": {
                                    "expr": {
                                        "FillRule": {
                                            "Input": {
                                                "Aggregation": {
                                                    "Expression": {
                                                        "Column": {
                                                            "Expression": {
                                                                "SourceRef": {
                                                                    "Entity": entity_name
                                                                }
                                                            },
                                                            "Property": property_name,
                                                        }
                                                    },
                                                    "Function": agg_code,
                                                }
                                            },
                                            "FillRule": {
                                                "linearGradient2": {
                                                    "min": {
                                                        "color": {
                                                            "Literal": {
                                                                "Value": "'minColor'"
                                                            }
                                                        }
                                                    },
                                                    "max": {
                                                        "color": {
                                                            "Literal": {
                                                                "Value": "'maxColor'"
                                                            }
                                                        }
                                                    },
                                                    "nullColoringStrategy": {
                                                        "strategy": {
                                                            "Literal": {
                                                                "Value": "'asZero'"
                                                            }
                                                        }
                                                    },
                                                }
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "selector": {
                        "data": [{"dataViewWildcard": {"matchingOption": 1}}],
                        "metadata": query_ref,
                    },
                }
            ]
        }
    else:
        powerbi_json["visual"]["query"]["queryState"]["Values"]["projections"] = []

    return powerbi_json

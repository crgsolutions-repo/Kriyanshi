import xml.etree.ElementTree as ET
import pandas as pd
import re
import json


def parse_tableau_to_json(input_twb_path: str, output_json_path: str) -> str:
    """
    Parse a Tableau TWB (XML) file and extract worksheet metadata into JSON.

    Args:
        input_twb_path (str): Path to the Tableau TWB file.
        output_json_path (str): Path where the JSON output should be saved.

    Returns:
        str: Path of the generated JSON file.
    """

    # --- Utility Functions ---
    def strip_namespace(tag: str) -> str:
        """Remove XML namespace prefix from a tag name."""
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def replace_names_with_captions(formula: str) -> str:
        """Replace calculation names in formulas with their captions."""
        if pd.isnull(formula):
            return formula
        for name, caption in name_to_caption.items():
            if name in formula:
                formula = formula.replace(name, caption)
        return formula

    def clean_field(field: str) -> str:
        """Remove federated/sqlproxy prefixes from field expressions."""
        if pd.isnull(field):
            return field
        return re.sub(pattern, "", field)

    def remove_parentheses_outside_brackets(expr: str) -> str:
        """Remove parentheses not enclosed inside brackets."""
        result, inside_brackets = [], False
        for char in expr:
            if char == "[":
                inside_brackets = True
                result.append(char)
            elif char == "]":
                inside_brackets = False
                result.append(char)
            elif char in "()":
                if inside_brackets:
                    result.append(char)
            else:
                result.append(char)
        return "".join(result)

    def clean_expression(expr: str, measure_map: dict, worksheet_name: str) -> str:
        """Clean and normalize expressions for metadata mapping."""
        expr = re.sub(pattern, "", expr)
        expr = remove_parentheses_outside_brackets(expr)
        measures = measure_map.get(worksheet_name, [])
        measure_expr = "|".join(measures) if measures else ""
        if measure_expr:
            expr = expr.replace("[:Measure Names]", measure_expr)
        expr = expr.replace("*", "|").replace("/", "|")
        return expr

    def strip_outer_parentheses(expr: str) -> str:
        """Remove surrounding parentheses from an expression."""
        expr = expr.strip()
        if expr.startswith("(") and expr.endswith(")"):
            return expr[1:-1].strip()
        return expr

    def resolve_metadata_token(token: str):
        token = (token or "").strip()
        if not token:
            return {"name": token}

        if token in metadata_lookup:
            return metadata_lookup[token]

        bracketed = token if token.startswith("[") else f"[{token}]"
        if bracketed in metadata_lookup:
            return metadata_lookup[bracketed]

        field_match = re.search(
            r"(?:none|sum|avg|yr|mn|qtr|wk|day|usr|ctd|cntd|pcto):([^:\]]+)",
            token,
            re.IGNORECASE,
        )
        if field_match:
            field_label = field_match.group(1).strip()
            for meta in metadata_lookup.values():
                if not isinstance(meta, dict):
                    continue
                if (
                    meta.get("local-name") == field_label
                    or meta.get("column") == field_label
                    or field_label in str(meta.get("name", ""))
                ):
                    return meta

        return {"name": token}

    def expr_to_metadata_list(expr: str):
        """Convert an expression string into a list of metadata dicts."""
        expr = strip_outer_parentheses(expr)
        if datasource_prefixes:
            expr = expr.replace(datasource_prefixes[0], "")

        bracket_tokens = re.findall(r"\[[^\]]+\]", expr)
        if bracket_tokens:
            parts = bracket_tokens
        else:
            parts = []
            for segment in expr.split("|"):
                parts.extend(re.split(r"\s*\+\s*", segment))
            parts = [e.strip() for e in parts if e.strip()]

            merged = []
            idx = 0
            while idx < len(parts):
                part = parts[idx]
                while part.count("[") > part.count("]") and idx + 1 < len(parts):
                    idx += 1
                    part += parts[idx]
                merged.append(part)
                idx += 1
            parts = merged

        return [resolve_metadata_token(part) for part in parts]

    def encodings_to_metadata(enc_list: list):
        """Convert list of encoding dictionaries to metadata.
        Each encoding dict has 'tag' and 'column' keys."""
        result = {}
        for enc in enc_list:
            tag = enc["tag"]
            column = enc["column"]

            # Clean the column value
            column_clean = (
                column.replace(datasource_prefixes[0], "", 1)
                if datasource_prefixes
                else column
            )

            # Get metadata
            metadata = metadata_lookup.get(column_clean, {"name": column_clean})

            # If this tag already exists, convert to list or append
            if tag in result:
                if not isinstance(result[tag], list):
                    result[tag] = [result[tag]]
                result[tag].append(metadata)
            else:
                result[tag] = metadata

        return result

    def slices_to_metadata_list(slices_list):
        """Convert slices into metadata dicts."""
        return [
            metadata_lookup.get(
                (
                    s.replace(datasource_prefixes[0], "").strip()
                    if datasource_prefixes
                    else s.strip()
                ),
                {
                    "name": (
                        s.replace(datasource_prefixes[0], "").strip()
                        if datasource_prefixes
                        else s.strip()
                    )
                },
            )
            for s in slices_list
            if s.strip()
        ]

    def extract_title(worksheet_elem):
        """Extract worksheet title text if available."""
        title_elem = worksheet_elem.find(".//layout-options/title/formatted-text/run")
        return (
            title_elem.text.strip()
            if title_elem is not None and title_elem.text
            else ""
        )

    def extract_worksheet_data(worksheet_elem, measure_map):
        """Extract detailed metadata from a worksheet element, including multi-pane marks."""

        name = worksheet_elem.attrib.get("name", "")
        table = worksheet_elem.find("table")

        rows_expr = (
            clean_expression(table.findtext("rows") or "", measure_map, name)
            if table is not None
            else ""
        )
        cols_expr = (
            clean_expression(table.findtext("cols") or "", measure_map, name)
            if table is not None
            else ""
        )

        marks = []
        if table is not None:
            panes = table.find("panes")
            if panes is not None:
                for pane in panes.findall("pane"):
                    mark_elem = pane.find("mark")
                    if mark_elem is not None:
                        mark_class = mark_elem.attrib.get("class", "")
                        if mark_class:
                            marks.append(mark_class)

        # Fallback if no panes or no marks found, use the old single mark extraction approach
        if not marks and table is not None:
            mark_elem = table.find(".//mark")
            if mark_elem is not None:
                mark_class = mark_elem.attrib.get("class", "")
                if mark_class:
                    marks.append(mark_class)

        slices = []
        if table is not None:
            slices_elem = table.find(".//view/slices")
            if slices_elem is not None:
                raw_slices = [
                    re.sub(pattern, "", col.text or "").replace("[:Measure Names]", "")
                    for col in slices_elem.findall("column")
                    if col.text
                ]
                slices = slices_to_metadata_list(raw_slices)

        # MODIFIED: Collect ALL encodings as a list
        encodings_list = []
        if table is not None:
            for enc_type_elem in table.findall(".//panes/pane/encodings/*"):
                field = enc_type_elem.attrib.get("column", "")
                if field:
                    field_clean = re.sub(pattern, "", field)
                    if field_clean != "[Multiple Values]":
                        encodings_list.append(
                            {
                                "tag": strip_namespace(enc_type_elem.tag),
                                "column": field_clean,
                            }
                        )

        ws_measure_names = measure_map.get(name, [])
        view_filters = []
        view_elem = worksheet_elem.find(".//view")
        if view_elem is not None:
            for filt in view_elem.findall("filter"):
                col_raw = re.sub(pattern, "", filt.attrib.get("column", "") or "")
                members = []
                for gf in filt.findall(".//groupfilter"):
                    if gf.attrib.get("function") == "member":
                        member = gf.attrib.get("member")
                        if member:
                            members.append(member)
                if col_raw:
                    view_filters.append(
                        {
                            "column": col_raw,
                            "members": members,
                            "field": metadata_lookup.get(col_raw, {"name": col_raw}),
                        }
                    )
        return {
            "worksheet": name,
            "title": extract_title(worksheet_elem) or name,
            "rows": expr_to_metadata_list(rows_expr),
            "cols": expr_to_metadata_list(cols_expr),
            "marks": marks,  # list of filtered marks
            "slices": slices,
            "encodings": encodings_to_metadata(encodings_list),
            "measure_names": [
                metadata_lookup.get(m, {"name": m}) for m in ws_measure_names
            ],
            "filters": view_filters,
        }

    # --- Parse XML ---
    tree = ET.parse(input_twb_path)
    root = tree.getroot()

    # --- Extract Column Metadata ---
    columns = [
        "ordinal",
        "remote-name",
        "remote-alias",
        "remote-type",
        "parent-name",
        "local-name",
        "local-type",
    ]

    data = []
    for record in root.findall(".//metadata-record[@class='column']"):
        row = {}
        for child in record:
            tag = strip_namespace(child.tag)
            if tag in columns:
                clean_text = (
                    (child.text or "").strip().replace("[", "").replace("]", "")
                )
                row[tag] = clean_text
        row_complete = {col: row.get(col, "") for col in columns}
        parent, local = row_complete.get("parent-name", ""), row_complete.get(
            "local-name", ""
        )
        native_name = f"{parent}.{local}" if parent and local else ""
        row_complete["Native name"] = native_name
        data.append(row_complete)
    df_columns = pd.DataFrame(data)

    datasource_prefixes = []
    for datasource in root.findall(".//datasource"):
        name, caption = datasource.attrib.get("name", ""), datasource.attrib.get(
            "caption", ""
        )
        if name and caption:
            datasource_prefixes.append(f"[{name}].")

    # --- Extract Column Instances ---
    column_instances = []
    for col_inst in root.findall(".//column-instance"):
        row = {k: v for k, v in col_inst.attrib.items() if k not in ["pivot", "type"]}
        for child in col_inst:
            child_tag = strip_namespace(child.tag)
            for attr_name, attr_value in child.attrib.items():
                key = f"{child_tag}:{attr_name}"
                row[key] = attr_value
        column_instances.append(row)
    df_col_instances = pd.DataFrame(column_instances)

    # --- Extract Calculated Columns ---
    columns_data = []
    for column in root.findall(".//column"):
        calc = column.find("calculation")
        if calc is not None:
            columns_data.append(
                {
                    "caption": column.attrib.get("caption"),
                    "name": column.attrib.get("name"),
                    "formula": calc.attrib.get("formula"),
                }
            )
    df_col_calculated = (
        pd.DataFrame(columns_data).drop_duplicates().reset_index(drop=True)
    )

    if {"name", "caption"}.issubset(
        df_col_calculated.columns
    ) and not df_col_calculated.empty:
        name_to_caption = dict(
            zip(df_col_calculated["name"], df_col_calculated["caption"])
        )
    else:
        name_to_caption = {}

    if "formula" in df_col_calculated.columns and not df_col_calculated.empty:
        df_col_calculated["formula"] = df_col_calculated["formula"].apply(
            replace_names_with_captions
        )

    # --- Clean Prefixes ---
    pattern = r"\[(federated|sqlproxy)\.[^\]]+\]\."
    for col in df_col_instances.select_dtypes(include="object").columns:
        df_col_instances[col] = df_col_instances[col].apply(clean_field)

    for col in ["table-calc:field", "table-calc:ordering-field"]:
        if col in df_col_instances.columns:
            df_col_instances[col] = df_col_instances[col].apply(
                replace_names_with_captions
            )

    # --- Merge Calculated Columns ---
    if "name" in df_col_instances.columns and "name" in df_col_calculated.columns:
        df_merged = pd.merge(
            df_col_instances,
            df_col_calculated,
            how="left",
            left_on="column",
            right_on="name",
            suffixes=("", "_calc"),
        )
        df_merged["column"] = df_merged["caption"].combine_first(df_merged["column"])
    else:
        df_merged = df_col_instances.copy()

    df_col_instances = df_merged

    # --- Merge with Column Metadata ---
    df_col_instances["column"] = (
        df_col_instances["column"].str.strip().str.replace(r"[\[\]]", "", regex=True)
    )
    df_columns["local-name"] = (
        df_columns["local-name"].str.strip().str.replace(r"[\[\]]", "", regex=True)
    )

    merged_df = pd.merge(
        df_col_instances,
        df_columns,
        how="left",
        right_on="local-name",
        left_on="column",
        suffixes=("_inst", "_col"),
    )
    merged_df.drop(
        columns=["ordinal", "remote-name", "remote-type", "remote-alias"],
        inplace=True,
        errors="ignore",
    )
    merged_df["Native name"] = merged_df["Native name"].fillna("Calculated")
    merged_df.dropna(subset=["name"], inplace=True)
    merged_df.reset_index(drop=True, inplace=True)

    # --- Build Metadata Lookup ---
    metadata_lookup = {
        row["name"]: {
            key: (None if pd.isna(value) else value) for key, value in row.items()
        }
        for _, row in merged_df.iterrows()
    }

    # --- Extract Measure Names Filters ---
    data_measures = []
    for worksheet in root.findall(".//worksheet"):
        ws_name = worksheet.attrib.get("name", "")
        for filt in worksheet.findall(".//filter"):
            col = filt.attrib.get("column", "")
            if ":Measure Names" in col:
                for gf in filt.findall(".//groupfilter"):
                    if gf.attrib.get("function") != "member":
                        continue
                    raw_member = gf.attrib.get("member", "") or ""
                    raw_member = raw_member.replace("&quot;", "").strip()
                    match = re.search(r"\[([^\]]+)\]", raw_member)
                    if match:
                        token = f"[{match.group(1)}]"
                    elif raw_member:
                        token = raw_member if raw_member.startswith("[") else f"[{raw_member}]"
                    else:
                        continue
                    data_measures.append(
                        {"worksheet name": ws_name, "member": token}
                    )
    df_measure_names = pd.DataFrame(data_measures)

    if not df_measure_names.empty and "worksheet name" in df_measure_names.columns:
        measure_map = (
            df_measure_names.groupby("worksheet name")["member"].apply(list).to_dict()
        )
    else:
        measure_map = {}

    # --- Extract Worksheets ---
    worksheets_data = [
        extract_worksheet_data(ws, measure_map) for ws in root.findall(".//worksheet")
    ]

    calculations = []
    if not df_col_calculated.empty:
        for _, row in df_col_calculated.iterrows():
            raw_name = row.get("name") or ""
            calc_name = str(raw_name).strip().strip("[]")
            if not calc_name:
                continue
            calculations.append(
                {
                    "name": calc_name,
                    "caption": row.get("caption"),
                    "formula": row.get("formula"),
                    "name_calc": f"[{calc_name}]",
                }
            )

    available_measures = []
    seen_measure_keys = set()
    if "name" in merged_df.columns:
        for _, row in merged_df.iterrows():
            deriv = str(row.get("derivation") or "").lower()
            local_type = str(row.get("local-type") or "").lower()
            name_token = str(row.get("name") or "")
            is_measure = deriv in {
                "sum",
                "avg",
                "average",
                "count",
                "countd",
                "cnt",
                "min",
                "max",
                "median",
            } or local_type in {"real", "integer", "numeric"} or any(
                tok in name_token.lower()
                for tok in ("sum:", "avg:", "cnt:", "cntd:", "ctd:", "count:")
            )
            if not is_measure:
                continue
            column = row.get("column") or row.get("local-name")
            if not column:
                continue
            key = (row.get("parent-name"), column, deriv)
            if key in seen_measure_keys:
                continue
            seen_measure_keys.add(key)
            available_measures.append(
                {
                    col_name: (None if pd.isna(value) else value)
                    for col_name, value in row.items()
                }
            )

    output = {
        "worksheets": worksheets_data,
        "calculations": calculations,
        "available_measures": available_measures,
    }

    # --- Save JSON ---
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output_json_path


if __name__ == "__main__":
    input_file = "C:\\Users\\User\\Desktop\\Kriyanshi\\Crg\\Tableau_to power_bi_migration_code\\Codes 2\\Codes\\Pie Chart_shailesh.twb"          # your Tableau file path
    output_file = "C:\\Users\\User\\Desktop\\Kriyanshi\\Crg\\Tableau_to power_bi_migration_code\\Codes 2\\Codes\\Pie Chart_shailesh.json"       # where JSON will be saved

    result = parse_tableau_to_json(input_file, output_file)
    print(f"JSON file generated at: {result}")
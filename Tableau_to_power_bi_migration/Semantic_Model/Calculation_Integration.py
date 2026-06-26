# ---------- Measures Helper Function ----------#

import xml.etree.ElementTree as ET
import json
import re
from openai import OpenAI
from typing import List, Dict, Any, Optional
from uuid import uuid4

# Initialize OpenAI client once (module level)
_client = None


def _get_openai_client(api_key: str = None):
    """Lazy initialization of OpenAI client."""
    global _client
    if _client is None and api_key:
        _client = OpenAI(api_key=api_key)
    return _client


def extract_calculated_fields(twb_file_path: str) -> List[Dict[str, str]]:
    """Extract calculated fields from Tableau TWB file."""
    tree = ET.parse(twb_file_path)
    root = tree.getroot()

    # Extract columns with calculations
    columns = {}
    for column in root.findall(".//column"):
        calc = column.find("calculation")
        if calc is not None:
            name = column.get("name", "")
            columns[name] = {
                "name": name,
                "caption": column.get("caption", ""),
                "formula": calc.get("formula", ""),
            }

    # Build name->caption mapping for replacements
    name_to_caption = {
        data["name"]: data["caption"]
        for data in columns.values()
        if data["name"] and data["caption"]
    }

    # Replace internal names with captions in formulas
    for data in columns.values():
        formula = data["formula"]
        for name, caption in name_to_caption.items():
            formula = formula.replace(name, caption)
        data["cleaned_formula"] = formula

    return list(columns.values())


def syntax_based_tableau_to_dax(formula: str, caption: str) -> Dict[str, Any]:
    """
    Fallback: Convert Tableau formula to DAX using syntax tree/pattern matching.
    """
    if not formula:
        return {"column_name": caption, "dax_query": ""}

    dax_formula = formula

    # Tableau to DAX function mappings
    conversions = {
        r"\bSUM\(": "SUM(",
        r"\bAVG\(": "AVERAGE(",
        r"\bCOUNT\(": "COUNT(",
        r"\bCOUNTD\(": "DISTINCTCOUNT(",
        r"\bMIN\(": "MIN(",
        r"\bMAX\(": "MAX(",
        r"\bIF\s+": "IF(",
        r"\bTHEN\b": ",",
        r"\bELSE\b": ",",
        r"\bEND\b": ")",
        r"\bAND\b": "&&",
        r"\bOR\b": "||",
        r"\bNOT\b": "NOT",
        r"\bCONTAINS\(": "CONTAINSSTRING(",
        r"\bLEFT\(": "LEFT(",
        r"\bRIGHT\(": "RIGHT(",
        r"\bLEN\(": "LEN(",
        r"\bLOWER\(": "LOWER(",
        r"\bUPPER\(": "UPPER(",
        r"\bTRIM\(": "TRIM(",
        r"\bYEAR\(": "YEAR(",
        r"\bMONTH\(": "MONTH(",
        r"\bDAY\(": "DAY(",
        r"\bDATE\(": "DATE(",
        r"\bDATEDIFF\(": "DATEDIFF(",
        r"\bDATEADD\(": "DATEADD(",
        r"\bTODAY\(\)": "TODAY()",
        r"\bNOW\(\)": "NOW()",
        r"\bROUND\(": "ROUND(",
        r"\bABS\(": "ABS(",
        r"\bCEILING\(": "CEILING(",
        r"\bFLOOR\(": "FLOOR(",
        r"\bPOWER\(": "POWER(",
        r"\bSQRT\(": "SQRT(",
        r"\bISNULL\(": "ISBLANK(",
        r"\bIFNULL\(": "IF(ISBLANK(",
        r"\bZN\(": "IF(ISBLANK(",
        r"\[([^\]]+)\]": r"[\1]",
    }

    for pattern, replacement in conversions.items():
        dax_formula = re.sub(pattern, replacement, dax_formula, flags=re.IGNORECASE)

    if "CASE" in dax_formula.upper():
        dax_formula = convert_case_to_switch(dax_formula)

    dax_formula = re.sub(r"\s+", " ", dax_formula).strip()

    return {
        "column_name": caption,
        "dax_query": dax_formula,
        "conversion_method": "syntax_based",
    }


def convert_case_to_switch(formula: str) -> str:
    """Convert Tableau CASE statements to DAX SWITCH."""
    case_pattern = r"CASE\s+(.*?)\s+END"
    match = re.search(case_pattern, formula, re.IGNORECASE | re.DOTALL)

    if not match:
        return formula

    case_body = match.group(1)
    when_then_pattern = r"WHEN\s+(.*?)\s+THEN\s+(.*?)(?=\s+WHEN|\s+ELSE|\s*$)"
    conditions = re.findall(when_then_pattern, case_body, re.IGNORECASE)
    else_pattern = r"ELSE\s+(.*?)$"
    else_match = re.search(else_pattern, case_body, re.IGNORECASE)
    else_value = else_match.group(1).strip() if else_match else "BLANK()"

    switch_parts = ["SWITCH(TRUE()"]
    for condition, value in conditions:
        switch_parts.append(f"{condition.strip()}, {value.strip()}")
    switch_parts.append(else_value)

    switch_statement = ", ".join(switch_parts) + ")"
    return formula[: match.start()] + switch_statement + formula[match.end() :]


def tableau_to_dax_llm(
    formula: str, caption: str, api_key: str = None
) -> Optional[Dict[str, Any]]:
    """Convert Tableau formula to DAX using GPT (with error handling)."""
    client = _get_openai_client(api_key)
    if not client:
        return None

    prompt = f"""Convert the following Tableau calculation to Power BI DAX.
Respond ONLY as valid JSON: {{"column_name": "<name>", "dax_query": "<DAX>"}}

Tableau Calculation:
Caption: {caption}
Formula: {formula}"""

    try:
        response = client.responses.create(model="gpt-4", input=prompt)
        output = response.output_text.strip()

        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            result["conversion_method"] = "llm"
            return result
        return None
    except Exception as e:
        print(f"⚠️ LLM conversion failed for {caption}: {e}")
        return None


def tableau_to_dax(
    formula: str, caption: str, use_llm: bool = True, api_key: str = None
) -> Dict[str, Any]:
    """Convert Tableau formula to DAX. Tries LLM first, falls back to syntax-based."""
    if use_llm:
        llm_result = tableau_to_dax_llm(formula, caption, api_key)
        if llm_result and llm_result.get("dax_query"):
            return llm_result
        print(f"🔄 Falling back to syntax-based conversion for: {caption}")

    return syntax_based_tableau_to_dax(formula, caption)


def convert_to_dax(
    calculated_fields: List[Dict], use_llm: bool = True, api_key: str = None
) -> List[Dict]:
    """Convert all Tableau calculations to DAX."""
    results = []
    llm_success = 0
    syntax_success = 0

    for calc in calculated_fields:
        caption = calc.get("caption", "")
        formula = calc.get("cleaned_formula", "")

        dax_result = tableau_to_dax(formula, caption, use_llm, api_key)
        results.append(dax_result)

        if dax_result.get("conversion_method") == "llm":
            llm_success += 1
        else:
            syntax_success += 1

    print(f"\n📊 Measure Conversion Summary:")
    print(f"   LLM conversions: {llm_success}")
    print(f"   Syntax-based conversions: {syntax_success}")
    print(f"   Total: {len(results)}")

    return results


def generate_measures_tmdl_content(dax_results: List[Dict]) -> str:
    """
    Generate TMDL-formatted measures content from DAX results.
    Returns a string that can be appended to table TMDL files.
    """
    if not dax_results:
        return ""

    measures_content = ""
    valid_count = 0

    for measure in dax_results:
        name = measure.get("column_name", "Unnamed_Measure")
        dax_query = measure.get("dax_query")

        if not dax_query:
            print(f"⚠️ Skipping measure '{name}' - no DAX query generated")
            continue

        dax_query = dax_query.strip()

        # Format as TMDL measure
        measures_content += f"\n\tmeasure '{name}' =\n"
        measures_content += f"\t\t{dax_query}\n"
        measures_content += f"\t\tlineageTag: {uuid4()}\n"
        measures_content += (
            f'\t\tannotation PBI_FormatHint = {{"isGeneralNumber":true}}\n'
        )

        valid_count += 1

    if valid_count > 0:
        print(f"✅ Generated {valid_count} measures for TMDL")

    return measures_content


# ---------- Main Helper Function for Excel Processor ----------#
def extract_and_generate_measures(
    twb_file: str, use_llm: bool = False, api_key: str = None
) -> str:
    """
    Extract calculated fields from TWB and convert to TMDL measures.
    This is the main helper function to be called from your Excel processor.

    Args:
        twb_file: Path to Tableau TWB file
        use_llm: Whether to use LLM for conversion (default: False for syntax-based only)
        api_key: OpenAI API key (required if use_llm=True)

    Returns:
        String containing TMDL-formatted measures that can be appended to table definitions
    """
    try:
        print("\n📊 Extracting calculated fields from TWB...")
        calculated_fields = extract_calculated_fields(twb_file)

        if not calculated_fields:
            print("ℹ️ No calculated fields found in TWB")
            return ""

        print(f"✅ Found {len(calculated_fields)} calculated field(s)")

        print(f"\n🔄 Converting to DAX (LLM {'enabled' if use_llm else 'disabled'})...")
        dax_results = convert_to_dax(calculated_fields, use_llm, api_key)

        print("\n💾 Generating TMDL measures content...")
        measures_tmdl = generate_measures_tmdl_content(dax_results)

        return measures_tmdl

    except Exception as e:
        print(f"❌ Error extracting measures: {e}")
        return ""

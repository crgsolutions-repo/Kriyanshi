import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, List
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from Semantic_Model.Semantic_utils import extract_table_names


# === XLSX Single Processor ===


# ---------- Backward Compatible Single-File Function ----------#
def process_xlsx_single(
    excel_path: str,
    output_dir: str,
    table_name: str = "Orders",
    write_local_date_table_tmdl=None,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    DEPRECATED: Use process_xlsx_multi() instead.
    Kept for backward compatibility.
    """
    # Create a simple TWB-like structure or call the multi processor
    file_info = {table_name: {"file_path": excel_path, "sheet_name": "Sheet1"}}

    # This is a simplified version - in reality you'd need actual TWB parsing
    print(
        "[!] Warning: process_xlsx_single is deprecated. Use process_xlsx_multi instead."
    )

    # For single file, we can't use the full multi-processor without a TWB file
    # Return empty metadata
    return "", []

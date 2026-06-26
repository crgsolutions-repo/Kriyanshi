import json
import os
import logging
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.Tableau_Parser import parse_tableau_to_json
from utils.visual_detection import (
    generate_random_id,
    detect_visual_type,
    process_visual,
)


def normalize_name(name):
    """Normalize names for case-insensitive, whitespace-tolerant comparison"""
    if not name:
        return ""
    return name.strip().lower()


def process_report(
    input_file: str,
    dashboard_data: list = None,
    selected_dashboard: str = None,
    selected_charts: list = None,
) -> str:
    """
    Converts a Tableau TWB file to Power BI-compatible JSON folder structure.

    Args:
        input_file (str): Path to the Tableau TWB file.
        dashboard_data (list, optional): Parsed dashboard layout data from parse_twb_dashboard().
        selected_dashboard (str, optional): Dashboard to process (if any).
        selected_charts (list, optional): Specific charts/worksheets to include.

    Returns:
        str: Path to the created report folder (definition/pages/...).
    """

    # --- Step 1: Convert Tableau TWB → JSON ---
    json_output_path = os.path.join(os.path.dirname(__file__), "temp_tableau.json")
    parse_tableau_to_json(input_file, json_output_path)

    if not os.path.exists(json_output_path):
        logging.error(f"JSON output file not found: {json_output_path}")
        return ""

    with open(json_output_path, "r", encoding="utf-8") as f:
        tableau_data = json.load(f)

    # --- Step 2: Setup output directories ---
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    definition_folder = os.path.join(desktop, "definition")
    # definition_folder = os.path.join(os.path.expanduser("~"), "Desktop", "Test.Report", "definition")
    pages_folder = os.path.join(definition_folder, "pages")
    os.makedirs(pages_folder, exist_ok=True)

    # =====================================================
    # === DASHBOARD MODE (if dashboard_data is provided) ===
    # =====================================================
    if dashboard_data:
        logging.info("🧩 Processing dashboards mode...")

        dashboards_to_process = []
        if selected_dashboard:
            dashboards_to_process = [
                d for d in dashboard_data if d["dashboard_name"] == selected_dashboard
            ]
        else:
            dashboards_to_process = dashboard_data

        page_order = []

        for dashboard in dashboards_to_process:
            dashboard_name = dashboard.get("dashboard_name", "Unnamed Dashboard")
            dashboard_id = generate_random_id()
            page_order.append(dashboard_id)

            dashboard_folder = os.path.join(pages_folder, dashboard_id)
            os.makedirs(dashboard_folder, exist_ok=True)

            # Create page.json
            page_json = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
                "name": dashboard_id,
                "displayName": dashboard_name,
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            }
            with open(
                os.path.join(dashboard_folder, "page.json"), "w", encoding="utf-8"
            ) as f_page:
                json.dump(page_json, f_page, indent=2)

            # Create visuals folder
            visuals_folder = os.path.join(dashboard_folder, "visuals")
            os.makedirs(visuals_folder, exist_ok=True)

            # Process charts
            charts = dashboard.get("charts", [])
            normalized_selected = {
                normalize_name(name) for name in selected_charts or []
            }
            logging.info(
                f"🔎 Selected charts for dashboard '{dashboard_name}': {selected_charts}"
            )
            if selected_charts:
                charts = [
                    ch
                    for ch in charts
                    if normalize_name(ch.get("chart_name")) in normalized_selected
                ]

            for chart in charts:
                chart_name = chart.get("chart_name", "Unnamed Chart")

                # Normalize chart name for matching
                chart_name_normalized = normalize_name(chart_name)

                # Try to find matching worksheet by both 'worksheet' and 'title' fields
                worksheet = next(
                    (
                        ws
                        for ws in tableau_data.get("worksheets", [])
                        if normalize_name(ws.get("worksheet")) == chart_name_normalized
                        or normalize_name(ws.get("title")) == chart_name_normalized
                    ),
                    None,
                )

                if not worksheet:
                    logging.warning(
                        f"⚠️ No matching worksheet found for chart '{chart_name}' in dashboard '{dashboard_name}'"
                    )
                    continue

                visual_type = detect_visual_type(worksheet)
                try:
                    visual_data = process_visual(
                        worksheet, visual_type, tableau_data=tableau_data
                    )
                except Exception as exc:
                    logging.error(
                        f"Failed to convert chart '{chart_name}' ({visual_type}): {exc}",
                        exc_info=True,
                    )
                    continue

                if not visual_data:
                    logging.warning(f"⚠️ No visual data for chart '{chart_name}'")
                    continue

                visuals = (
                    visual_data if isinstance(visual_data, list) else [visual_data]
                )

                for vis in visuals:
                    visual_id = generate_random_id()
                    visual_folder = os.path.join(visuals_folder, visual_id)
                    os.makedirs(visual_folder, exist_ok=True)

                    with open(
                        os.path.join(visual_folder, "visual.json"),
                        "w",
                        encoding="utf-8",
                    ) as f_out:
                        json.dump(vis, f_out, indent=2)

                    logging.info(
                        f"✅ Saved '{chart_name}' visual under dashboard '{dashboard_name}' → {visual_id}"
                    )

        # Write pages.json
        pages_json_content = {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": page_order,
            "activePageName": page_order[0] if page_order else None,
        }
        with open(
            os.path.join(pages_folder, "pages.json"), "w", encoding="utf-8"
        ) as f_pages:
            json.dump(pages_json_content, f_pages, indent=2)

        logging.info("✅ All dashboards processed successfully.")
        return pages_folder

    # =====================================================
    # === WORKSHEET MODE (default fallback) ===============
    # =====================================================
    logging.info("📊 Processing worksheets mode...")

    outer_folder_name = generate_random_id()
    outer_folder_path = os.path.join(pages_folder, outer_folder_name)
    os.makedirs(outer_folder_path, exist_ok=True)

    # page.json
    page_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
        "name": outer_folder_name,
        "displayName": "Page 1",
        "displayOption": "FitToPage",
        "height": 720,
        "width": 1280,
    }
    with open(
        os.path.join(outer_folder_path, "page.json"), "w", encoding="utf-8"
    ) as f_page:
        json.dump(page_json, f_page, indent=2)

    visuals_folder_path = os.path.join(outer_folder_path, "visuals")
    os.makedirs(visuals_folder_path, exist_ok=True)

    all_worksheet_names = [
        ws.get("worksheet", "Unnamed") for ws in tableau_data.get("worksheets", [])
    ]
    all_titles = [ws.get("title", "Unnamed") for ws in tableau_data.get("worksheets", [])]
    logging.info(f"📄 All worksheets found: {all_worksheet_names}")
    logging.info(f"📄 All worksheet titles found: {all_titles}")
    if selected_charts:
        logging.info(f"✅ Selected worksheets to process: {selected_charts}")
    normalized_selected = {
        normalize_name(name) for name in selected_charts or []
    }

    for worksheet in tableau_data.get("worksheets", []):
        title = worksheet.get("title", "Unnamed")
        worksheet_name = worksheet.get("worksheet", "Unnamed")

        # Check both title and worksheet name for selection
        if selected_charts and not (
            normalize_name(title) in normalized_selected
            or normalize_name(worksheet_name) in normalized_selected
        ):
            continue

        visual_type = detect_visual_type(worksheet)
        logging.info(
            f"📄 Processing worksheet: {worksheet_name} (title: {title}) → {visual_type}"
        )

        try:
            visual_data = process_visual(
                worksheet, visual_type, tableau_data=tableau_data
            )
        except Exception as exc:
            logging.error(
                f"Failed to convert worksheet '{worksheet_name}' ({visual_type}): {exc}",
                exc_info=True,
            )
            continue

        if not visual_data:
            logging.warning(f"No visual data returned for worksheet '{worksheet_name}'")
            continue

        visuals = visual_data if isinstance(visual_data, list) else [visual_data]
        for i, vis in enumerate(visuals):
            inner_folder_name = generate_random_id()
            inner_folder_path = os.path.join(visuals_folder_path, inner_folder_name)
            os.makedirs(inner_folder_path, exist_ok=True)
            with open(
                os.path.join(inner_folder_path, "visual.json"), "w", encoding="utf-8"
            ) as f_out:
                json.dump(vis, f_out, indent=2)
            logging.info(
                f"✅ Saved visual {i+1} at definition/pages/{outer_folder_name}/visuals/{inner_folder_name}/visual.json"
            )

    # pages.json
    pages_json_content = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [outer_folder_name],
        "activePageName": outer_folder_name,
    }
    with open(
        os.path.join(pages_folder, "pages.json"), "w", encoding="utf-8"
    ) as f_pages:
        json.dump(pages_json_content, f_pages, indent=2)

    logging.info(
        f"✅ Processing complete. All visuals saved under definition/pages/{outer_folder_name}/visuals/"
    )

    return outer_folder_path

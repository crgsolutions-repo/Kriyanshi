import os
import streamlit as st
import sys
import traceback
import json

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# === Imports ===
from utils.Process_Report import process_report
from Semantic_Model.Semantic_mode_Main import run_semantic_model
from utils.Mapper import extract_table_columns_mapping
from utils.Dashboard import parse_twb_dashboard
from utils.Worksheet_Name_Extarctor import extract_worksheet_names

# === Error Logging Helper ===
def log_detailed_error(e):
    tb = traceback.TracebackException.from_exception(e)
    for line in tb.format(chain=True):
        st.error(line)
    if tb.stack:
        last_frame = tb.stack[-1]
        st.error(
            f"Error in file '{last_frame.filename}', function '{last_frame.name}', line {last_frame.lineno}"
        )
    else:
        st.error("Could not extract detailed error location.")

# === Main App ===
def main():
    st.title("Tableau to PowerBI Migration Utility")

    st.markdown(
        """
        Upload your Tableau `.twb` file below, then select which process you want to run:
        - **Report Processing** → Convert Tableau visuals
        - **Semantic Model Generation** → Build Power BI TMDL model
        - **Run Both** → Do both in one go
        """
    )

    uploaded_file = st.file_uploader("📂 Upload Tableau TWB file", type=["twb"])

    if uploaded_file is not None:
        # Save uploaded file temporarily
        twb_temp_path = os.path.join("temp_uploads", uploaded_file.name)
        os.makedirs(os.path.dirname(twb_temp_path), exist_ok=True)
        with open(twb_temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"✅ File saved: {twb_temp_path}")

        # === Extract table-column mapping ===
        try:
            mapping = extract_table_columns_mapping(twb_temp_path)
        except Exception as e:
            st.warning("⚠️ Table mapping extraction failed.")
            log_detailed_error(e)
            mapping = {}

        # Mapping editing UI
        if mapping:
            st.subheader("🧩 Table & Column Mapping (Editable)")
            st.caption("Modify table or column names below for Power BI compatibility.")

            if "renamed_mapping" not in st.session_state:
                st.session_state.renamed_mapping = {}

            renamed_mapping = {}
            for table_name, columns in mapping.items():
                with st.expander(f"📄 Table: {table_name}", expanded=False):
                    new_table_name = st.text_input(
                        f"Rename Table '{table_name}'",
                        value=st.session_state.renamed_mapping.get(table_name, {}).get(
                            "__new_table_name__", table_name
                        ),
                        key=f"table_{table_name}",
                    )

                    renamed_mapping[new_table_name] = {
                        "__new_table_name__": new_table_name
                    }

                    for col in columns:
                        new_col_name = st.text_input(
                            f"Column '{col}'",
                            value=st.session_state.renamed_mapping.get(
                                table_name, {}
                            ).get(col, col),
                            key=f"{table_name}_{col}",
                        )
                        renamed_mapping[new_table_name][col] = new_col_name

            st.session_state.renamed_mapping = renamed_mapping

            st.download_button(
                "💾 Download Renamed Mapping JSON",
                data=json.dumps(renamed_mapping, indent=2),
                file_name="renamed_mapping.json",
                mime="application/json",
            )

        # === Dashboard extraction ===
        try:
            dashboards_data = parse_twb_dashboard(twb_temp_path)
        except Exception as e:
            dashboards_data = []
            st.warning("⚠️ Dashboard parsing failed. Try with a different TWB file.")
            log_detailed_error(e)

        if dashboards_data:
            st.subheader("📊 Dashboards and Chart Layouts")
            st.json(dashboards_data)

        # === Pipeline Options ===
        st.subheader("⚡ Conversion Pipeline Mode")
        pipeline_option = st.radio(
            "Choose dashboard processing:",
            [
                "Replicate dashboard layout (keep chart positions)",
                "Generate from selected worksheet(s) with random positions",
            ],
        )

        selected_dashboard = None
        selected_charts = []

        if (
            dashboards_data
            and pipeline_option == "Replicate dashboard layout (keep chart positions)"
        ):
            dashboard_names = ["All Dashboards"] + [
                db["dashboard_name"] for db in dashboards_data
            ]
            selected_dashboard = st.selectbox("Select Dashboard", dashboard_names)
            if selected_dashboard == "All Dashboards":
                selected_charts = []
            else:
                charts = [
                    ch["chart_name"]
                    for db in dashboards_data
                    if db["dashboard_name"] == selected_dashboard
                    for ch in db["charts"]
                ]
                selected_charts = st.multiselect(
                    "Select Charts to Convert (or leave blank for all)", charts
                )

        elif (
            pipeline_option
            == "Generate from selected worksheet(s) with random positions"
        ):
            try:
                worksheet_list = extract_worksheet_names(twb_temp_path)
                if not worksheet_list:
                    st.warning("⚠️ No worksheets found in the Tableau file.")
                else:
                    selected_charts = st.multiselect(
                        "Select Worksheet(s) to Convert", worksheet_list
                    )
            except Exception as e:
                st.error("❌ Failed to extract worksheet names.")
                log_detailed_error(e)

        # === Process Selection ===
        choice = st.radio(
            "Select process to run",
            ("Report Processing", "Semantic Model Generation", "Both"),
        )

        # === Semantic Model Configuration ===
        include_measures = True  # Only this is kept (no LLM)
        if choice in ["Semantic Model Generation", "Both"]:
            st.subheader("⚙️ Semantic Model Configuration")
            include_measures = st.checkbox(
                "Include calculated measures in semantic model",
                value=True,
                help="Convert Tableau calculated fields to Power BI measures",
            )
        # === Optional Folder Path Input ===
        st.subheader("📁 Definition Folder Setup")
        st.caption("Specify where you want to create the Definition folder.")
        definition_folder_path = st.text_input(
            "Enter folder path:",
            placeholder="e.g., C:/Users/YourName/Documents/PowerBI_Definition",
        )

        # === Run Button ===
        if st.button("▶️ Run"):
            try:
                report_output_dir = None

                # --- Report Processing ---
                if choice in ["Report Processing", "Both"]:
                    st.info("⚙️ Starting Report Processing...")

                    if (
                        pipeline_option
                        == "Replicate dashboard layout (keep chart positions)"
                    ):
                        if selected_dashboard == "All Dashboards":
                            all_output_dirs = []
                            for db in dashboards_data:
                                charts = [ch["chart_name"] for ch in db["charts"]]
                                output_dir = process_report(
                                    twb_temp_path,
                                    dashboard_data=dashboards_data,
                                    selected_dashboard=db["dashboard_name"],
                                    selected_charts=charts,
                                )
                                all_output_dirs.append(
                                    {
                                        "dashboard": db["dashboard_name"],
                                        "output_dir": output_dir,
                                    }
                                )
                            st.success(
                                f"✅ All dashboards converted. Output folders: {all_output_dirs}"
                            )

                        else:
                            report_output_dir = process_report(
                                twb_temp_path,
                                dashboard_data=dashboards_data,
                                selected_dashboard=selected_dashboard,
                                selected_charts=selected_charts,
                            )
                            st.success(
                                f"✅ Report Processing completed. Output folder: {report_output_dir}"
                            )

                    else:
                        report_output_dir = process_report(
                            twb_temp_path,
                            dashboard_data=None,
                            selected_dashboard=None,
                            selected_charts=selected_charts,
                        )
                        st.success(
                            f"✅ Report Processing completed. Output folder: {report_output_dir}"
                        )

                # --- Semantic Model Generation ---
                if choice in ["Semantic Model Generation", "Both"]:
                    st.info("⚙️ Starting Semantic Model Generation...")

                    semantic_params = {
                        "twb_file_path": twb_temp_path,
                        "include_measures": include_measures,
                    }

                    semantic_output_dir = run_semantic_model(**semantic_params)
                    st.success(f"✅ Semantic model created at: {semantic_output_dir}")

            except Exception as e:
                log_detailed_error(e)

    else:
        st.info("📌 Please upload a Tableau TWB file to begin.")

if __name__ == "__main__":
    main()
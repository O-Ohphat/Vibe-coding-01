import statistics
import time
from typing import Dict, List, Optional, Tuple, Any
import sqlite3
from typing import Dict, List, Optional
from pathlib import Path

import streamlit as st

# =====================================================================
# 1. DATA ACCESS LAYER (MODELS) - UNCHANGED BUSINESS LOGIC
# =====================================================================

class PatientModel:
    """Manages persistent patient data storage (SQLite) and initial data cleaning."""

    DB_PATH = Path("patients.db")

    _SEED_DATA: Dict[int, Dict[str, float]] = {
        101: {"Glucose": 95.0, "BMI": 22.5, "Age": 28.0, "BloodPressure": 115.0},
        102: {"Glucose": 145.0, "BMI": 0.0, "Age": 54.0, "BloodPressure": 135.0},
        103: {"Glucose": 112.0, "BMI": 29.1, "Age": 42.0, "BloodPressure": 122.0},
        104: {"Glucose": 180.0, "BMI": 36.4, "Age": 61.0, "BloodPressure": 142.0},
    }

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path) if db_path else str(self.DB_PATH)
        self._init_db()
        self._seed_if_empty()
        self._clean_initial_data()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id INTEGER PRIMARY KEY,
                    Glucose REAL NOT NULL,
                    BMI REAL NOT NULL,
                    Age REAL NOT NULL,
                    BloodPressure REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _seed_if_empty(self) -> None:
        with self._get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM patients").fetchone()["c"]
            if count == 0:
                conn.executemany(
                    """
                    INSERT INTO patients (patient_id, Glucose, BMI, Age, BloodPressure)
                    VALUES (:id, :Glucose, :BMI, :Age, :BloodPressure)
                    """,
                    [
                        {"id": pid, **metrics}
                        for pid, metrics in self._SEED_DATA.items()
                    ],
                )
                conn.commit()

    def _clean_initial_data(self) -> None:
        """Replace any non-positive BMI values with the median BMI across patients."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT patient_id, BMI FROM patients").fetchall()
            valid_bmis = [row["BMI"] for row in rows if row["BMI"] > 0]
            median_bmi = round(statistics.median(valid_bmis), 1) if valid_bmis else 25.0

            invalid_ids = [row["patient_id"] for row in rows if row["BMI"] <= 0]
            if invalid_ids:
                conn.executemany(
                    "UPDATE patients SET BMI = ? WHERE patient_id = ?",
                    [(median_bmi, pid) for pid in invalid_ids],
                )
                conn.commit()

    def get_all_ids(self) -> List[int]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT patient_id FROM patients ORDER BY patient_id ASC"
            ).fetchall()
        return [row["patient_id"] for row in rows]

    def get_patient(self, patient_id: int) -> Optional[Dict[str, float]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT Glucose, BMI, Age, BloodPressure FROM patients WHERE patient_id = ?",
                (patient_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "Glucose": row["Glucose"],
            "BMI": row["BMI"],
            "Age": row["Age"],
            "BloodPressure": row["BloodPressure"],
        }

    def update_patient(self, patient_id: int, updated_metrics: Dict[str, float]) -> bool:
        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT patient_id FROM patients WHERE patient_id = ?", (patient_id,)
            ).fetchone()
            if existing is None:
                return False

            columns = ", ".join(f"{col} = ?" for col in updated_metrics.keys())
            values = list(updated_metrics.values()) + [patient_id]
            conn.execute(
                f"UPDATE patients SET {columns} WHERE patient_id = ?", values
            )
            conn.commit()
        return True

# =====================================================================
# 2. BUSINESS LOGIC LAYER (SERVICE) - UNCHANGED
# =====================================================================
class ClinicalRiskService:
    """Handles clinical decision rules, point scoring, and risk categorization."""

    THRESHOLDS = {
        "Glucose": (100.0, 125.0),
        "BMI": (25.0, 29.9),
        "Age": (35.0, 55.0),
        "BloodPressure": (120.0, 130.0)
    }

    def calculate_metric_score(self, metric_name: str, value: float) -> int:
        if metric_name not in self.THRESHOLDS:
            return 0
        low_max, med_max = self.THRESHOLDS[metric_name]
        if value <= low_max:
            return 0
        elif value <= med_max:
            return 1
        return 2

    def evaluate_patient_risk(self, metrics: Dict[str, float]) -> Tuple[int, str]:
        total_score = sum(self.calculate_metric_score(m, v) for m, v in metrics.items())
        if total_score <= 2:
            category = "Low Risk"
        elif total_score <= 5:
            category = "Moderate Risk"
        else:
            category = "High Risk"
        return total_score, category


# =====================================================================
# 3. PRESENTATION LAYER (STREAMLIT VIEW)
# Replaces ConsoleView. Same responsibilities: layout, inputs, reports.
# =====================================================================
class StreamlitView:
    """Handles page layout, widget rendering, and structured reports for Streamlit."""

    @staticmethod
    def setup_page() -> None:
        st.set_page_config(page_title="Diabetes Risk Scoring System", page_icon="🩺", layout="centered")
        st.title("🩺 Diabetes Risk Scoring System")
        st.caption("Clinical decision-support tool for rapid diabetes risk categorization.")

    @staticmethod
    def display_patient_selector(ids: List[int]) -> Optional[int]:
        st.subheader("1. Select Patient")
        return st.selectbox("Available Patient IDs", options=ids, format_func=lambda x: f"Patient {x}")

    @staticmethod
    def display_error(message: str) -> None:
        st.error(f"[ERROR] {message}")

    @staticmethod
    def display_profile(patient_id: int, metrics: Dict[str, float]) -> None:
        st.subheader(f"2. Clinical Profile — Patient {patient_id}")
        cols = st.columns(len(metrics))
        for col, (metric, val) in zip(cols, metrics.items()):
            col.metric(label=metric, value=val)

    @staticmethod
    def prompt_metric_updates(metrics: Dict[str, float]) -> Dict[str, float]:
        st.subheader("3. Modify Metrics (optional)")
        updated_metrics = {}
        with st.form(key="metric_update_form"):
            for metric, current_val in metrics.items():
                updated_metrics[metric] = st.number_input(
                    label=metric,
                    value=float(current_val),
                    step=1.0,
                    format="%.1f",
                    key=f"input_{metric}"
                )
            submitted = st.form_submit_button("Calculate Risk Score")
        return updated_metrics if submitted else None

    @staticmethod
    def display_diagnostic_report(patient_id: int, score: int, category: str) -> None:
        st.subheader("4. Diagnostic Risk Report")
        color_map = {"Low Risk": "green", "Moderate Risk": "orange", "High Risk": "red"}
        badge_color = color_map.get(category, "blue")

        c1, c2 = st.columns(2)
        c1.metric("Cumulative Score", f"{score} pts")
        c2.markdown(
            f"**Risk Category:** :{badge_color}[{category.upper()}]"
        )
        st.progress(min(score, 8) / 8.0)


# =====================================================================
# 4. ORCHESTRATION LAYER (STREAMLIT CONTROLLER)
# Replaces ConsoleController. Same responsibilities: coordinate
# Model <-> Service <-> View, unchanged business logic calls.
# =====================================================================
class StreamlitController:
    """Coordinates interaction workflows between Model, Service, and Streamlit View."""

    def __init__(self, model: Any, service: ClinicalRiskService, view: StreamlitView):
        self.model = model
        self.service = service
        self.view = view

    def run(self) -> None:
        self.view.setup_page()

        valid_ids = self.model.get_all_ids()
        if not valid_ids:
            self.view.display_error("No patients found in the database.")
            return

        patient_id = self.view.display_patient_selector(valid_ids)
        patient_metrics = self.model.get_patient(patient_id)
        if not patient_metrics:
            self.view.display_error(f"Patient ID {patient_id} does not exist in the database.")
            return

        self.view.display_profile(patient_id, patient_metrics)

        updated_metrics = self.view.prompt_metric_updates(patient_metrics)
        if updated_metrics is not None:
            self.model.update_patient(patient_id, updated_metrics)
            patient_metrics = updated_metrics
            score, category = self.service.evaluate_patient_risk(patient_metrics)
            self.view.display_diagnostic_report(patient_id, score, category)
        else:
            st.info("Adjust metrics above and click **Calculate Risk Score** to generate a report.")


# =====================================================================
# SYSTEM APPLICATION ENTRY POINT (Streamlit)
# =====================================================================
# Use session_state so the in-memory model persists across Streamlit reruns
if "db_model" not in st.session_state:
    st.session_state.db_model = PatientModel()

db_model = st.session_state.db_model
rules_service = ClinicalRiskService()
ui_view = StreamlitView()

app = StreamlitController(model=db_model, service=rules_service, view=ui_view)
app.run()

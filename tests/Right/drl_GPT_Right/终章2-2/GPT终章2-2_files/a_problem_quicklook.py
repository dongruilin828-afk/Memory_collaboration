"""Five-minute quicklook for CUMCM 2026 Problem A attachments.

This script only audits inputs and runs a provisional radial finite-volume
baseline. It is not the final competition solver.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PROBLEM_DIR = ROOT.parents[2] / "CUMCM2026Problems" / "A题"
ATTACHMENTS = PROBLEM_DIR / "附件"
OUT = ROOT / "results" / "a_problem_quicklook.json"


def workbook_summary(path: Path) -> dict:
    book = pd.ExcelFile(path)
    result = {"file": path.name, "sheets": {}}
    for sheet in book.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet)
        result["sheets"][sheet] = {
            "shape": list(frame.shape),
            "columns": [str(column) for column in frame.columns],
            "head": frame.head(3).to_dict(orient="records"),
            "tail": frame.tail(3).to_dict(orient="records"),
        }
    return result


def load_numeric(path: Path, columns: int) -> np.ndarray:
    return pd.read_excel(path).iloc[:, :columns].apply(pd.to_numeric).to_numpy(float)


def step_field(u: np.ndarray, diffusivity: np.ndarray, dr: float, dt: float, transfer: float, ambient: float) -> np.ndarray:
    """Explicit cylindrical diffusion step on equally spaced radial nodes."""
    out = u.copy()
    d = diffusivity
    out[0] += dt * 4.0 * d[0] * (u[1] - u[0]) / dr**2
    r = np.arange(len(u), dtype=float) * dr
    for i in range(1, len(u) - 1):
        d_minus = 0.5 * (d[i] + d[i - 1])
        d_plus = 0.5 * (d[i] + d[i + 1])
        flux_plus = (r[i] + dr / 2) * d_plus * (u[i + 1] - u[i]) / dr
        flux_minus = (r[i] - dr / 2) * d_minus * (u[i] - u[i - 1]) / dr
        out[i] += dt * (flux_plus - flux_minus) / (r[i] * dr)
    out[-1] += dt * (
        2.0 * d[-1] * (u[-2] - u[-1]) / dr**2
        + 2.0 * transfer * (ambient - u[-1]) / dr
        + transfer * (ambient - u[-1]) / max(r[-1], dr)
    )
    return out


def run_baseline(ambient: np.ndarray, shrink: np.ndarray) -> dict:
    dr = 0.001
    dt = 1.0
    radii = np.arange(21) * dr
    sample_seconds = {100, 300, 600, 900, 1200, 1500, 1800, 1800 * 2, 1800 * 3, 1800 * 4, 1800 * 5, 1800 * 6}
    t_air = lambda t: float(np.interp(t, ambient[:, 0], ambient[:, 1]))
    c_air = lambda t: float(np.interp(t, ambient[:, 0], ambient[:, 2]))

    def simulate(variable: bool, shrinking: bool = False, limit: int = 10800):
        temperature = np.full(21, 28.0)
        moisture = np.full(21, 2.55)
        records = {}
        finish = None
        for second in range(1, limit + 1):
            if variable:
                rho = 650.0 + 128.0 * moisture
                cp = 1450.0 + 2736.0 * moisture / (moisture + 1.0)
                conductivity = 0.21 + 0.38 * moisture / (moisture + 1.0)
                moisture_d = 2.4e-3 * np.exp(-0.45 / moisture) * np.exp(-3850.0 / (temperature + 273.15))
            else:
                rho = np.full(21, 820.0)
                cp = np.full(21, 2600.0)
                conductivity = np.full(21, 0.36)
                moisture_d = 7e-9 * np.exp(-0.89 / moisture)
            radius = 0.02
            if shrinking:
                radius = float(np.interp(second, shrink[:, 0], shrink[:, 1])) / 100.0
                scale = (0.02 / radius) ** 2
            else:
                scale = 1.0
            thermal_d = conductivity / (rho * cp) * scale
            moisture_d = moisture_d * scale
            temperature = step_field(temperature, thermal_d, dr, dt, 25.0 / (rho[-1] * cp[-1]), t_air(second))
            moisture = step_field(moisture, moisture_d, dr, dt, 8e-7 * scale, c_air(second))
            moisture = np.maximum(moisture, 0.0)
            if second in sample_seconds:
                records[str(second)] = {
                    "temperature_C": np.round(temperature[[0, 5, 10, 15, 20]], 4).tolist(),
                    "moisture_kg_per_kg": np.round(moisture[[0, 5, 10, 15, 20]], 4).tolist(),
                }
            if finish is None and float(moisture.max()) < 0.15:
                finish = second
                break
        return records, finish, float(moisture.max()), float(radius)

    q1, _, _, _ = simulate(False, limit=1800)
    q23, finish3, max_c3, _ = simulate(True)
    q4, finish4, max_c4, radius4 = simulate(True, shrinking=True)
    # First-mode diffusion timescale, used only as an order-of-magnitude draft.
    d_reference = 2.4e-3 * np.exp(-0.45 / 0.15) * np.exp(-3850.0 / (50.165 + 273.15))
    timescale_h = (0.02**2 / (2.4048**2 * d_reference)) / 3600.0
    return {
        "radial_sample_cm": [0, 0.5, 1.0, 1.5, 2.0],
        "problem1": q1,
        "problem2_and_3": q23,
        "problem3_finish_h": None if finish3 is None else round(finish3 / 3600, 4),
        "problem3_max_moisture_at_stop": round(max_c3, 6),
        "problem4_finish_h_quasistatic": None if finish4 is None else round(finish4 / 3600, 4),
        "problem4_max_moisture_at_stop": round(max_c4, 6),
        "problem4_radius_at_stop_cm": round(radius4 * 100, 4),
        "draft_diffusion_timescale_h_at_C_0_15_T_50_165C": round(float(timescale_h), 3),
        "finish_time_note": "The 3 h run does not establish the drying endpoint. Use the timescale only to design the full 72 h simulation and convergence study.",
    }


def main() -> None:
    ambient = load_numeric(ATTACHMENTS / "附件1.xlsx", 3)
    shrink = load_numeric(ATTACHMENTS / "附件2.xlsx", 2)
    summaries = [
        workbook_summary(ATTACHMENTS / "附件1.xlsx"),
        workbook_summary(ATTACHMENTS / "附件2.xlsx"),
    ]
    templates = {}
    for path in sorted((ATTACHMENTS / "附件3").glob("result*.xlsx")):
        book = pd.ExcelFile(path)
        templates[path.name] = {
            sheet: list(pd.read_excel(path, sheet_name=sheet).shape)
            for sheet in book.sheet_names
        }

    payload = {
        "status": "quicklook_only",
        "problem_pdf": str(PROBLEM_DIR / "A题.pdf"),
        "attachments": summaries,
        "templates": templates,
        "draft_model": {
            "geometry": "axisymmetric radial cylinder, axial gradients neglected",
            "temperature": "rho*cp*dT/dt = (1/r)d/dr(k*r*dT/dr)",
            "moisture": "dC/dt = (1/r)d/dr(D*r*dC/dr)",
            "center_boundary": "zero radial flux",
            "surface_boundaries": [
                "-k*dT/dr = h*(T_surface-T_air)",
                "-D*dC/dr = hm*(C_surface-C_air)",
            ],
        },
        "baseline_results": run_baseline(ambient, shrink),
        "baseline_assumptions": [
            "Axial gradients and end-face heat/mass transfer are neglected.",
            "Attachment 1 temperature and moisture are linearly interpolated; after 14400 s the final values are held constant.",
            "Problem 4 uses a quasi-static normalized-radius diffusivity correction and omits the moving-grid advection term.",
            "The 1 s explicit scheme and Robin boundary discretization require convergence and sign/unit verification.",
        ],
        "warning": "All numbers are provisional baseline outputs, not submission-ready results. Validate convergence, boundary definitions, moving-boundary physics, and workbook templates before use.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

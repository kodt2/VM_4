from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

import plotly.graph_objects as go
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.templating import Jinja2Templates
from starlette.requests import Request

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BINARY_CANDIDATES = (
    PROJECT_ROOT / "build" / "poisson_sor",
    PROJECT_ROOT / "cmake-build-debug" / "poisson_sor",
    PROJECT_ROOT / "poisson_sor",
    PROJECT_ROOT / "solver",
    PROJECT_ROOT / "solver.exe",
)
MAX_SURFACE_AXIS_POINTS = int(os.getenv("MAX_SURFACE_AXIS_POINTS", "90"))

app = FastAPI(title="Poisson SOR Web UI", version="1.0.0")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")


class RectanglePayload(BaseModel):
    a: float = 0.0
    b: float = 1.0
    c: float = 0.0
    d: float = 1.0


class GridPayload(BaseModel):
    n: int = Field(20, ge=2, le=5000)
    m: int = Field(20, ge=2, le=5000)


class SorPayload(BaseModel):
    omega: float = Field(1.5, gt=0.0, lt=2.0)
    epsilon_mem: float = Field(1e-8, gt=0.0)
    max_iterations: int = Field(10000, ge=1)


class CalculatePayload(BaseModel):
    rectangle: RectanglePayload = Field(default_factory=RectanglePayload)
    grid: GridPayload = Field(default_factory=GridPayload)
    base: SorPayload = Field(default_factory=SorPayload)
    fine: SorPayload = Field(default_factory=lambda: SorPayload(omega=1.7, max_iterations=20000))
    variant: int = Field(1, ge=1, le=3)
    binary_path: str | None = None


def _default_binary_path() -> Path:
    env_binary_path = os.getenv("SOLVER_BINARY_PATH")
    if env_binary_path:
        return Path(env_binary_path).expanduser()

    for candidate in DEFAULT_BINARY_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_BINARY_CANDIDATES[0]


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    binary_path = _default_binary_path()
    if not binary_path.exists():
        raise HTTPException(status_code=503, detail=f"C++ solver binary is not available: {binary_path}")
    return {"ok": True, "solver_binary": str(binary_path), "solver_exists": True}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"default_binary_path": str(_default_binary_path())},
    )


@app.post("/api/calculate")
async def calculate(payload: CalculatePayload) -> dict[str, Any]:
    if not payload.rectangle.a < payload.rectangle.b or not payload.rectangle.c < payload.rectangle.d:
        raise HTTPException(status_code=422, detail="Требуется a < b и c < d")

    binary_path = Path(payload.binary_path or _default_binary_path()).expanduser()
    if not binary_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"C++ бинарник не найден: {binary_path}. Соберите проект CMake или укажите путь в форме.",
        )

    request_json = payload.model_dump(exclude={"binary_path"})
    solver_response = _run_solver(binary_path, request_json)
    if not solver_response.get("ok", False):
        raise HTTPException(status_code=400, detail=solver_response.get("error", "C++ solver returned an error"))

    solver_response["plots"] = _build_plotly_payload(solver_response)
    solver_response["log"] = _build_log(solver_response, binary_path)
    solver_response["plot_downsampling"] = {"max_axis_points": MAX_SURFACE_AXIS_POINTS}
    return solver_response


def _run_solver(binary_path: Path, request_json: dict[str, Any]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(binary_path)],
            input=json.dumps(request_json),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="C++ solver превысил лимит времени 120 секунд") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось запустить C++ solver: {exc}") from exc

    stdout = completed.stdout.strip()
    if not stdout:
        raise HTTPException(
            status_code=500,
            detail=f"C++ solver не вернул JSON. stderr: {completed.stderr.strip()}",
        )

    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Некорректный JSON от C++ solver: {exc}. stdout={stdout[:500]}",
        ) from exc

    if completed.returncode != 0 and response.get("ok", True):
        raise HTTPException(
            status_code=500,
            detail=f"C++ solver завершился с кодом {completed.returncode}. stderr: {completed.stderr.strip()}",
        )
    return response


def _build_plotly_payload(response: dict[str, Any]) -> dict[str, str]:
    base_grid = response["base"]["grid"]
    fine_grid = response["fine"]["grid"]
    nodes = response.get("nodes", [])
    initial = response.get("initial", {})

    plots = {
        "initial_base": _surface_figure_json(
            initial.get("base", []), base_grid, "value", "Начальное приближение v⁽⁰⁾", "Viridis"
        ),
        "initial_fine": _surface_figure_json(
            initial.get("fine", []), fine_grid, "value", "Начальное приближение v₂⁽⁰⁾", "Plasma"
        ),
        "solution_base": _surface_figure_json(
            _common_nodes_as_value(nodes, "base"), base_grid, "value", "Итоговое решение v⁽ᴺ⁾", "Viridis"
        ),
        "solution_fine": _surface_figure_json(
            _common_nodes_as_value(nodes, "fine"), base_grid, "value", "Итоговое решение v₂⁽ᴺ²⁾ на общих узлах", "Plasma"
        ),
        "difference": _surface_figure_json(
            _common_nodes_as_value(nodes, "difference"), base_grid, "value", "Разность v⁽ᴺ⁾ − v₂⁽ᴺ²⁾", "RdBu"
        ),
    }
    return plots


def _common_nodes_as_value(nodes: list[dict[str, Any]], key: Literal["base", "fine", "difference"]) -> list[dict[str, Any]]:
    return [{"i": node["i"], "j": node["j"], "x": node["x"], "y": node["y"], "value": node[key]} for node in nodes]


def _surface_figure_json(
    nodes: list[dict[str, Any]],
    grid: dict[str, Any],
    value_key: str,
    title: str,
    colorscale: str,
) -> str:
    x, y, z, stride_x, stride_y = _nodes_to_surface(nodes, int(grid["n"]), int(grid["m"]), value_key)
    surface = go.Surface(x=x, y=y, z=z, colorscale=colorscale, colorbar={"title": "u"})
    fig = go.Figure(data=[surface])
    suffix = "" if stride_x == 1 and stride_y == 1 else f" (прорежено: каждый {stride_x}-й i, каждый {stride_y}-й j)"
    fig.update_layout(
        title=f"{title}{suffix}",
        autosize=True,
        height=680,
        margin={"l": 0, "r": 0, "t": 52, "b": 0},
        scene={
            "xaxis_title": "x",
            "yaxis_title": "y",
            "zaxis_title": "u(x,y)",
            "camera": {"eye": {"x": 1.45, "y": 1.45, "z": 0.9}},
        },
    )
    return fig.to_json()


def _nodes_to_surface(
    nodes: list[dict[str, Any]],
    n: int,
    m: int,
    value_key: str,
) -> tuple[list[list[float]], list[list[float]], list[list[float]], int, int]:
    node_map = {(int(node["i"]), int(node["j"])): node for node in nodes}
    x_indices, stride_x = _sample_indices(n, MAX_SURFACE_AXIS_POINTS)
    y_indices, stride_y = _sample_indices(m, MAX_SURFACE_AXIS_POINTS)

    x_values: list[list[float]] = []
    y_values: list[list[float]] = []
    z_values: list[list[float]] = []
    for j in y_indices:
        x_row: list[float] = []
        y_row: list[float] = []
        z_row: list[float] = []
        for i in x_indices:
            node = node_map[(i, j)]
            x_row.append(float(node["x"]))
            y_row.append(float(node["y"]))
            z_row.append(float(node[value_key]))
        x_values.append(x_row)
        y_values.append(y_row)
        z_values.append(z_row)
    return x_values, y_values, z_values, stride_x, stride_y


def _sample_indices(max_index: int, max_axis_points: int) -> tuple[list[int], int]:
    stride = max(1, math.ceil((max_index + 1) / max_axis_points))
    indices = list(range(0, max_index + 1, stride))
    if indices[-1] != max_index:
        indices.append(max_index)
    return indices, stride


def _build_log(response: dict[str, Any], binary_path: Path) -> str:
    base = response["base"]
    fine = response["fine"]
    max_node = response["max_difference_node"]
    return "\n".join(
        [
            "Справка для основной задачи",
            f"C++ бинарник: {binary_path}",
            f"Вариант задачи: {response.get('variant')}",
            "",
            "Основная сетка:",
            f"  n={base['grid']['n']}, m={base['grid']['m']}, h={base['grid']['h']:.6e}, k={base['grid']['k']:.6e}",
            f"  Итераций N: {base['iterations']}",
            f"  ||R^(N)||_inf: {base['residual_norm']:.6e}",
            f"  epsilon^(N): {base['method_accuracy']:.6e}",
            f"  Сходимость: {'достигнута' if base['converged'] else 'не достигнута'}",
            "",
            "Половинная сетка:",
            f"  n2={fine['grid']['n']}, m2={fine['grid']['m']}, h2={fine['grid']['h']:.6e}, k2={fine['grid']['k']:.6e}",
            f"  Итераций N2: {fine['iterations']}",
            f"  ||R2^(N2)||_inf: {fine['residual_norm']:.6e}",
            f"  epsilon2_method^(N2): {fine['method_accuracy']:.6e}",
            f"  Сходимость: {'достигнута' if fine['converged'] else 'не достигнута'}",
            "",
            f"epsilon_2 = max|v - v2| на общих узлах: {response['epsilon2']:.6e}",
            f"Узел максимального отклонения: i={max_node['i']}, j={max_node['j']}, x={max_node['x']:.6e}, y={max_node['y']:.6e}",
        ]
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), reload=True)

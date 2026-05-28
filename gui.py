#!/usr/bin/env python3
"""PyQt6 GUI for the C++ Poisson SOR JSON CLI backend."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from matplotlib import pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_BINARY_CANDIDATES = (
    PROJECT_ROOT / "build" / "poisson_sor",
    PROJECT_ROOT / "poisson_sor",
    PROJECT_ROOT / "solver",
    PROJECT_ROOT / "solver.exe",
)


class SolverWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Poisson SOR Solver")
        self.resize(1180, 820)
        self.last_response: dict[str, Any] | None = None

        self.binary_path = QLineEdit(str(self._default_binary_path()))
        self.binary_path.setPlaceholderText("Path to poisson_sor / solver.exe")
        browse_button = QPushButton("Выбрать…")
        browse_button.clicked.connect(self._choose_binary)

        binary_layout = QHBoxLayout()
        binary_layout.addWidget(QLabel("C++ бинарник:"))
        binary_layout.addWidget(self.binary_path, stretch=1)
        binary_layout.addWidget(browse_button)

        self.a = self._double_box(0.0)
        self.b = self._double_box(1.0)
        self.c = self._double_box(0.0)
        self.d = self._double_box(1.0)
        geometry_group = self._form_group(
            "Геометрия области",
            [("a", self.a), ("b", self.b), ("c", self.c), ("d", self.d)],
        )

        self.n = self._int_box(20, minimum=2, maximum=2000)
        self.m = self._int_box(20, minimum=2, maximum=2000)
        grid_group = self._form_group("Основная сетка", [("n", self.n), ("m", self.m)])

        self.base_omega = self._double_box(1.5, minimum=0.000001, maximum=1.999999, decimals=6)
        self.base_epsilon = self._double_box(1e-8, minimum=1e-15, maximum=1.0, decimals=12)
        self.base_nmax = self._int_box(10000, minimum=1, maximum=100_000_000)
        base_group = self._form_group(
            "МВР: базовая сетка",
            [("omega", self.base_omega), ("epsilon", self.base_epsilon), ("N_max", self.base_nmax)],
        )

        self.fine_omega = self._double_box(1.7, minimum=0.000001, maximum=1.999999, decimals=6)
        self.fine_epsilon = self._double_box(1e-8, minimum=1e-15, maximum=1.0, decimals=12)
        self.fine_nmax = self._int_box(20000, minimum=1, maximum=100_000_000)
        fine_group = self._form_group(
            "МВР: сетка с половинным шагом",
            [("omega", self.fine_omega), ("epsilon", self.fine_epsilon), ("N_max", self.fine_nmax)],
        )

        self.variant = QComboBox()
        self.variant.addItem("Вариант 1: функции из C++ шаблона", 1)
        self.variant.addItem("Вариант 2: тест sin(pi*x)sin(pi*y)", 2)
        self.variant.addItem("Вариант 3: полиномиальные границы", 3)
        variant_group = self._form_group("Вариант задачи", [("variant", self.variant)])

        settings_grid = QGridLayout()
        settings_grid.addWidget(geometry_group, 0, 0)
        settings_grid.addWidget(grid_group, 0, 1)
        settings_grid.addWidget(variant_group, 0, 2)
        settings_grid.addWidget(base_group, 1, 0, 1, 2)
        settings_grid.addWidget(fine_group, 1, 2)

        self.calculate_button = QPushButton("Рассчитать")
        self.calculate_button.setMinimumHeight(42)
        self.calculate_button.clicked.connect(self.calculate)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Здесь появится аналитическая справка и JSON-диагностика…")

        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        table_controls = QHBoxLayout()
        self.table_data_kind = QComboBox()
        self.table_data_kind.addItem("v^(N)(x,y): основная сетка", "base")
        self.table_data_kind.addItem("v2^(N2)(x,y): половинный шаг", "fine")
        self.table_data_kind.addItem("v^(N)(x,y) - v2^(N2)(x,y)", "difference")
        self.table_data_kind.currentIndexChanged.connect(self._refresh_table)
        self.table_stride = QComboBox()
        for stride in (1, 2, 5, 10):
            self.table_stride.addItem(f"каждый {stride}-й узел", stride)
        self.table_stride.currentIndexChanged.connect(self._refresh_table)
        table_controls.addWidget(QLabel("Данные:"))
        table_controls.addWidget(self.table_data_kind)
        table_controls.addSpacing(16)
        table_controls.addWidget(QLabel("Прореживание:"))
        table_controls.addWidget(self.table_stride)
        table_controls.addStretch(1)
        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setCornerButtonEnabled(True)
        table_layout.addLayout(table_controls)
        table_layout.addWidget(self.result_table)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.log, "Справка")
        self.tabs.addTab(table_tab, "Таблица результатов")

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addLayout(binary_layout)
        main_layout.addLayout(settings_grid)
        main_layout.addWidget(self.calculate_button)
        main_layout.addWidget(self.tabs, stretch=1)
        self.setCentralWidget(central)
        self._set_table_corner_text()

    @staticmethod
    def _double_box(
        value: float,
        minimum: float = -1_000_000.0,
        maximum: float = 1_000_000.0,
        decimals: int = 8,
    ) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(minimum, maximum)
        box.setDecimals(decimals)
        box.setValue(value)
        box.setSingleStep(0.1)
        return box

    @staticmethod
    def _int_box(value: int, minimum: int, maximum: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    @staticmethod
    def _form_group(title: str, rows: list[tuple[str, QWidget]]) -> QGroupBox:
        group = QGroupBox(title)
        layout = QFormLayout(group)
        for label, widget in rows:
            layout.addRow(label, widget)
        return group

    @staticmethod
    def _default_binary_path() -> Path:
        for candidate in DEFAULT_BINARY_CANDIDATES:
            if candidate.exists():
                return candidate
        return DEFAULT_BINARY_CANDIDATES[0]

    def _choose_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите C++ solver binary", str(PROJECT_ROOT))
        if path:
            self.binary_path.setText(path)

    def _build_request(self) -> dict[str, Any]:
        return {
            "rectangle": {
                "a": self.a.value(),
                "b": self.b.value(),
                "c": self.c.value(),
                "d": self.d.value(),
            },
            "grid": {"n": self.n.value(), "m": self.m.value()},
            "base": {
                "omega": self.base_omega.value(),
                "epsilon": self.base_epsilon.value(),
                "N_max": self.base_nmax.value(),
            },
            "fine": {
                "omega": self.fine_omega.value(),
                "epsilon": self.fine_epsilon.value(),
                "N_max": self.fine_nmax.value(),
            },
            "variant": self.variant.currentData(),
        }

    def calculate(self) -> None:
        binary = Path(self.binary_path.text()).expanduser()
        if not binary.exists():
            QMessageBox.critical(self, "Ошибка", f"Бинарник не найден:\n{binary}")
            return

        request = self._build_request()
        self.log.setPlainText("Запуск C++ solver…\n\nВходной JSON:\n" + json.dumps(request, ensure_ascii=False, indent=2))
        QApplication.processEvents()

        try:
            completed = subprocess.run(
                [str(binary)],
                input=json.dumps(request),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Ошибка", "Расчет превысил лимит 300 секунд.")
            return
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка запуска", str(exc))
            return

        if completed.stderr.strip():
            self.log.append("\nSTDERR:\n" + completed.stderr)

        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.log.append("\nНекорректный stdout от C++ процесса:\n" + completed.stdout)
            QMessageBox.critical(self, "Ошибка JSON", f"Не удалось распарсить stdout: {exc}")
            return

        self.last_response = response
        self.log.setPlainText(self._format_report(request, response))
        if not response.get("ok", False):
            QMessageBox.critical(self, "Ошибка solver", response.get("error", "Неизвестная ошибка"))
            return

        self._refresh_table()
        self._plot_surfaces(response)

    @staticmethod
    def _format_report(request: dict[str, Any], response: dict[str, Any]) -> str:
        if not response.get("ok", False):
            return "Solver вернул ошибку:\n" + response.get("error", "Неизвестная ошибка")

        base = response["base"]
        fine = response["fine"]
        max_node = response["max_difference_node"]
        lines = [
            "Справка для основной задачи",
            "=" * 44,
            f"Вариант: {response['variant']}",
            f"Область: a={request['rectangle']['a']}, b={request['rectangle']['b']}, "
            f"c={request['rectangle']['c']}, d={request['rectangle']['d']}",
            "",
            "Базовая сетка:",
            f"  n={base['grid']['n']}, m={base['grid']['m']}, h={base['grid']['h']:.6e}, k={base['grid']['k']:.6e}",
            f"  Итераций: {base['iterations']}",
            f"  Невязка ||R^(N)||_inf: {base['residual_norm']:.6e}",
            f"  Точность метода epsilon^(N): {base['method_accuracy']:.6e}",
            f"  Сходимость: {'достигнута' if base['converged'] else 'не достигнута'}",
            "",
            "Сетка с половинным шагом:",
            f"  n={fine['grid']['n']}, m={fine['grid']['m']}, h={fine['grid']['h']:.6e}, k={fine['grid']['k']:.6e}",
            f"  Итераций: {fine['iterations']}",
            f"  Невязка ||R^(N)||_inf: {fine['residual_norm']:.6e}",
            f"  Точность метода epsilon^(N): {fine['method_accuracy']:.6e}",
            f"  Сходимость: {'достигнута' if fine['converged'] else 'не достигнута'}",
            "",
            f"epsilon_2 = {response['epsilon2']:.6e}",
            "Максимальное отклонение на общем узле: "
            f"i={max_node['i']}, j={max_node['j']}, x={max_node['x']:.6e}, y={max_node['y']:.6e}",
            f"Количество общих узлов в nodes: {len(response.get('nodes', []))}",
        ]
        return "\n".join(lines)

    def _refresh_table(self) -> None:
        if not self.last_response or not self.last_response.get("ok", False):
            return

        response = self.last_response
        n = int(response["base"]["grid"]["n"])
        m = int(response["base"]["grid"]["m"])
        stride = int(self.table_stride.currentData())
        value_key = str(self.table_data_kind.currentData())
        x_indices = self._sample_indices(n, stride)
        y_indices = self._sample_indices(m, stride)
        nodes_by_index = {(int(node["i"]), int(node["j"])): node for node in response.get("nodes", [])}

        self.result_table.setUpdatesEnabled(False)
        self.result_table.clear()
        self.result_table.setRowCount(len(y_indices))
        self.result_table.setColumnCount(len(x_indices))
        self.result_table.setHorizontalHeaderLabels(
            [f"x_{i}\n{nodes_by_index[(i, 0)]['x']:.6g}" for i in x_indices]
        )
        self.result_table.setVerticalHeaderLabels(
            [f"y_{j}\n{nodes_by_index[(0, j)]['y']:.6g}" for j in y_indices]
        )

        for row, j in enumerate(y_indices):
            for col, i in enumerate(x_indices):
                value = float(nodes_by_index[(i, j)][value_key])
                item = QTableWidgetItem(f"{value:.10e}")
                item.setToolTip(f"j={j}, i={i}, {value_key}={value:.12e}")
                self.result_table.setItem(row, col, item)

        self.result_table.resizeColumnsToContents()
        self.result_table.resizeRowsToContents()
        self.result_table.setUpdatesEnabled(True)
        self._set_table_corner_text()

    @staticmethod
    def _sample_indices(max_index: int, stride: int) -> list[int]:
        indices = list(range(0, max_index + 1, stride))
        if indices[-1] != max_index:
            indices.append(max_index)
        return indices

    def _set_table_corner_text(self) -> None:
        corner = self.result_table.findChild(QAbstractButton)
        if corner is not None:
            corner.setText("j / i")
            corner.setToolTip("Строки: y_j; столбцы: x_i")

    @staticmethod
    def _plot_surfaces(response: dict[str, Any]) -> None:
        surfaces = [
            ("Численное решение: основная сетка", SolverWindow._surface_from_common_nodes(response, "base"), "viridis"),
            (
                "Численное решение: половинный шаг (на общих узлах)",
                SolverWindow._surface_from_common_nodes(response, "fine"),
                "plasma",
            ),
            ("Разность: base - fine", SolverWindow._surface_from_common_nodes(response, "difference"), "coolwarm"),
            (
                "Начальное приближение: основная сетка",
                SolverWindow._surface_from_grid_nodes(response.get("initial", {}).get("base", []), response["base"]["grid"]),
                "viridis",
            ),
            (
                "Начальное приближение: половинный шаг",
                SolverWindow._surface_from_grid_nodes(response.get("initial", {}).get("fine", []), response["fine"]["grid"]),
                "plasma",
            ),
        ]

        for title, data, cmap in surfaces:
            if data is None:
                continue
            x, y, z = data
            fig = plt.figure(figsize=(9, 7))
            ax = fig.add_subplot(111, projection="3d")
            surface = ax.plot_surface(x, y, z, cmap=cmap, linewidth=0, antialiased=True)
            ax.set_title(title)
            ax.set_xlabel("x")
            ax.set_ylabel("y")
            ax.set_zlabel("u")
            fig.colorbar(surface, shrink=0.65, aspect=12)

        plt.show(block=False)

    @staticmethod
    def _surface_from_common_nodes(response: dict[str, Any], value_key: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        nodes = response.get("nodes", [])
        if not nodes:
            return None

        grid = response["base"]["grid"]
        return SolverWindow._surface_from_nodes(nodes, int(grid["n"]), int(grid["m"]), value_key)

    @staticmethod
    def _surface_from_grid_nodes(
        nodes: list[dict[str, Any]],
        grid: dict[str, Any],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        if not nodes:
            return None
        return SolverWindow._surface_from_nodes(nodes, int(grid["n"]), int(grid["m"]), "value")

    @staticmethod
    def _surface_from_nodes(
        nodes: list[dict[str, Any]],
        n: int,
        m: int,
        value_key: str,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = np.zeros((m + 1, n + 1))
        y = np.zeros((m + 1, n + 1))
        z = np.zeros((m + 1, n + 1))

        for node in nodes:
            i = int(node["i"])
            j = int(node["j"])
            x[j, i] = node["x"]
            y[j, i] = node["y"]
            z[j, i] = node[value_key]

        return x, y, z


def main() -> int:
    app = QApplication(sys.argv)
    window = SolverWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

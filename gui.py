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
        self.resize(1080, 760)

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

        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addLayout(binary_layout)
        main_layout.addLayout(settings_grid)
        main_layout.addWidget(self.calculate_button)
        main_layout.addWidget(self.log, stretch=1)
        self.setCentralWidget(central)

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

        self.log.setPlainText(self._format_report(request, response))
        if not response.get("ok", False):
            QMessageBox.critical(self, "Ошибка solver", response.get("error", "Неизвестная ошибка"))
            return

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

    @staticmethod
    def _plot_surfaces(response: dict[str, Any]) -> None:
        nodes = response.get("nodes", [])
        if not nodes:
            return

        n = int(response["base"]["grid"]["n"])
        m = int(response["base"]["grid"]["m"])
        x = np.zeros((m + 1, n + 1))
        y = np.zeros((m + 1, n + 1))
        base = np.zeros((m + 1, n + 1))
        fine = np.zeros((m + 1, n + 1))
        difference = np.zeros((m + 1, n + 1))

        for node in nodes:
            i = int(node["i"])
            j = int(node["j"])
            x[j, i] = node["x"]
            y[j, i] = node["y"]
            base[j, i] = node["base"]
            fine[j, i] = node["fine"]
            difference[j, i] = node["difference"]

        surfaces = [
            ("Численное решение: основная сетка", base, "viridis"),
            ("Численное решение: половинный шаг (на общих узлах)", fine, "plasma"),
            ("Разность: base - fine", difference, "coolwarm"),
        ]

        for title, z, cmap in surfaces:
            fig = plt.figure(figsize=(9, 7))
            ax = fig.add_subplot(111, projection="3d")
            surface = ax.plot_surface(x, y, z, cmap=cmap, linewidth=0, antialiased=True)
            ax.set_title(title)
            ax.set_xlabel("x")
            ax.set_ylabel("y")
            ax.set_zlabel("u")
            fig.colorbar(surface, shrink=0.65, aspect=12)

        plt.show(block=False)


def main() -> int:
    app = QApplication(sys.argv)
    window = SolverWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

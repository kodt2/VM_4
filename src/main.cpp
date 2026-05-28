#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

// -----------------------------------------------------------------------------
// Заглушки пользовательских функций.
// Замените тела этих функций на правую часть и граничные условия своей задачи.
// Уравнение: Delta u(x, y) = -f(x, y).
// -----------------------------------------------------------------------------

const double PI = 3,141592653589793;

double f(double x, double y) {
    return (sin( PI * x*y)) * sin( PI * x*y));
}

// x = a
double mu_1(double y) {
    return sin(PI*y);
}

// x = b
double mu_2(double y) {
   return sin(PI*y);
}

// y = c
double mu_3(double x) {
    return x-x*x;
}

// y = d
double mu_4(double x) {
    return x-x*x;
}

struct Rectangle {
    double a = 0.0;
    double b = 1.0;
    double c = 0.0;
    double d = 1.0;
};

struct SorParameters {
    double omega = 1.5;       // параметр верхней релаксации: 0 < omega < 2
    double epsilon_mem = 1e-8; // требуемая точность метода по норме поправки
    std::size_t max_iterations = 10000;
};

struct GridSize {
    std::size_t n = 20; // число разбиений по X
    std::size_t m = 20; // число разбиений по Y
};

struct SolveResult {
    GridSize grid;
    double h = 0.0;
    double k = 0.0;
    std::vector<double> values; // одномерное хранение узлов: index(i, j) = j*(n+1)+i
    std::size_t iterations = 0;
    double residual_norm = 0.0;     // ||R^(N)||_infinity
    double method_accuracy = 0.0;   // epsilon^(N): max |u_new - u_old| на последней итерации
    bool converged = false;
};

struct CommonGridDifference {
    double epsilon2 = 0.0;
    double x = 0.0;
    double y = 0.0;
    std::size_t i = 0;
    std::size_t j = 0;
};

class PoissonSolver {
public:
    using RightPart = std::function<double(double, double)>;
    using Boundary = std::function<double(double)>;

    PoissonSolver(Rectangle rectangle,
                  RightPart right_part,
                  Boundary left,
                  Boundary right,
                  Boundary bottom,
                  Boundary top)
        : rectangle_(rectangle),
          f_(std::move(right_part)),
          mu_left_(std::move(left)),
          mu_right_(std::move(right)),
          mu_bottom_(std::move(bottom)),
          mu_top_(std::move(top)) {
        if (!(rectangle_.a < rectangle_.b) || !(rectangle_.c < rectangle_.d)) {
            throw std::invalid_argument("Некорректная прямоугольная область");
        }
    }

    SolveResult solve(GridSize grid, SorParameters params) const {
        validate(grid, params);

        SolveResult result;
        result.grid = grid;
        result.h = (rectangle_.b - rectangle_.a) / static_cast<double>(grid.n);
        result.k = (rectangle_.d - rectangle_.c) / static_cast<double>(grid.m);
        result.values.assign((grid.n + 1) * (grid.m + 1), 0.0);

        initialize(result);

        for (std::size_t iteration = 1; iteration <= params.max_iterations; ++iteration) {
            const double correction_norm = sor_iteration(result, params.omega);
            result.iterations = iteration;
            result.method_accuracy = correction_norm;

            if (correction_norm <= params.epsilon_mem) {
                result.converged = true;
                break;
            }
        }

        result.residual_norm = residual_norm(result);
        return result;
    }

    double residual_norm(const SolveResult& result) const {
        const auto n = result.grid.n;
        const auto m = result.grid.m;
        const double h2_inv = 1.0 / (result.h * result.h);
        const double k2_inv = 1.0 / (result.k * result.k);
        const double diagonal = 2.0 * (h2_inv + k2_inv);

        double norm = 0.0;
        for (std::size_t j = 1; j < m; ++j) {
            const double y = y_coord(j, result.k);
            for (std::size_t i = 1; i < n; ++i) {
                const double x = x_coord(i, result.h);
                const double u = at(result, i, j);
                const double residual = diagonal * u
                    - h2_inv * (at(result, i - 1, j) + at(result, i + 1, j))
                    - k2_inv * (at(result, i, j - 1) + at(result, i, j + 1))
                    - f_(x, y);
                norm = std::max(norm, std::abs(residual));
            }
        }
        return norm;
    }

    CommonGridDifference compare_on_common_nodes(const SolveResult& coarse,
                                                 const SolveResult& fine) const {
        if (fine.grid.n != 2 * coarse.grid.n || fine.grid.m != 2 * coarse.grid.m) {
            throw std::invalid_argument("Вторая сетка должна иметь половинный шаг: (2n, 2m)");
        }

        CommonGridDifference diff;
        for (std::size_t j = 0; j <= coarse.grid.m; ++j) {
            for (std::size_t i = 0; i <= coarse.grid.n; ++i) {
                const double current = std::abs(at(coarse, i, j) - at(fine, 2 * i, 2 * j));
                if (current > diff.epsilon2) {
                    diff.epsilon2 = current;
                    diff.i = i;
                    diff.j = j;
                    diff.x = x_coord(i, coarse.h);
                    diff.y = y_coord(j, coarse.k);
                }
            }
        }
        return diff;
    }

private:
    static std::size_t index(const SolveResult& result, std::size_t i, std::size_t j) {
        return j * (result.grid.n + 1) + i;
    }

    static double at(const SolveResult& result, std::size_t i, std::size_t j) {
        return result.values[index(result, i, j)];
    }

    static double& at(SolveResult& result, std::size_t i, std::size_t j) {
        return result.values[index(result, i, j)];
    }

    void validate(GridSize grid, SorParameters params) const {
        if (grid.n < 2 || grid.m < 2) {
            throw std::invalid_argument("n и m должны быть не меньше 2");
        }
        if (!(params.omega > 0.0 && params.omega < 2.0)) {
            throw std::invalid_argument("Для МВР требуется 0 < omega < 2");
        }
        if (!(params.epsilon_mem > 0.0)) {
            throw std::invalid_argument("epsilon_mem должна быть положительной");
        }
        if (params.max_iterations == 0) {
            throw std::invalid_argument("N_max должен быть положительным");
        }
    }

    void initialize(SolveResult& result) const {
        const auto n = result.grid.n;
        const auto m = result.grid.m;

        // Сначала задаем все четыре стороны. Углы записываются повторно
        // согласованными значениями соответствующих граничных функций.
        for (std::size_t j = 0; j <= m; ++j) {
            const double y = y_coord(j, result.k);
            at(result, 0, j) = mu_left_(y);
            at(result, n, j) = mu_right_(y);
        }
        for (std::size_t i = 0; i <= n; ++i) {
            const double x = x_coord(i, result.h);
            at(result, i, 0) = mu_bottom_(x);
            at(result, i, m) = mu_top_(x);
        }

        // Начальное приближение во внутренних узлах: линейная интерполяция
        // между значениями на левой и правой сторонах при фиксированном y.
        for (std::size_t j = 1; j < m; ++j) {
            const double y = y_coord(j, result.k);
            const double left = mu_left_(y);
            const double right = mu_right_(y);
            for (std::size_t i = 1; i < n; ++i) {
                const double t = static_cast<double>(i) / static_cast<double>(n);
                at(result, i, j) = (1.0 - t) * left + t * right;
            }
        }
    }

    double sor_iteration(SolveResult& result, double omega) const {
        const auto n = result.grid.n;
        const auto m = result.grid.m;
        const double h2_inv = 1.0 / (result.h * result.h);
        const double k2_inv = 1.0 / (result.k * result.k);
        const double diagonal = 2.0 * (h2_inv + k2_inv);

        double correction_norm = 0.0;

        // In-place обход Гаусса--Зейделя: слева и снизу уже лежат значения
        // текущей итерации, справа и сверху — еще значения предыдущей итерации.
        for (std::size_t j = 1; j < m; ++j) {
            const double y = y_coord(j, result.k);
            for (std::size_t i = 1; i < n; ++i) {
                const double x = x_coord(i, result.h);
                const double old_value = at(result, i, j);
                const double gauss_seidel_value =
                    (h2_inv * (at(result, i - 1, j) + at(result, i + 1, j))
                     + k2_inv * (at(result, i, j - 1) + at(result, i, j + 1))
                     + f_(x, y))
                    / diagonal;
                const double new_value = old_value + omega * (gauss_seidel_value - old_value);

                at(result, i, j) = new_value;
                correction_norm = std::max(correction_norm, std::abs(new_value - old_value));
            }
        }

        return correction_norm;
    }

    double x_coord(std::size_t i, double h) const {
        return rectangle_.a + static_cast<double>(i) * h;
    }

    double y_coord(std::size_t j, double k) const {
        return rectangle_.c + static_cast<double>(j) * k;
    }

    Rectangle rectangle_;
    RightPart f_;
    Boundary mu_left_;
    Boundary mu_right_;
    Boundary mu_bottom_;
    Boundary mu_top_;
};

void print_result(const std::string& title, const SolveResult& result) {
    std::cout << title << '\n';
    std::cout << "Число итераций N = " << result.iterations << '\n';
    std::cout << "Невязка ||R^(N)||_inf = " << result.residual_norm << '\n';
    std::cout << "Норма поправки / точность метода epsilon^(N) = " << result.method_accuracy << '\n';
    std::cout << "Статус сходимости = " << (result.converged ? "достигнута" : "не достигнута") << '\n';
}

int main() {
    try {
        // ------------------------------------------------------------------
        // Входные параметры. При необходимости замените значения ниже или
        // добавьте чтение из файла/консоли.
        // ------------------------------------------------------------------
        const Rectangle rectangle{0.0, 1.0, 0.0, 1.0};
        const GridSize base_grid{20, 20};
        const SorParameters base_params{1.5, 1e-8, 10000};
        const SorParameters fine_params{1.7, 1e-8, 20000};

        const GridSize fine_grid{2 * base_grid.n, 2 * base_grid.m};

        PoissonSolver solver(rectangle, f, mu_1, mu_2, mu_3, mu_4);

        const SolveResult base_result = solver.solve(base_grid, base_params);
        const SolveResult fine_result = solver.solve(fine_grid, fine_params);
        const CommonGridDifference difference =
            solver.compare_on_common_nodes(base_result, fine_result);

        std::cout << std::scientific << std::setprecision(10);
        std::cout << "Справки для основной задачи" << '\n';
        std::cout << "----------------------------------------" << '\n';
        print_result("Базовая сетка (n, m)", base_result);
        std::cout << '\n';
        print_result("Сетка с половинным шагом (2n, 2m)", fine_result);
        std::cout << '\n';
        std::cout << "Точность решения основной задачи epsilon_2 = "
                  << difference.epsilon2 << '\n';
        std::cout << "Координаты максимального отклонения: x = " << difference.x
                  << ", y = " << difference.y << '\n';
        std::cout << "Индексы узла базовой сетки: i = " << difference.i
                  << ", j = " << difference.j << '\n';
    } catch (const std::exception& ex) {
        std::cerr << "Ошибка: " << ex.what() << '\n';
        return 1;
    }

    return 0;
}

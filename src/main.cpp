#include <algorithm>
#include <cmath>
#include <cstddef>
#include <functional>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

// -----------------------------------------------------------------------------
// Заглушки пользовательских функций.
// Замените тела этих функций на правую часть и граничные условия своей задачи.
// Уравнение: Delta u(x, y) = -f(x, y).
// -----------------------------------------------------------------------------

constexpr double PI = 3.14159265358979323846;

double f(double x, double y) {
    return std::sin(PI * x * y) * std::sin(PI * x * y);
}

// x = a
double mu_1(double y) {
    return std::sin(PI * y);
}

// x = b
double mu_2(double y) {
    return std::sin(PI * y);
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
    std::vector<double> initial_values; // значения после задания граничных условий и начальной интерполяции
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
        result.initial_values = result.values;

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


namespace {

using json = nlohmann::json;

struct SolverInput {
    Rectangle rectangle;
    GridSize base_grid;
    SorParameters base_params;
    SorParameters fine_params;
    std::size_t variant = 1;
};

struct ProblemFunctions {
    PoissonSolver::RightPart right_part;
    PoissonSolver::Boundary left;
    PoissonSolver::Boundary right;
    PoissonSolver::Boundary bottom;
    PoissonSolver::Boundary top;
};

double exact_variant_2(double x, double y) {
    return std::sin(PI * x) * std::sin(PI * y);
}

ProblemFunctions make_problem(std::size_t variant, const Rectangle& rectangle) {
    switch (variant) {
        case 1:
            return ProblemFunctions{f, mu_1, mu_2, mu_3, mu_4};
        case 2:
            // Delta u = -f, u = sin(pi*x)sin(pi*y) на границе.
            return ProblemFunctions{
                [](double x, double y) { return 2.0 * PI * PI * exact_variant_2(x, y); },
                [rectangle](double y) { return exact_variant_2(rectangle.a, y); },
                [rectangle](double y) { return exact_variant_2(rectangle.b, y); },
                [rectangle](double x) { return exact_variant_2(x, rectangle.c); },
                [rectangle](double x) { return exact_variant_2(x, rectangle.d); }};
        case 3:
            return ProblemFunctions{
                [](double x, double y) { return x * x + y * y; },
                [](double y) { return y * (1.0 - y); },
                [](double y) { return y * (1.0 - y); },
                [](double x) { return x * (1.0 - x); },
                [](double x) { return x * (1.0 - x); }};
        default:
            throw std::invalid_argument("Неизвестный номер варианта");
    }
}

std::size_t read_size(const json& object, const char* key) {
    if (!object.contains(key)) {
        throw std::invalid_argument(std::string("Отсутствует поле ") + key);
    }
    return object.at(key).get<std::size_t>();
}

double read_double(const json& object, const char* key) {
    if (!object.contains(key)) {
        throw std::invalid_argument(std::string("Отсутствует поле ") + key);
    }
    return object.at(key).get<double>();
}

SorParameters parse_params(const json& object) {
    SorParameters params;
    params.omega = read_double(object, "omega");
    if (object.contains("epsilon_mem")) {
        params.epsilon_mem = object.at("epsilon_mem").get<double>();
    } else {
        params.epsilon_mem = read_double(object, "epsilon");
    }
    if (object.contains("max_iterations")) {
        params.max_iterations = object.at("max_iterations").get<std::size_t>();
    } else {
        params.max_iterations = read_size(object, "N_max");
    }
    return params;
}

SolverInput parse_input(std::istream& input_stream) {
    json request;
    input_stream >> request;

    SolverInput input;
    const json& rectangle = request.at("rectangle");
    input.rectangle = Rectangle{
        read_double(rectangle, "a"),
        read_double(rectangle, "b"),
        read_double(rectangle, "c"),
        read_double(rectangle, "d")};

    const json& grid = request.at("grid");
    input.base_grid = GridSize{read_size(grid, "n"), read_size(grid, "m")};
    input.base_params = parse_params(request.at("base"));
    input.fine_params = parse_params(request.at("fine"));
    input.variant = request.value("variant", static_cast<std::size_t>(1));
    return input;
}

json result_to_json(const SolveResult& result) {
    return json{
        {"grid", {{"n", result.grid.n}, {"m", result.grid.m}, {"h", result.h}, {"k", result.k}}},
        {"iterations", result.iterations},
        {"residual_norm", result.residual_norm},
        {"method_accuracy", result.method_accuracy},
        {"converged", result.converged}};
}

json common_nodes_to_json(const Rectangle& rectangle,
                          const SolveResult& coarse,
                          const SolveResult& fine) {
    json nodes = json::array();
    nodes.get_ref<json::array_t&>().reserve((coarse.grid.n + 1) * (coarse.grid.m + 1));

    for (std::size_t j = 0; j <= coarse.grid.m; ++j) {
        const double y = rectangle.c + static_cast<double>(j) * coarse.k;
        for (std::size_t i = 0; i <= coarse.grid.n; ++i) {
            const double x = rectangle.a + static_cast<double>(i) * coarse.h;
            const double coarse_value = coarse.values[j * (coarse.grid.n + 1) + i];
            const double fine_value = fine.values[(2 * j) * (fine.grid.n + 1) + (2 * i)];
            nodes.push_back({
                {"i", i},
                {"j", j},
                {"x", x},
                {"y", y},
                {"base", coarse_value},
                {"fine", fine_value},
                {"difference", coarse_value - fine_value}});
        }
    }
    return nodes;
}


json grid_nodes_to_json(const Rectangle& rectangle,
                        const SolveResult& result,
                        bool use_initial_values) {
    const std::vector<double>& values = use_initial_values ? result.initial_values : result.values;
    if (values.size() != result.values.size()) {
        throw std::runtime_error("Внутренняя ошибка: массив начального приближения не заполнен");
    }

    json nodes = json::array();
    nodes.get_ref<json::array_t&>().reserve((result.grid.n + 1) * (result.grid.m + 1));

    for (std::size_t j = 0; j <= result.grid.m; ++j) {
        const double y = rectangle.c + static_cast<double>(j) * result.k;
        for (std::size_t i = 0; i <= result.grid.n; ++i) {
            const double x = rectangle.a + static_cast<double>(i) * result.h;
            nodes.push_back({
                {"i", i},
                {"j", j},
                {"x", x},
                {"y", y},
                {"value", values[j * (result.grid.n + 1) + i]}});
        }
    }
    return nodes;
}

json make_success_response(const SolverInput& input,
                           const SolveResult& base_result,
                           const SolveResult& fine_result,
                           const CommonGridDifference& difference) {
    return json{
        {"ok", true},
        {"variant", input.variant},
        {"rectangle", {{"a", input.rectangle.a}, {"b", input.rectangle.b}, {"c", input.rectangle.c}, {"d", input.rectangle.d}}},
        {"base", result_to_json(base_result)},
        {"fine", result_to_json(fine_result)},
        {"epsilon2", difference.epsilon2},
        {"max_difference_node", {{"i", difference.i}, {"j", difference.j}, {"x", difference.x}, {"y", difference.y}}},
        {"nodes", common_nodes_to_json(input.rectangle, base_result, fine_result)},
        {"initial", {{"base", grid_nodes_to_json(input.rectangle, base_result, true)},
                     {"fine", grid_nodes_to_json(input.rectangle, fine_result, true)}}}};
}

} // namespace

int main() {
    std::cout << std::scientific << std::setprecision(10);

    try {
        const SolverInput input = parse_input(std::cin);
        const GridSize fine_grid{2 * input.base_grid.n, 2 * input.base_grid.m};
        const ProblemFunctions problem = make_problem(input.variant, input.rectangle);

        PoissonSolver solver(input.rectangle,
                             problem.right_part,
                             problem.left,
                             problem.right,
                             problem.bottom,
                             problem.top);

        const SolveResult base_result = solver.solve(input.base_grid, input.base_params);
        const SolveResult fine_result = solver.solve(fine_grid, input.fine_params);
        const CommonGridDifference difference =
            solver.compare_on_common_nodes(base_result, fine_result);

        std::cout << make_success_response(input, base_result, fine_result, difference).dump();
    } catch (const std::exception& ex) {
        const json error = {{"ok", false}, {"error", ex.what()}};
        std::cout << error.dump();
        return 1;
    }

    return 0;
}

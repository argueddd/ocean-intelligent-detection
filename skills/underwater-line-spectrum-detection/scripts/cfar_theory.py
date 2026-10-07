"""CA/OS coefficient mathematics, NOT a signal detector or execution gateway.

Model: a CUT and N references are mutually independent, identically distributed
exponential powers. CA uses the reference mean; OS uses ascending, 1-based rank.
Every scientific argument is explicit. This module does not select a model for
real data, allocate frame/segment budgets, read files, calibrate, or find peaks.
"""

from dataclasses import dataclass
import math
import sys


IMPLEMENTATION_VERSION = "0.1.0"
MODEL = "iid_exponential_cut_and_references"
# Versioned numerical/resource bounds, not recommended detection parameters.
MAX_REFERENCES = 100_000
LOG_PROBABILITY_RELATIVE_TOLERANCE = 2e-13
LOG_PROBABILITY_ABSOLUTE_TOLERANCE = 5e-13
MAX_BISECTION_ITERATIONS = 128


class CFARParameterError(ValueError):
    """Explicit arguments are invalid or outside this implementation's bounds."""


class CFARNumericalError(ArithmeticError):
    """A finite coefficient cannot be verified within the numerical contract."""


@dataclass(frozen=True)
class TheoryCoefficient:
    method: str
    p_cell: float
    n_reference: int
    rank: int | None
    alpha: float
    reconstructed_log_pfa: float
    relative_log_probability_residual: float
    solver_iterations: int
    absolute_log_probability_residual: float
    model: str = MODEL
    implementation_version: str = IMPLEMENTATION_VERSION
    log_probability_relative_tolerance: float = LOG_PROBABILITY_RELATIVE_TOLERANCE
    log_probability_absolute_tolerance: float = LOG_PROBABILITY_ABSOLUTE_TOLERANCE


def _reference_count(value):
    if type(value) is not int or not 1 <= value <= MAX_REFERENCES:
        raise CFARParameterError(
            f"n_reference must be an explicit integer in [1, {MAX_REFERENCES}]"
        )
    return value


def _rank(value, n_reference):
    if type(value) is not int or not 1 <= value <= n_reference:
        raise CFARParameterError("rank must be an explicit 1-based integer in [1, N]")
    return value


def _finite_real(value, name):
    # No strings, bools, arrays, percentiles, or implicit JSON-type coercion.
    if type(value) not in (int, float):
        raise CFARParameterError(f"{name} must be a finite Python int or float")
    try:
        result = float(value)
    except OverflowError as exc:
        raise CFARParameterError(f"{name} is outside finite float range") from exc
    if not math.isfinite(result):
        raise CFARParameterError(f"{name} must be finite")
    return result


def _probability(value):
    result = _finite_real(value, "p_cell")
    if not 0.0 < result < 1.0:
        raise CFARParameterError("p_cell must lie strictly between 0 and 1")
    return result


def _alpha(value):
    result = _finite_real(value, "alpha")
    if result < 0:
        raise CFARParameterError("alpha must be nonnegative")
    return result


def _check_float_environment():
    if (sys.float_info.radix, sys.float_info.mant_dig, sys.float_info.max_exp) != (2, 53, 1024):
        raise CFARNumericalError("this implementation requires binary64 Python floats")


def _log1p_ratio(alpha, denominator):
    ratio = alpha / denominator
    if alpha > 0 and ratio < sys.float_info.min:
        raise CFARNumericalError("log probability ratio underflows normal binary64 range")
    return math.log1p(ratio)


def _ca_log_pfa(alpha, n_reference):
    return -n_reference * _log1p_ratio(alpha, n_reference)


def _os_log_pfa(alpha, n_reference, rank):
    result = -math.fsum(
        _log1p_ratio(alpha, denominator)
        for denominator in range(n_reference - rank + 1, n_reference + 1)
    )
    return result


def ca_log_pfa_iid_exponential(alpha, n_reference):
    """Return log(p_cell) for CA's reference MEAN, under the named model only."""
    _check_float_environment()
    return _ca_log_pfa(_alpha(alpha), _reference_count(n_reference))


def os_log_pfa_iid_exponential(alpha, n_reference, rank):
    """Return log(p_cell) for OS's ascending, 1-based reference order statistic."""
    _check_float_environment()
    n_reference = _reference_count(n_reference)
    return _os_log_pfa(_alpha(alpha), n_reference, _rank(rank, n_reference))


def _within_tolerance(log_pfa, target):
    residual = abs(log_pfa - target)
    return (residual <= LOG_PROBABILITY_ABSOLUTE_TOLERANCE
            and residual / abs(target) <= LOG_PROBABILITY_RELATIVE_TOLERANCE)


def _result(method, p_cell, n_reference, rank, alpha, log_pfa, iterations):
    target = math.log(p_cell)
    residual = abs(log_pfa - target) / abs(target)
    if not (math.isfinite(alpha) and alpha > 0 and math.isfinite(log_pfa)
            and _within_tolerance(log_pfa, target)):
        raise CFARNumericalError("coefficient did not pass finite-value/residual checks")
    return TheoryCoefficient(method, p_cell, n_reference, rank, alpha, log_pfa,
                             residual, iterations, abs(log_pfa - target))


def _positive_scaled_expm1(scale, exponent):
    try:
        result = scale * math.expm1(exponent)
    except OverflowError as exc:
        raise CFARNumericalError("coefficient exceeds finite binary64 range") from exc
    if not math.isfinite(result) or result <= 0:
        raise CFARNumericalError("coefficient is not positive and finite")
    return result


def ca_coefficient_iid_exponential(p_cell, n_reference):
    """Compute N*expm1(-log(p_cell)/N). No default p or reference count."""
    _check_float_environment()
    p_cell = _probability(p_cell)
    n_reference = _reference_count(n_reference)
    alpha = _positive_scaled_expm1(n_reference, -math.log(p_cell) / n_reference)
    return _result("CA", p_cell, n_reference, None, alpha,
                   _ca_log_pfa(alpha, n_reference), 0)


def os_coefficient_iid_exponential(p_cell, n_reference, rank):
    """Solve product[r/(r+alpha), r=N-k+1..N] = p_cell in log space.

    A deterministic bracket follows from
    sum(log1p(alpha/r)) >= k*log1p(alpha/N).
    Thus N*expm1(-log(p)/k) is a mathematical upper bound. No empirical
    coefficients or CA substitution are used on failure. k=1 has a closed form.
    """
    _check_float_environment()
    p_cell = _probability(p_cell)
    n_reference = _reference_count(n_reference)
    rank = _rank(rank, n_reference)
    target = math.log(p_cell)
    upper = _positive_scaled_expm1(n_reference, -target / rank)
    if rank == 1:
        return _result("OS", p_cell, n_reference, rank, upper,
                       _os_log_pfa(upper, n_reference, rank), 0)

    upper_log = _os_log_pfa(upper, n_reference, rank)
    if _within_tolerance(upper_log, target):
        return _result("OS", p_cell, n_reference, rank, upper, upper_log, 0)
    if upper_log > target:
        raise CFARNumericalError("OS upper bound could not be verified")

    lower = 0.0
    for iteration in range(1, MAX_BISECTION_ITERATIONS + 1):
        midpoint = lower + (upper - lower) / 2.0
        if midpoint == lower or midpoint == upper:
            raise CFARNumericalError("OS solver reached float resolution before tolerance")
        log_pfa = _os_log_pfa(midpoint, n_reference, rank)
        if _within_tolerance(log_pfa, target):
            return _result("OS", p_cell, n_reference, rank, midpoint, log_pfa, iteration)
        if log_pfa > target:
            lower = midpoint
        else:
            upper = midpoint
    raise CFARNumericalError("OS iteration limit reached; no fallback coefficient")

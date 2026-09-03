#!/usr/bin/env python3
"""Extract publication-ready values from the definitive v4.2 campaign.

The command is intentionally read-only and strict.  It accepts only the
frozen, complete 36-process campaign used by the first paper and writes one
deterministic JSON document to stdout.  Numeric fields are never rounded;
rounding is confined to the companion ``formatted`` strings.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore")
PRIMARY_PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4")
JCS_PROVIDERS = ("jcs321", "jcs4")
PHASES = ("initial", "redeploy")
ANALYSIS_SETS = ("primary-all-cycles", "sensitivity-without-cycle-1")

EXPECTED_CAMPAIGN_PREFIX = "article1-unified-v4-2"
EXPECTED_CAMPAIGN_ID_PATTERN = re.compile(
    rf"{re.escape(EXPECTED_CAMPAIGN_PREFIX)}-fb3f101b-\d{{8}}-\d{{6}}"
)
EXPECTED_PROTOCOL_VERSION = "4.2"
EXPECTED_PROTOCOL_PATH = "press/article/protocollo-campagna-v4-2.md"
EXPECTED_PROTOCOL_SHA256 = (
    "4f364de62f696c687d3175931f29c69013f4ad9d96303558e2444bfc5c73596f"
)
NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT = (
    "Nessuna deviazione dai parametri machine-verificabili del protocollo "
    "è registrata nel dataset"
)
EXPECTED_JCS4_COMMIT = "fb3f101b87709b713468e8d827b8612e6e65f29b"
EXPECTED_JCS321_SHA256 = (
    "12c6fe08223820089f60969b6088e6ac5d358aa872de78357585cdacb6c61049"
)
EXPECTED_RUNTIME_IMAGE_SHA256 = (
    "sha256:6d673ad42da6498f05755cae67f85f2128bdfd88943c9bdb22e0965f8d4c3182"
)
EXPECTED_BUILD_IMAGE_SHA256 = (
    "sha256:407c4423cec0cf2981055bc2c6c0dc211d9605b6669279b95997f2d1c7e91e2c"
)
EXPECTED_SCHEDULE_SEED = 2_482_026
EXPECTED_WILLIAMS_ROWS = (
    ("caffeine", "ehcache", "nostore", "cache2k", "jcs321", "jcs4"),
    ("ehcache", "cache2k", "caffeine", "jcs4", "nostore", "jcs321"),
    ("cache2k", "jcs4", "ehcache", "jcs321", "caffeine", "nostore"),
    ("jcs4", "jcs321", "cache2k", "nostore", "ehcache", "caffeine"),
    ("jcs321", "nostore", "jcs4", "caffeine", "cache2k", "ehcache"),
    ("nostore", "caffeine", "jcs321", "ehcache", "jcs4", "cache2k"),
)
EXPECTED_CONFIGURATION = {
    "entries": 10_000,
    "operations": 400_000,
    "threads": 8,
    "hitPercent": 95,
    "payloadBytes": 512,
    "warmupOperations": 50_000,
    "warmupSeconds": 3.0,
    "measurementSeconds": 5.0,
    "ttlSeconds": 300,
    "workload": "uniform",
    "writePercent": 10,
    "jcsMemoryMode": "strict",
    "seed": 24_301,
    "latencySampleRate": 64,
}

DISPLAY_NAMES = {
    "caffeine": "Caffeine 3.2.4",
    "ehcache": "Ehcache 3.12.0",
    "cache2k": "cache2k 2.6.1.Final",
    "jcs4": "snapshot JCS 4",
    "jcs321": "Apache Commons JCS 3.2.1",
    "nostore": "`no-store`",
}
PHASE_NAMES = {"initial": "Iniziale", "redeploy": "Redeploy"}

STAT_SUFFIXES = {
    "n": "N",
    "median": "Median",
    "mean": "Mean",
    "sampleStandardDeviation": "SampleStandardDeviation",
    "firstQuartile": "FirstQuartile",
    "thirdQuartile": "ThirdQuartile",
    "minimum": "Minimum",
    "maximum": "Maximum",
}


class ExtractionError(ValueError):
    """Raised when an input is not a frozen, complete v4.2 dataset."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExtractionError(message)


def require_sha256(value: Any, label: str) -> str:
    require(
        isinstance(value, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", value, re.IGNORECASE)),
        f"{label} must be a SHA-256 hex digest",
    )
    return value.lower()


def paired_request_seed(base_seed: int, schedule_seed: int,
                        block: int, cycle: int) -> int:
    material = (
        f"cache-benchmark-v4:base:{base_seed}:campaign:{schedule_seed}:"
        f"block:{block}:cycle:{cycle}"
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big") & 0x7fffffff


def json_equivalent(actual: Any, expected: Any, label: str) -> None:
    """Compare regenerated analysis while tolerating only insignificant float drift."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        require(type(actual) is type(expected) and actual == expected,
                f"{label} differs from analysis regenerated from raw data")
        return
    if (isinstance(actual, (int, float))
            and isinstance(expected, (int, float))):
        require(
            math.isclose(float(actual), float(expected),
                         rel_tol=1e-12, abs_tol=1e-9),
            f"{label} differs from analysis regenerated from raw data: "
            f"{actual!r} != {expected!r}",
        )
        return
    require(type(actual) is type(expected),
            f"{label} has type {type(actual).__name__}; expected "
            f"{type(expected).__name__}")
    if isinstance(actual, dict):
        require(set(actual) == set(expected),
                f"{label} has different object fields from regenerated analysis")
        for key in actual:
            json_equivalent(actual[key], expected[key], f"{label}.{key}")
        return
    if isinstance(actual, list):
        require(len(actual) == len(expected),
                f"{label} has a different array length from regenerated analysis")
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            json_equivalent(actual_item, expected_item, f"{label}[{index}]")
        return
    require(actual == expected,
            f"{label} differs from analysis regenerated from raw data")


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as failure:
        raise ExtractionError(f"cannot read {label} JSON {path}: {failure}") from failure
    require(isinstance(value, dict), f"{label} JSON must contain an object")
    reject_non_finite(value, label)
    return value


def reject_non_finite(value: Any, path: str) -> None:
    if isinstance(value, float):
        require(math.isfinite(value), f"non-finite number at {path}")
    elif isinstance(value, dict):
        for key, child in value.items():
            reject_non_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_non_finite(child, f"{path}[{index}]")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as failure:
        raise ExtractionError(f"cannot hash {path}: {failure}") from failure
    return digest.hexdigest()


def as_list(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def nested_dict(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def finite_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_workload_checkpoints(
    workload: dict[str, Any],
    validation: dict[str, Any],
    provider: str,
    request: dict[str, Any],
    label: str,
) -> None:
    """Validate the two v4.2 capacity checkpoints and their aggregate gate."""
    require(workload.get("configuration") == request,
            f"{label}: workload configuration differs from the cycle request")
    after_workload = nested_dict(
        workload.get("providerMetricsAfterWorkload"),
        f"{label}.providerMetricsAfterWorkload",
    )
    after_write = nested_dict(
        workload.get("providerMetricsAfterWriteProbe"),
        f"{label}.providerMetricsAfterWriteProbe",
    )
    legacy_alias = nested_dict(
        workload.get("providerMetrics"), f"{label}.providerMetrics"
    )
    require(legacy_alias == after_write,
            f"{label}: providerMetrics must equal the post-write checkpoint")

    hit_rate = after_workload.get("hitRate")
    entries_after_workload = after_workload.get("currentEntries")
    entries_after_write = after_write.get("currentEntries")
    require(finite_nonnegative_number(hit_rate) and float(hit_rate) <= 1.0,
            f"{label}: post-workload hit rate is missing or malformed")
    require(nonnegative_integer(entries_after_workload),
            f"{label}: post-workload entry count is missing or malformed")
    require(nonnegative_integer(entries_after_write),
            f"{label}: post-write entry count is missing or malformed")
    observed_hit_rate = float(hit_rate)

    requested_operations = request.get("operations")
    measured_operations = workload.get("measuredOperations")
    operations_per_second = workload.get("operationsPerSecond")
    require(isinstance(requested_operations, int)
            and not isinstance(requested_operations, bool)
            and requested_operations > 0,
            f"{label}: requested operation count is malformed")
    require(nonnegative_integer(measured_operations),
            f"{label}: measured operation count is malformed")
    operation_measurements_valid = (
        finite_nonnegative_number(operations_per_second)
        and float(operations_per_second) > 0.0
    )
    completed = (
        operation_measurements_valid
        and measured_operations >= requested_operations
    )
    require(validation.get("requiredOperations") == requested_operations
            and validation.get("measuredOperations") == measured_operations
            and validation.get("operationMeasurementsValid")
            is operation_measurements_valid
            and validation.get("completedOperations") is completed,
            f"{label}: completed-operations evidence is inconsistent")
    require(validation.get("providerMetricCheckpointsValid") is True,
            f"{label}: provider checkpoint validity flag is inconsistent")
    measurement_nanos = workload.get("measurementNanos")
    measurement_overshoot_nanos = workload.get("measurementOvershootNanos")
    requested_measurement_nanos = int(
        float(request.get("measurementSeconds", 0.0)) * 1_000_000_000
    )
    require(nonnegative_integer(measurement_nanos),
            f"{label}: measurementNanos is missing or malformed")
    require(nonnegative_integer(measurement_overshoot_nanos),
            f"{label}: measurementOvershootNanos is missing or malformed")
    expected_overshoot = max(0, measurement_nanos - requested_measurement_nanos)
    duration_passed = (
        requested_measurement_nanos == 0
        or measurement_nanos >= requested_measurement_nanos
    )
    require(
        validation.get("requestedMeasurementNanos") == requested_measurement_nanos
        and validation.get("observedMeasurementNanos") == measurement_nanos
        and validation.get("measurementDurationPassed") is duration_passed
        and measurement_overshoot_nanos == expected_overshoot,
        f"{label}: measurement-duration evidence is inconsistent",
    )
    loader_invocations = workload.get("loaderInvocationsUnderContention")
    single_flight_observed = workload.get("singleFlightPassed")
    require(nonnegative_integer(loader_invocations),
            f"{label}: loader invocation count is missing or malformed")
    require(
        isinstance(single_flight_observed, bool)
        and single_flight_observed is (loader_invocations == 1),
        f"{label}: single-flight result differs from loader invocation count",
    )
    if provider == "nostore":
        zero_hits = observed_hit_rate == 0.0
        no_entries_retained = (
            entries_after_workload == 0 and entries_after_write == 0
        )
        require(
            validation.get("gateType") == "no-store-control"
            and validation.get("performanceComparisonEligible") is False
            and validation.get("expectedStoredEntries") == 0
            and validation.get("observedEntriesAfterWorkload")
            == entries_after_workload
            and validation.get("capacityAfterWorkloadPassed")
            is (entries_after_workload == 0)
            and validation.get("observedEntriesAfterWriteProbe")
            == entries_after_write
            and validation.get("capacityAfterWriteProbePassed")
            is (entries_after_write == 0)
            and validation.get("capacityCheckPassed") is no_entries_retained
            and validation.get("noEntriesRetained") is no_entries_retained
            and validation.get("hitRate") == observed_hit_rate
            and validation.get("zeroHits") is zero_hits
            and validation.get("hitRateGateApplicable") is False
            and validation.get("singleFlightGateApplicable") is False,
            f"{label}: no-store checkpoint evidence is inconsistent",
        )
        expected_passed = (
            completed and duration_passed and no_entries_retained and zero_hits
        )
    else:
        expected_hit_rate = float(request["hitPercent"]) / 100.0
        hit_rate_passed = (
            str(request["workload"]).lower() != "uniform"
            or abs(observed_hit_rate - expected_hit_rate) <= 0.005
        )
        minimum_entries = int(int(request["entries"]) * 0.99)
        capacity_after_workload = entries_after_workload >= minimum_entries
        capacity_after_write = entries_after_write >= minimum_entries
        capacity_passed = capacity_after_workload and capacity_after_write
        single_flight = single_flight_observed
        require(
            validation.get("gateType") == "cache-semantics"
            and validation.get("expectedHitRate") == expected_hit_rate
            and validation.get("observedHitRate") == observed_hit_rate
            and validation.get("hitRateWithinHalfPercentagePoint")
            is hit_rate_passed
            and validation.get("minimumExpectedEntriesAfterWorkload")
            == minimum_entries
            and validation.get("minimumExpectedEntriesAfterWriteProbe")
            == minimum_entries
            and validation.get("observedEntriesAfterWorkload")
            == entries_after_workload
            and validation.get("capacityAfterWorkloadPassed")
            is capacity_after_workload
            and validation.get("observedEntriesAfterWriteProbe")
            == entries_after_write
            and validation.get("capacityAfterWriteProbePassed")
            is capacity_after_write
            and validation.get("capacityCheckPassed") is capacity_passed
            and validation.get("singleFlightPassed") is single_flight,
            f"{label}: cache checkpoint evidence is inconsistent",
        )
        expected_passed = (
            completed and duration_passed and hit_rate_passed
            and capacity_passed and single_flight
        )
    require(validation.get("passed") is expected_passed,
            f"{label}: aggregate semantic gate differs from its components")


POST_UNDEPLOY_TIMING_FIELDS = (
    "earlyThreadSecondsAfterUndeploy",
    "finalMeasurementSecondsAfterUndeploy",
    "earlyThreadTargetSecondsAfterUndeploy",
    "finalDiagnosticTargetSecondsAfterUndeploy",
    "earlyThreadStartedSecondsAfterUndeploy",
    "earlyThreadCompletedSecondsAfterUndeploy",
    "finalDiagnosticStartedSecondsAfterUndeploy",
    "findLeaksCompletedSecondsAfterUndeploy",
    "finalSnapshotCompletedSecondsAfterUndeploy",
)


def validate_post_undeploy_timing(
    value: Any,
    early_target: float,
    final_target: float,
    label: str,
) -> None:
    """Validate monotonic boundaries, allowing diagnostics to finish late."""
    timing = nested_dict(value, label)
    require(all(finite_nonnegative_number(timing.get(field))
                for field in POST_UNDEPLOY_TIMING_FIELDS),
            f"{label}: elapsed monotonic timing fields are incomplete")
    early_legacy = float(timing["earlyThreadSecondsAfterUndeploy"])
    final_legacy = float(timing["finalMeasurementSecondsAfterUndeploy"])
    recorded_early_target = float(
        timing["earlyThreadTargetSecondsAfterUndeploy"]
    )
    recorded_final_target = float(
        timing["finalDiagnosticTargetSecondsAfterUndeploy"]
    )
    early_started = float(timing["earlyThreadStartedSecondsAfterUndeploy"])
    early_completed = float(timing["earlyThreadCompletedSecondsAfterUndeploy"])
    final_started = float(timing["finalDiagnosticStartedSecondsAfterUndeploy"])
    findleaks_completed = float(timing["findLeaksCompletedSecondsAfterUndeploy"])
    final_completed = float(timing["finalSnapshotCompletedSecondsAfterUndeploy"])

    require(math.isclose(early_legacy, early_target)
            and math.isclose(recorded_early_target, early_target),
            f"{label}: early target differs from lifecycleProtocol")
    require(math.isclose(final_legacy, final_target)
            and math.isclose(recorded_final_target, final_target),
            f"{label}: final target differs from lifecycleProtocol")
    require(early_started >= recorded_early_target,
            f"{label}: early collection started before its target")
    require(early_completed >= early_started,
            f"{label}: early collection completed before it started")
    require(final_started >= recorded_final_target
            and final_started >= early_completed,
            f"{label}: final diagnostics started before their lower bounds")
    require(findleaks_completed >= final_started,
            f"{label}: findleaks completed before final diagnostics started")
    require(final_completed >= findleaks_completed,
            f"{label}: final snapshot completed before findleaks")


def italian_number(value: float | int | None, decimals: int = 3,
                   signed: bool = False) -> str:
    if value is None:
        return "n.d."
    number = float(value)
    if signed:
        text = f"{number:+.{decimals}f}"
    else:
        text = f"{number:.{decimals}f}"
    return text.replace(".", ",")


def italian_smart_number(value: float | int | None, decimals: int = 3,
                         signed: bool = False) -> str:
    if value is None:
        return "n.d."
    number = float(value)
    if number.is_integer():
        return f"{int(number):+d}" if signed else str(int(number))
    text = italian_number(number, decimals, signed=signed)
    while text.endswith("0"):
        text = text[:-1]
    if text.endswith(","):
        text = text[:-1]
    return text


def italian_integer(value: int) -> str:
    require(nonnegative_integer(value), "integer to format must be non-negative")
    return f"{value:,}".replace(",", ".")


def denominator(numerator: int, denominator_value: int) -> str:
    return f"{numerator}/{denominator_value}"


def range_text(stats: dict[str, Any], decimals: int = 3,
               smart: bool = False, signed: bool = False) -> str:
    formatter = italian_smart_number if smart else italian_number
    return (
        f"{formatter(stats['minimum'], decimals, signed=signed)}–"
        f"{formatter(stats['maximum'], decimals, signed=signed)}"
    )


def quartile_text(stats: dict[str, Any], decimals: int = 3,
                  smart: bool = False, signed: bool = False) -> str:
    formatter = italian_smart_number if smart else italian_number
    return (
        f"{formatter(stats['firstQuartile'], decimals, signed=signed)}–"
        f"{formatter(stats['thirdQuartile'], decimals, signed=signed)}"
    )


def median_range_text(stats: dict[str, Any], decimals: int = 3,
                      smart: bool = False, signed: bool = False) -> str:
    formatter = italian_smart_number if smart else italian_number
    return (
        f"{formatter(stats['median'], decimals, signed=signed)} "
        f"[{range_text(stats, decimals, smart=smart, signed=signed)}]"
    )


def interpolated_quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def descriptive(values: Iterable[float | int]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {
            "n": 0,
            "median": None,
            "mean": None,
            "sampleStandardDeviation": None,
            "firstQuartile": None,
            "thirdQuartile": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "n": len(numbers),
        "median": statistics.median(numbers),
        "mean": statistics.mean(numbers),
        "sampleStandardDeviation": statistics.stdev(numbers)
        if len(numbers) > 1 else None,
        "firstQuartile": interpolated_quantile(numbers, 0.25),
        "thirdQuartile": interpolated_quantile(numbers, 0.75),
        "minimum": min(numbers),
        "maximum": max(numbers),
    }


def stats_from_row(row: dict[str, Any], prefix: str,
                   scale: float = 1.0) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for output_name, suffix in STAT_SUFFIXES.items():
        key = f"{prefix}{suffix}"
        require(key in row, f"analysis row lacks {key}")
        value = row[key]
        if output_name == "n":
            require(isinstance(value, int), f"{key} must be an integer")
            output[output_name] = value
        else:
            require(value is None or isinstance(value, (int, float)),
                    f"{key} must be numeric or null")
            output[output_name] = None if value is None else float(value) / scale
    return output


def scaled_stats(stats: dict[str, Any], scale: float) -> dict[str, Any]:
    return {
        key: value if key == "n" or value is None else float(value) / scale
        for key, value in stats.items()
    }


def list_count(value: Any, label: str) -> int:
    return len(as_list(value, label))


def validate_findleaks_snapshot(snapshot: dict[str, Any], provider: str,
                                label: str) -> bool:
    occurrences = as_list(snapshot.get("tomcatFindLeaksOccurrences"),
                          f"{label}.tomcatFindLeaksOccurrences")
    require(all(isinstance(item, str) and item.startswith("/")
                for item in occurrences),
            f"{label}: malformed Tomcat findleaks occurrence")
    require(snapshot.get("tomcatFindLeaksOccurrenceCount") == len(occurrences),
            f"{label}: findleaks occurrence count differs from the preserved list")
    counts = nested_dict(
        snapshot.get("tomcatFindLeaksOccurrenceCountsByContext"),
        f"{label}.tomcatFindLeaksOccurrenceCountsByContext",
    )
    require(counts == dict(Counter(occurrences)),
            f"{label}: findleaks per-context counts differ from occurrences")
    contexts = as_list(snapshot.get("tomcatFindLeaksContexts"),
                       f"{label}.tomcatFindLeaksContexts")
    require(contexts == list(dict.fromkeys(occurrences)),
            f"{label}: findleaks context list differs from occurrences")
    require(snapshot.get("tomcatFindLeaksDetected") is bool(occurrences),
            f"{label}: findleaks detection boolean differs from occurrences")
    return f"/{provider}" in contexts


def campaign_prefix_from_run_id(run_id: str) -> str:
    match = re.fullmatch(
        r"(.+)-default-f(?:0[1-6])-p[1-6]-(caffeine|ehcache|cache2k|jcs4|jcs321|nostore)",
        run_id,
    )
    require(match is not None, f"unexpected processRunId format: {run_id!r}")
    return match.group(1)


def campaign_id_from_results_path(results_path: Path) -> str:
    suffix = "-results.json"
    require(results_path.name.endswith(suffix),
            f"results filename must end with {suffix}")
    campaign_id = results_path.name[:-len(suffix)]
    require(EXPECTED_CAMPAIGN_ID_PATTERN.fullmatch(campaign_id) is not None,
            "results filename does not identify a frozen v4.2 campaign with "
            "the expected JCS4 commit")
    return campaign_id


def artifact_manifest_map(value: Any, label: str) -> dict[str, str]:
    rows = as_list(value, label)
    result: dict[str, str] = {}
    for index, item in enumerate(rows):
        row = nested_dict(item, f"{label}[{index}]")
        path = row.get("containerPath")
        require(isinstance(path, str) and path.startswith("/artifacts/"),
                f"{label}[{index}].containerPath is invalid")
        require(path not in result, f"{label} repeats {path}")
        result[path] = require_sha256(row.get("sha256"),
                                      f"{label}[{index}].sha256")
    return result


def validate_analysis_regeneration(
    raw: dict[str, Any],
    analysis: dict[str, Any],
    source_files: list[dict[str, Any]],
) -> None:
    """Prove that every derived table still matches the frozen runner formulae."""
    runner_rows = [
        item for item in source_files
        if item.get("path") == "scripts/run_benchmark.py"
    ]
    require(len(runner_rows) == 1,
            "source manifest must identify scripts/run_benchmark.py exactly once")
    runner_path = Path(__file__).resolve().with_name("run_benchmark.py")
    require(runner_path.is_file(),
            f"frozen analysis runner is unavailable at {runner_path}")
    require(
        sha256_file(runner_path) == runner_rows[0]["sha256"].lower(),
        "local run_benchmark.py differs from the runner recorded by the campaign",
    )
    try:
        spec = importlib.util.spec_from_file_location(
            "_paper_v4_2_frozen_runner", runner_path
        )
        require(spec is not None and spec.loader is not None,
                "cannot load frozen run_benchmark.py")
        runner = importlib.util.module_from_spec(spec)
        previous_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(runner)
        finally:
            sys.dont_write_bytecode = previous_dont_write_bytecode
        regenerated = runner.analyse(raw)
    except ExtractionError:
        raise
    except Exception as failure:
        raise ExtractionError(
            f"cannot regenerate analysis with frozen runner: {failure}"
        ) from failure

    require(isinstance(regenerated, dict),
            "frozen runner did not regenerate an analysis object")
    require(set(analysis) == set(regenerated),
            "analysis fields differ from a fresh derivation from raw data")
    require(isinstance(analysis.get("generatedAt"), str)
            and bool(analysis["generatedAt"]),
            "analysis.generatedAt is missing")
    for key in analysis:
        if key != "generatedAt":
            json_equivalent(
                analysis[key], regenerated[key], f"analysis.{key}"
            )


def validate_inputs(raw: dict[str, Any], analysis: dict[str, Any],
                    results_path: Path, analysis_path: Path) -> str:
    campaign_id = campaign_id_from_results_path(results_path)
    expected_results_name = f"{campaign_id}-results.json"
    expected_analysis_name = f"{campaign_id}-analysis.json"
    require(results_path.name == expected_results_name,
            f"results filename must be {expected_results_name}")
    require(analysis_path.name == expected_analysis_name,
            f"analysis filename must be {expected_analysis_name}")
    require(results_path.parent == analysis_path.parent,
            "results and analysis JSON must be siblings in the campaign bundle")
    require(raw.get("analysisFile") == expected_analysis_name,
            "results.analysisFile does not identify the definitive analysis")
    analysis_sha = sha256_file(analysis_path)
    require(raw.get("analysisSha256") == analysis_sha,
            "analysis SHA-256 does not match results.analysisSha256")

    require(raw.get("schemaVersion") == 4, "results schemaVersion must be 4")
    require(analysis.get("schemaVersion") == 4, "analysis schemaVersion must be 4")
    require(raw.get("protocolVersion") == EXPECTED_PROTOCOL_VERSION,
            "results protocolVersion must be 4.2")
    require(analysis.get("protocolVersion") == EXPECTED_PROTOCOL_VERSION,
            "analysis protocolVersion must be 4.2")
    require(raw.get("providers") == list(PROVIDERS),
            "provider list/order differs from the frozen campaign")
    require(raw.get("forks") == 6, "campaign must declare six forks")
    require(raw.get("cyclesPerProcessRun") == 5,
            "campaign must declare five cycles per JVM")
    require(raw.get("configuration") == EXPECTED_CONFIGURATION,
            "campaign configuration differs from frozen v4.2")
    require(raw.get("infrastructureFailures") == [],
            "campaign contains infrastructure failures")
    require(raw.get("invalidBlocks", []) == [],
            "results contain invalid Williams blocks")
    require(analysis.get("invalidBlocks") == [],
            "analysis contains invalid Williams blocks")
    require(analysis.get("rankingProduced") is False,
            "analysis must not produce a ranking")
    require(bool(raw.get("campaignStartedAt")) and bool(raw.get("campaignFinishedAt")),
            "campaign start and finish timestamps are required")
    diagnostic_archive = nested_dict(
        raw.get("diagnosticArchive"), "results.diagnosticArchive"
    )
    diagnostic_name = diagnostic_archive.get("file")
    require(isinstance(diagnostic_name, str)
            and Path(diagnostic_name).name == diagnostic_name,
            "diagnostic archive must be a sibling filename")
    diagnostic_path = results_path.parent / diagnostic_name
    require(diagnostic_path.is_file(),
            f"diagnostic archive is missing: {diagnostic_path}")
    require(isinstance(diagnostic_archive.get("sizeBytes"), int)
            and diagnostic_archive["sizeBytes"] == diagnostic_path.stat().st_size,
            "diagnostic archive size differs from recorded metadata")
    require_sha256(diagnostic_archive.get("sha256"),
                   "results.diagnosticArchive.sha256")
    require(sha256_file(diagnostic_path) == diagnostic_archive["sha256"].lower(),
            "diagnostic archive SHA-256 differs from recorded metadata")

    matrix = nested_dict(raw.get("matrix"), "results.matrix")
    expected_matrix = {
        "threads": [8],
        "hitPercent": [95],
        "workloads": ["uniform"],
        "jcsMemoryModes": ["strict"],
    }
    require(matrix == expected_matrix, "scenario matrix differs from frozen v4.2")

    protocol = nested_dict(raw.get("lifecycleProtocol"), "lifecycleProtocol")
    require(protocol.get("freshContainerPerProcessRun") is True,
            "fresh-container protocol is not declared")
    require(protocol.get("redeployExecutesSameSeededFullWorkload") is True,
            "redeploy does not declare the same seeded workload")
    require(protocol.get("earlyThreadObservationSeconds") == 2.0,
            "early lifecycle checkpoint must be 2 seconds")
    require(protocol.get("finalObservationAndFindleaksSeconds") == 10.0,
            "final lifecycle checkpoint must be 10 seconds")
    require(protocol.get("forcedGcCountPerFinalSnapshot") == 2,
            "final lifecycle checkpoint must perform two explicit GCs")
    require(protocol.get("findleaksOccurrencesPreserved") is True,
            "findleaks occurrences must be preserved")
    require(protocol.get("finalHeapDumpPolicy") == "jcs",
            "final heap-dump policy must be jcs")

    schedule = nested_dict(raw.get("schedule"), "results.schedule")
    require(schedule.get("design") == "frozen canonical Williams 6x6",
            "campaign is not the frozen Williams 6x6 design")
    require(schedule.get("rowsAreShuffled") is False,
            "frozen Williams rows must not be shuffled")
    require(schedule.get("selectedProviders") == list(PROVIDERS),
            "Williams schedule provider list differs")
    require(schedule.get("canonicalRows") == [list(row) for row in EXPECTED_WILLIAMS_ROWS],
            "canonical Williams rows differ from the frozen design")
    require(schedule.get("scheduleSeed") == EXPECTED_SCHEDULE_SEED,
            "Williams schedule seed differs from frozen v4.2")
    require(schedule.get("workloadBaseSeed") == EXPECTED_CONFIGURATION["seed"],
            "Williams workload base seed differs from the request")
    fork_rows = as_list(schedule.get("forkRows"), "schedule.forkRows")
    require(len(fork_rows) == 6, "Williams schedule must contain six rows")
    for block, expected_order in enumerate(EXPECTED_WILLIAMS_ROWS, 1):
        row = nested_dict(fork_rows[block - 1], f"schedule.forkRows[{block - 1}]")
        require(
            row.get("fork") == block
            and row.get("block") == block
            and row.get("williamsRow") == block
            and row.get("order") == list(expected_order),
            f"Williams row {block} differs from the frozen design",
        )

    runs = as_list(raw.get("processRuns"), "results.processRuns")
    require(len(runs) == 36, "campaign must contain exactly 36 process runs")
    plan = as_list(raw.get("executionPlan"), "results.executionPlan")
    require(len(plan) == 36, "execution plan must contain exactly 36 process runs")
    require(all(isinstance(item, dict) for item in plan),
            "every execution-plan entry must be an object")
    plan_by_id = index_unique(plan, ("processRunId",), "execution plan")
    for block, expected_order in enumerate(EXPECTED_WILLIAMS_ROWS, 1):
        block_plan = sorted(
            (item for item in plan if item.get("block") == block),
            key=lambda item: item.get("orderPosition", -1),
        )
        require([item.get("provider") for item in block_plan] == list(expected_order),
                f"execution plan for Williams block {block} has the wrong order")
        for position, item in enumerate(block_plan, 1):
            require(
                item.get("scenario") == "default"
                and item.get("fork") == block
                and item.get("williamsRow") == block
                and item.get("orderPosition") == position,
                f"execution-plan entry for block {block}, position {position} differs",
            )
            expected_seeds = {
                str(cycle): paired_request_seed(
                    EXPECTED_CONFIGURATION["seed"], EXPECTED_SCHEDULE_SEED,
                    block, cycle,
                )
                for cycle in range(1, 6)
            }
            require(item.get("pairedRequestSeedsByCycle") == expected_seeds,
                    f"execution-plan seeds differ in block {block}, position {position}")
    run_ids: set[str] = set()
    container_ids: set[str] = set()
    provider_counts: Counter[str] = Counter()
    paired_seeds: dict[tuple[int, int], set[int]] = defaultdict(set)
    paired_access_plans: dict[tuple[int, int], set[str]] = defaultdict(set)
    paired_providers: dict[tuple[int, int], set[str]] = defaultdict(set)
    cycle_count = 0
    window_count = 0
    for run in runs:
        require(isinstance(run, dict), "each process run must be an object")
        run_id = run.get("processRunId")
        require(isinstance(run_id, str), "processRunId is required")
        require(campaign_prefix_from_run_id(run_id) == campaign_id,
                f"{run_id}: not part of campaign {campaign_id}")
        require(run_id not in run_ids, f"duplicate processRunId {run_id}")
        run_ids.add(run_id)
        provider = run.get("provider")
        require(provider in PROVIDERS, f"{run_id}: unknown provider {provider!r}")
        provider_counts[provider] += 1
        require(run.get("fork") == run.get("block")
                and run.get("fork") in range(1, 7),
                f"{run_id}: fork/block must be identical and in 1..6")
        planned = plan_by_id.get((run_id,))
        require(planned is not None, f"{run_id}: absent from execution plan")
        require(
            run.get("scenario") == planned.get("scenario") == "default"
            and run.get("provider") == planned.get("provider")
            and run.get("fork") == planned.get("fork")
            and run.get("block") == planned.get("block")
            and run.get("williamsRow") == planned.get("williamsRow")
            and run.get("orderPosition") == planned.get("orderPosition"),
            f"{run_id}: completed process metadata differs from the execution plan",
        )
        expected_run_id = (
            f"{campaign_id}-default-f{run['fork']:02d}-"
            f"p{run['orderPosition']}-{provider}"
        )
        require(run_id == expected_run_id,
                f"{run_id}: processRunId does not encode its fork/order/provider")
        require(run.get("configuration") == EXPECTED_CONFIGURATION,
                f"{run_id}: process configuration differs from frozen v4.2")
        require(run.get("scheduleSeed") == EXPECTED_SCHEDULE_SEED,
                f"{run_id}: process schedule seed differs")
        cycles = as_list(run.get("cycles"), f"{run_id}.cycles")
        require(len(cycles) == 5, f"{run_id}: expected five cycles")
        require([cycle.get("cycle") for cycle in cycles] == [1, 2, 3, 4, 5],
                f"{run_id}: cycle sequence must be 1..5")
        cycle_count += len(cycles)
        for cycle in cycles:
            cycle_number = cycle["cycle"]
            expected_seed = paired_request_seed(
                EXPECTED_CONFIGURATION["seed"], EXPECTED_SCHEDULE_SEED,
                int(run["block"]), int(cycle_number),
            )
            request = nested_dict(cycle.get("request"), f"{run_id}.C{cycle_number}.request")
            expected_request = {**EXPECTED_CONFIGURATION, "seed": expected_seed}
            require(cycle.get("requestSeed") == expected_seed
                    and request == expected_request,
                    f"{run_id} C{cycle_number}: paired request/seed differs")
            pairing_key = (int(run["block"]), int(cycle_number))
            paired_seeds[pairing_key].add(expected_seed)
            paired_providers[pairing_key].add(provider)
            phase_access_plans: list[str] = []
            for phase, workload_key, validation_key in (
                ("initial", "workload", "protocolValidation"),
                ("redeploy", "redeployWorkload", "redeployProtocolValidation"),
            ):
                workload = nested_dict(cycle.get(workload_key),
                                       f"{run_id}.{workload_key}")
                validation = nested_dict(cycle.get(validation_key),
                                         f"{run_id}.{validation_key}")
                throughput = workload.get("operationsPerSecond")
                require(isinstance(throughput, (int, float))
                        and not isinstance(throughput, bool)
                        and math.isfinite(float(throughput))
                        and throughput >= 0,
                        f"{run_id}: throughput is missing or invalid")
                require(workload.get("provider") == provider,
                        f"{run_id}: workload provider differs")
                access_plan = require_sha256(
                    workload.get("accessPlanSha256"),
                    f"{run_id}.C{cycle_number}.{workload_key}.accessPlanSha256",
                )
                phase_access_plans.append(access_plan)
                require(isinstance(validation.get("passed"), bool),
                        f"{run_id}: semantic gate outcome is missing")
                require(isinstance(validation.get("measurementDurationPassed"), bool),
                        f"{run_id}: measurement-duration outcome is missing")
                require(
                    validation.get("performanceComparisonEligible")
                    is (provider in PRIMARY_PROVIDERS),
                    f"{run_id}: performance eligibility differs from the protocol",
                )
                validate_workload_checkpoints(
                    workload, validation, provider, request,
                    f"{run_id}.C{cycle_number}.{phase}",
                )
                window_count += 1
            require(len(set(phase_access_plans)) == 1,
                    f"{run_id} C{cycle_number}: initial/redeploy access plans differ")
            paired_access_plans[pairing_key].add(phase_access_plans[0])
            validate_post_undeploy_timing(
                cycle.get("firstUndeployTiming"),
                float(protocol["earlyThreadObservationSeconds"]),
                float(protocol["finalObservationAndFindleaksSeconds"]),
                f"{run_id}.C{cycle_number}.firstUndeployTiming",
            )
            validate_post_undeploy_timing(
                cycle.get("finalUndeployTiming"),
                float(protocol["earlyThreadObservationSeconds"]),
                float(protocol["finalObservationAndFindleaksSeconds"]),
                f"{run_id}.C{cycle_number}.finalUndeployTiming",
            )
            require(isinstance(cycle.get("redeployReady"), bool),
                    f"{run_id}: redeploy readiness outcome is missing")
        environment = nested_dict(run.get("environment"), f"{run_id}.environment")
        container_id = environment.get("containerId")
        require(isinstance(container_id, str)
                and bool(re.fullmatch(r"[0-9a-f]{64}", container_id, re.IGNORECASE)),
                f"{run_id}: invalid full container ID")
        require(container_id not in container_ids,
                f"{run_id}: container ID was reused")
        container_ids.add(container_id)
        require(environment.get("provenanceValidationPassed") is True
                and environment.get("provenanceValidationErrors") == [],
                f"{run_id}: runtime provenance validation failed")
        require(environment.get("jcs4SourceCommit") == EXPECTED_JCS4_COMMIT,
                f"{run_id}: JCS4 source commit differs")
        require(environment.get("jcs321ArtifactSha256") == EXPECTED_JCS321_SHA256,
                f"{run_id}: JCS 3.2.1 checksum differs")
        for image_key, expected_digest in (
            ("runtimeBaseImage", EXPECTED_RUNTIME_IMAGE_SHA256),
            ("buildBaseImage", EXPECTED_BUILD_IMAGE_SHA256),
        ):
            image = nested_dict(environment.get(image_key),
                                f"{run_id}.environment.{image_key}")
            require(image.get("inspectionAvailable") is True
                    and image.get("pinnedDigest") == expected_digest
                    and image.get("id") == expected_digest
                    and str(image.get("reference", "")).endswith(
                        "@" + expected_digest
                    ),
                    f"{run_id}: {image_key} inspection/digest differs")
        if provider in JCS_PROVIDERS:
            heap_dump = run.get("finalHeapDump")
            require(isinstance(heap_dump, dict),
                    f"{run_id}: required final JCS heap dump is missing")
            require(heap_dump.get("policy") == "jcs",
                    f"{run_id}: final heap dump has the wrong policy")
            require(isinstance(heap_dump.get("file"), str)
                    and Path(heap_dump["file"]).name == heap_dump["file"],
                    f"{run_id}: final heap-dump filename is invalid")
            require_sha256(heap_dump.get("sha256"),
                           f"{run_id}.finalHeapDump.sha256")
            require(isinstance(heap_dump.get("sizeBytes"), int)
                    and not isinstance(heap_dump.get("sizeBytes"), bool)
                    and heap_dump["sizeBytes"] > 0,
                    f"{run_id}: final heap-dump size is invalid")
            require(isinstance(heap_dump.get("jcmdOutput"), str)
                    and bool(heap_dump["jcmdOutput"]),
                    f"{run_id}: heap-dump command evidence is missing")
        else:
            require(run.get("finalHeapDump") is None,
                    f"{run_id}: non-JCS heap dump conflicts with policy jcs")
    require(provider_counts == Counter({provider: 6 for provider in PROVIDERS}),
            f"provider process counts differ: {dict(provider_counts)}")
    require(cycle_count == 180, "campaign must contain exactly 180 cycles")
    require(window_count == 360, "campaign must contain exactly 360 workload windows")
    require(len(container_ids) == 36, "campaign must contain 36 distinct containers")

    expected_pairing_keys = {
        (block, cycle) for block in range(1, 7) for cycle in range(1, 6)
    }
    require(set(paired_providers) == expected_pairing_keys,
            "campaign does not contain all 30 Williams block/cycle pairs")
    for block_cycle in sorted(expected_pairing_keys):
        require(paired_providers[block_cycle] == set(PROVIDERS),
                f"block/cycle {block_cycle}: provider pairing is incomplete")
        require(len(paired_seeds[block_cycle]) == 1,
                f"block/cycle {block_cycle}: paired seeds differ")
        require(len(paired_access_plans[block_cycle]) == 1,
                f"block/cycle {block_cycle}: paired access-plan checksums differ")

    plan_ids = {item.get("processRunId") for item in plan}
    require(plan_ids == run_ids, "completed process runs differ from execution plan")

    expected_analysis_counts = {
        "summaries": 24,
        "forks": 144,
        "lifecycleSummaries": 6,
        "lifecycleForks": 36,
        "observations": 360,
    }
    for key, expected_count in expected_analysis_counts.items():
        rows = as_list(analysis.get(key), f"analysis.{key}")
        require(len(rows) == expected_count,
                f"analysis.{key} must contain {expected_count} rows")
    for key in ("forks", "lifecycleForks", "observations"):
        require(all(row.get("blockValid") is True for row in analysis[key]),
                f"analysis.{key} contains an invalid block")

    observations = analysis["observations"]
    observation_keys = {
        (row.get("processRunId"), row.get("cycle"), row.get("phase"))
        for row in observations
    }
    require(len(observation_keys) == 360,
            "analysis observations are not unique by JVM/cycle/phase")
    require({key[0] for key in observation_keys} == run_ids,
            "analysis observations do not cover every process run")
    require(all(isinstance(row.get("semanticGatePassed"), bool)
                for row in observations),
            "analysis contains a missing semantic-gate outcome")
    require(all(
        nonnegative_integer(row.get("observedEntriesAfterWorkload"))
        and nonnegative_integer(row.get("observedEntriesAfterWriteProbe"))
        and row.get("observedEntries")
        == row.get("observedEntriesAfterWriteProbe")
        and all(finite_nonnegative_number(row.get(field))
                for field in POST_UNDEPLOY_TIMING_FIELDS[2:])
        for row in observations
    ), "analysis entry/timing checkpoints are missing or aliases are inconsistent")

    fork_rows = analysis["forks"]
    fork_keys = {
        (row.get("processRunId"), row.get("phase"), row.get("analysisSet"))
        for row in fork_rows
    }
    require(len(fork_keys) == 144,
            "analysis fork rows are not unique by JVM/phase/analysis set")
    require({key[0] for key in fork_keys} == run_ids,
            "analysis fork rows do not cover every process run")
    require(all(row.get("cycleObservationCount") ==
                (5 if row.get("analysisSet") == ANALYSIS_SETS[0] else 4)
                for row in fork_rows),
            "analysis fork cycle denominators are inconsistent")

    lifecycle_ids = {row.get("processRunId") for row in analysis["lifecycleForks"]}
    require(lifecycle_ids == run_ids,
            "lifecycle analysis does not cover every process run exactly once")
    require(all(row.get("cycleCount") == 5
                and isinstance(row.get("redeployReadyAllCycles"), bool)
                for row in analysis["lifecycleForks"]),
            "lifecycle analysis contains an incomplete JVM series")

    expected_summary_keys = {
        (provider, phase, analysis_set)
        for provider in PROVIDERS
        for phase in PHASES
        for analysis_set in ANALYSIS_SETS
    }
    actual_summary_keys = {
        (row.get("provider"), row.get("phase"), row.get("analysisSet"))
        for row in analysis["summaries"]
    }
    require(actual_summary_keys == expected_summary_keys,
            "analysis summaries do not cover the frozen provider/phase matrix")

    expected_ratio_keys = {
        (provider, phase, analysis_set)
        for provider in ("caffeine", "ehcache", "cache2k")
        for phase in PHASES
        for analysis_set in ANALYSIS_SETS
    }
    paired_ratio_rows = as_list(
        analysis.get("pairedRatios"), "analysis.pairedRatios"
    )
    require(len(paired_ratio_rows) <= len(expected_ratio_keys),
            "analysis contains too many paired-ratio rows")
    actual_ratio_keys = {
        (row.get("provider"), row.get("phase"), row.get("analysisSet"))
        for row in paired_ratio_rows
    }
    require(actual_ratio_keys <= expected_ratio_keys,
            "paired ratios contain a provider/phase/analysis-set outside the protocol")
    require(all(row.get("referenceProvider") == "jcs4"
                and 1 <= len(row.get("valuesByBlock", [])) <= 6
                and row.get("ratioToJcs4N") == len(row.get("valuesByBlock", []))
                for row in paired_ratio_rows),
            "paired ratios must use admitted Williams blocks and JCS4 as reference")

    preflight = nested_dict(raw.get("campaignPreflight"), "campaignPreflight")
    require(preflight.get("provenanceValidationPassed") is True,
            "campaign preflight provenance failed")
    require(preflight.get("nativeMemoryTrackingSummaryAvailable") is True,
            "Native Memory Tracking preflight is unavailable")
    require(preflight.get("jcs4SourceCommit") == EXPECTED_JCS4_COMMIT,
            "JCS4 commit differs from the frozen snapshot")
    require(preflight.get("jcs4Version") == "4.0.0-SNAPSHOT",
            "JCS4 version differs from the frozen snapshot")
    require(preflight.get("jcs321Version") == "3.2.1",
            "JCS 3.2.1 version differs from the positive control")
    require(preflight.get("jcs321ArtifactSha256") == EXPECTED_JCS321_SHA256,
            "JCS 3.2.1 checksum differs from the frozen release artifact")
    for key, expected_digest in (
        ("runtimeBaseImage", EXPECTED_RUNTIME_IMAGE_SHA256),
        ("buildBaseImage", EXPECTED_BUILD_IMAGE_SHA256),
    ):
        image = nested_dict(preflight.get(key), f"campaignPreflight.{key}")
        require(image.get("inspectionAvailable") is True,
                f"{key} inspection is unavailable")
        require(image.get("pinnedDigest") == expected_digest,
                f"{key} digest differs from frozen v4.2")
        require(image.get("id") == expected_digest,
                f"{key} inspected image ID differs from frozen v4.2")
        require(str(image.get("reference", "")).endswith("@" + expected_digest),
                f"{key} reference is not pinned to its digest")

    require(preflight.get("imageJcs4RevisionLabel") == EXPECTED_JCS4_COMMIT,
            "container image JCS4 revision label differs from the source commit")
    require(preflight.get("jcs321ExpectedSha256") == EXPECTED_JCS321_SHA256,
            "preflight expected JCS 3.2.1 checksum differs")
    preflight_checksums = {
        "warSha256": require_sha256(preflight.get("warSha256"),
                                    "campaignPreflight.warSha256"),
        "jcs4ArtifactSha256": require_sha256(
            preflight.get("jcs4ArtifactSha256"),
            "campaignPreflight.jcs4ArtifactSha256",
        ),
        "jcs321ArtifactSha256": require_sha256(
            preflight.get("jcs321ArtifactSha256"),
            "campaignPreflight.jcs321ArtifactSha256",
        ),
    }
    require(preflight_checksums["jcs321ArtifactSha256"]
            == EXPECTED_JCS321_SHA256,
            "preflight JCS 3.2.1 artifact checksum differs")
    preflight_manifest = artifact_manifest_map(
        preflight.get("artifactManifest"), "campaignPreflight.artifactManifest"
    )
    expected_artifacts = {
        "/artifacts/cache-benchmark.war": preflight_checksums["warSha256"],
        "/artifacts/commons-jcs3-core-3.2.1.jar":
        preflight_checksums["jcs321ArtifactSha256"],
        "/artifacts/commons-jcs4-core-4.0.0-SNAPSHOT.jar":
        preflight_checksums["jcs4ArtifactSha256"],
    }
    require(preflight_manifest == expected_artifacts,
            "preflight artifact manifest differs from its declared checksums")
    require(isinstance(preflight.get("containerCpuLimit"), (int, float))
            and not isinstance(preflight.get("containerCpuLimit"), bool)
            and preflight["containerCpuLimit"] > 0,
            "preflight container CPU limit is missing or invalid")
    require(isinstance(preflight.get("containerMemoryLimitBytes"), int)
            and not isinstance(preflight.get("containerMemoryLimitBytes"), bool)
            and preflight["containerMemoryLimitBytes"] > 0,
            "preflight container memory limit is missing or invalid")
    coherent_environment_fields = (
        "dockerImageId", "containerImageName", "containerOS", "javaOptions",
        "JVM Version", "JVM Vendor", "OS Name", "OS Version",
        "OS Architecture", "containerCpuModel", "containerVisibleProcessors",
        "containerCpuLimit", "containerMemoryLimitBytes",
        "dockerServerVersion", "dockerServerOperatingSystem",
        "dockerServerKernelVersion", "dockerServerArchitecture",
        "dockerServerName", "jvmCommandLine", "jvmFlags", "jcs4Version",
        "jcs321Version",
    )
    for run in runs:
        run_id = run["processRunId"]
        environment = nested_dict(run.get("environment"), f"{run_id}.environment")
        for field in coherent_environment_fields:
            require(environment.get(field) == preflight.get(field),
                    f"{run_id}: environment field {field} differs from preflight")
        preflight_uname = str(preflight.get("containerKernel", "")).split()
        run_uname = str(environment.get("containerKernel", "")).split()
        require(len(preflight_uname) >= 3 and len(run_uname) >= 3,
                f"{run_id}: container uname output is malformed")
        require(
            [preflight_uname[0], *preflight_uname[2:]]
            == [run_uname[0], *run_uname[2:]],
            f"{run_id}: container kernel differs from preflight after ignoring "
            "the per-container hostname",
        )
        for checksum_key, expected_checksum in preflight_checksums.items():
            require(environment.get(checksum_key) == expected_checksum,
                    f"{run_id}: {checksum_key} differs from preflight")
        require(environment.get("imageJcs4RevisionLabel") == EXPECTED_JCS4_COMMIT,
                f"{run_id}: container image JCS4 revision label differs")
        require(
            artifact_manifest_map(
                environment.get("artifactManifest"),
                f"{run_id}.environment.artifactManifest",
            ) == preflight_manifest,
            f"{run_id}: artifact manifest differs from preflight",
        )

    source = nested_dict(raw.get("sourceProvenance"), "sourceProvenance")
    source_files = as_list(source.get("files"), "sourceProvenance.files")
    require(all(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sizeBytes"), int)
        and not isinstance(item.get("sizeBytes"), bool)
        and item.get("sizeBytes") >= 0
        and isinstance(item.get("sha256"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", item["sha256"], re.IGNORECASE))
        for item in source_files
    ), "source provenance file manifest is malformed")
    require(len({item["path"] for item in source_files}) == len(source_files),
            "source provenance file paths are not unique")
    calculated_source_manifest = hashlib.sha256(
        "\n".join(
            f"{item['sha256']}  {item['path']}" for item in source_files
        ).encode("utf-8")
    ).hexdigest()
    require(source.get("manifestSha256") == calculated_source_manifest,
            "source provenance aggregate SHA-256 is inconsistent")
    protocol_rows = [
        item for item in source_files
        if item.get("path") == EXPECTED_PROTOCOL_PATH
    ]
    require(len(protocol_rows) == 1
            and protocol_rows[0].get("sha256") == EXPECTED_PROTOCOL_SHA256,
            "frozen v4.2 protocol checksum is missing or different")
    validate_analysis_regeneration(raw, analysis, source_files)
    return campaign_id


def index_unique(rows: Iterable[dict[str, Any]], fields: tuple[str, ...],
                 label: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        require(key not in result, f"duplicate {label} key {key}")
        result[key] = row
    return result


def extract_observed_semantic_evidence(
    runs: list[dict[str, Any]], provider: str
) -> dict[str, Any]:
    """Extract observed RQ1 ranges from every raw workload window.

    These ranges describe all acquired windows, independently of whether the
    aggregate semantic gate passed.  The gate count remains a separate field
    in ``qualityControl.byProvider`` so that observations and admissions cannot
    be conflated.
    """
    require(provider in PROVIDERS, f"unknown provider {provider!r}")
    durations_seconds: list[float] = []
    measured_operations: list[int] = []
    hit_rates: list[float] = []
    entries_after_workload: list[int] = []
    entries_after_write_probe: list[int] = []
    single_flight_applicable = 0
    single_flight_passed = 0
    redeploy_ready_applicable = 0
    redeploy_ready_passed = 0

    for run_position, run_value in enumerate(runs):
        run = nested_dict(run_value, f"{provider}.runs[{run_position}]")
        require(run.get("provider") == provider,
                f"{provider}.runs[{run_position}]: provider differs")
        cycles = as_list(run.get("cycles"),
                         f"{provider}.runs[{run_position}].cycles")
        for cycle_position, cycle_value in enumerate(cycles):
            cycle = nested_dict(
                cycle_value,
                f"{provider}.runs[{run_position}].cycles[{cycle_position}]",
            )
            redeploy_ready = cycle.get("redeployReady")
            require(isinstance(redeploy_ready, bool),
                    f"{provider}.runs[{run_position}].cycles[{cycle_position}]: "
                    "redeployReady must be boolean")
            redeploy_ready_applicable += 1
            redeploy_ready_passed += int(redeploy_ready)
            for phase, workload_key, validation_key in (
                ("initial", "workload", "protocolValidation"),
                ("redeploy", "redeployWorkload", "redeployProtocolValidation"),
            ):
                label = (
                    f"{provider}.runs[{run_position}].cycles[{cycle_position}]"
                    f".{phase}"
                )
                workload = nested_dict(cycle.get(workload_key),
                                       f"{label}.{workload_key}")
                validation = nested_dict(cycle.get(validation_key),
                                         f"{label}.{validation_key}")
                after_workload = nested_dict(
                    workload.get("providerMetricsAfterWorkload"),
                    f"{label}.providerMetricsAfterWorkload",
                )
                after_write = nested_dict(
                    workload.get("providerMetricsAfterWriteProbe"),
                    f"{label}.providerMetricsAfterWriteProbe",
                )

                measurement_nanos = workload.get("measurementNanos")
                require(nonnegative_integer(measurement_nanos)
                        and measurement_nanos > 0,
                        f"{label}: measurementNanos is missing or malformed")
                require(validation.get("observedMeasurementNanos")
                        == measurement_nanos,
                        f"{label}: observed duration differs from validation")

                operations = workload.get("measuredOperations")
                hit_rate = after_workload.get("hitRate")
                population_after_workload = after_workload.get("currentEntries")
                population_after_write = after_write.get("currentEntries")
                require(nonnegative_integer(operations),
                        f"{label}: measuredOperations is missing or malformed")
                require(finite_nonnegative_number(hit_rate)
                        and float(hit_rate) <= 1.0,
                        f"{label}: hitRate is missing or malformed")
                require(nonnegative_integer(population_after_workload),
                        f"{label}: post-workload population is malformed")
                require(nonnegative_integer(population_after_write),
                        f"{label}: post-write population is malformed")

                durations_seconds.append(measurement_nanos / 1_000_000_000.0)
                measured_operations.append(operations)
                hit_rates.append(float(hit_rate))
                entries_after_workload.append(population_after_workload)
                entries_after_write_probe.append(population_after_write)

                if provider == "nostore":
                    require(validation.get("singleFlightGateApplicable") is False,
                            f"{label}: no-store single-flight must be inapplicable")
                else:
                    single_flight = workload.get("singleFlightPassed")
                    require(isinstance(single_flight, bool),
                            f"{label}: singleFlightPassed must be boolean")
                    require(
                        validation.get("singleFlightPassed") is single_flight,
                        f"{label}: single-flight evidence differs from validation",
                    )
                    single_flight_applicable += 1
                    single_flight_passed += int(single_flight)

            redeploy_validation = nested_dict(
                cycle.get("redeployProtocolValidation"),
                f"{provider}.runs[{run_position}].cycles[{cycle_position}]"
                ".redeployProtocolValidation",
            )
            require(
                cycle.get("redeployPassed")
                is (redeploy_ready and redeploy_validation.get("passed") is True),
                f"{provider}.runs[{run_position}].cycles[{cycle_position}]: "
                "redeployPassed differs from readiness and semantic evidence",
            )

    observed_windows = len(durations_seconds)
    require(observed_windows == 60,
            f"{provider}: expected 60 raw workload windows, found {observed_windows}")
    require(redeploy_ready_applicable == 30,
            f"{provider}: expected 30 post-redeploy readiness checks")

    def bounds(values: list[float] | list[int]) -> dict[str, Any]:
        require(len(values) == observed_windows,
                f"{provider}: incomplete observed semantic evidence")
        return {"n": len(values), "minimum": min(values), "maximum": max(values)}

    duration_stats = bounds(durations_seconds)
    operations_stats = bounds(measured_operations)
    hit_rate_stats = bounds(hit_rates)
    after_workload_stats = bounds(entries_after_workload)
    after_write_stats = bounds(entries_after_write_probe)
    require(
        (provider == "nostore" and single_flight_applicable == 0
         and single_flight_passed == 0)
        or (provider != "nostore" and single_flight_applicable == observed_windows),
        f"{provider}: single-flight denominator is inconsistent",
    )

    formatted = {
        "measurementDurationSecondsMinMax": range_text(duration_stats, 3),
        "measuredOperationsMinMax": (
            f"{italian_integer(int(operations_stats['minimum']))}–"
            f"{italian_integer(int(operations_stats['maximum']))}"
        ),
        "hitRatePercentMinMax": range_text(
            {
                "minimum": float(hit_rate_stats["minimum"]) * 100.0,
                "maximum": float(hit_rate_stats["maximum"]) * 100.0,
            },
            3,
        ),
        "entriesAfterWorkloadMinMax": (
            f"{italian_integer(int(after_workload_stats['minimum']))}–"
            f"{italian_integer(int(after_workload_stats['maximum']))}"
        ),
        "entriesAfterWriteProbeMinMax": (
            f"{italian_integer(int(after_write_stats['minimum']))}–"
            f"{italian_integer(int(after_write_stats['maximum']))}"
        ),
        "singleFlightPassedApplicable": (
            denominator(single_flight_passed, single_flight_applicable)
            if single_flight_applicable else "non applicabile"
        ),
        "redeployReadyPassedApplicable": denominator(
            redeploy_ready_passed, redeploy_ready_applicable
        ),
    }
    return {
        "scope": (
            "all 60 acquired raw workload windows, irrespective of aggregate "
            "semantic-gate outcome"
        ),
        "measurementDurationSeconds": duration_stats,
        "measuredOperations": operations_stats,
        "hitRate": hit_rate_stats,
        "entriesAfterWorkload": after_workload_stats,
        "entriesAfterWriteProbe": after_write_stats,
        "singleFlight": {
            "gateApplicable": single_flight_applicable > 0,
            "applicableWindows": single_flight_applicable,
            "passedWindows": (
                single_flight_passed if single_flight_applicable else None
            ),
            "failedWindows": (
                single_flight_applicable - single_flight_passed
                if single_flight_applicable else None
            ),
            "allApplicableWindowsPassed": (
                single_flight_passed == single_flight_applicable
                if single_flight_applicable else None
            ),
        },
        "redeployReady": {
            "applicableCycles": redeploy_ready_applicable,
            "passedCycles": redeploy_ready_passed,
        },
        "formatted": formatted,
    }


def extract_quality_control(raw: dict[str, Any], analysis: dict[str, Any],
                            valid_run_ids: set[str]) -> dict[str, Any]:
    runs_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in raw["processRuns"]:
        runs_by_provider[run["provider"]].append(run)
    observations_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in analysis["observations"]:
        observations_by_provider[row["provider"]].append(row)
    primary_forks_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in analysis["forks"]:
        if row["analysisSet"] == "primary-all-cycles":
            primary_forks_by_provider[row["provider"]].append(row)

    by_provider = []
    for provider in PROVIDERS:
        runs = runs_by_provider[provider]
        observations = observations_by_provider[provider]
        fork_rows = primary_forks_by_provider[provider]
        acquired = len(runs)
        valid = sum(run["processRunId"] in valid_run_ids for run in runs)
        gate_passed = sum(row["semanticGatePassed"] is True for row in observations)
        semantic_pairs = sum(row["semanticGatePassed"] is True for row in fork_rows)
        performance_pairs = sum(
            row["includedInPerformanceSummary"] is True for row in fork_rows
        )
        row = {
            "provider": provider,
            "displayName": DISPLAY_NAMES[provider],
            "processesAcquired": acquired,
            "processesPlanned": 6,
            "validJvms": valid,
            "validJvmsPlanned": 6,
            "workloadWindowsAcquired": len(observations),
            "workloadWindowsPlanned": 60,
            "semanticGateWindowsPassed": gate_passed,
            "semanticGateWindowsEvaluable": len(observations),
            "semanticForkPhasePairsPassed": semantic_pairs,
            "semanticForkPhasePairsEvaluable": 12,
            "performanceForkPhasePairsIncluded": performance_pairs,
            "performanceForkPhasePairsPlanned": 12
            if provider in PRIMARY_PROVIDERS else 0,
            "performanceComparisonApplicable": provider in PRIMARY_PROVIDERS,
            "observedSemanticEvidence": extract_observed_semantic_evidence(
                runs, provider
            ),
        }
        formatted = {
            "processesAcquired": denominator(acquired, 6),
            "validJvms": denominator(valid, 6),
            "workloadWindowsAcquired": denominator(len(observations), 60),
            "semanticGateWindowsPassed": denominator(gate_passed, 60),
            "performanceForkPhasePairsIncluded": denominator(performance_pairs, 12)
            if provider in PRIMARY_PROVIDERS else "non applicabile",
        }
        formatted["paperRow"] = (
            f"| {DISPLAY_NAMES[provider]} | {formatted['processesAcquired']} | "
            f"{formatted['validJvms']} | {formatted['workloadWindowsAcquired']} | "
            f"{formatted['semanticGateWindowsPassed']} | "
            f"{formatted['performanceForkPhasePairsIncluded']} |"
        )
        row["formatted"] = formatted
        by_provider.append(row)

    plan_by_block: dict[int, set[str]] = defaultdict(set)
    completed_by_block: dict[int, set[str]] = defaultdict(set)
    for item in raw["executionPlan"]:
        plan_by_block[int(item["block"])].add(item["processRunId"])
    for run in raw["processRuns"]:
        completed_by_block[int(run["block"])].add(run["processRunId"])
    complete_blocks = sum(
        plan_by_block[block] == completed_by_block[block]
        for block in range(1, 7)
    )
    block_qc = {
        "scope": "only the definitive finalized campaign JSON; earlier excluded campaigns are not counted",
        "planned": 6,
        "completeAtFirstAttemptWithinDataset": complete_blocks,
        "completeOnRecordedExecution": complete_blocks,
        "invalidated": len(raw.get("invalidBlocks", [])),
        "repeatedWithinDataset": 0,
        "finalAdmitted": len({run["block"] for run in raw["processRuns"]
                              if run["processRunId"] in valid_run_ids}),
        "invalidAttemptsRetainedWithinDataset": len(raw["infrastructureFailures"]),
        "invalidAttemptsWithinDataset": len(raw["infrastructureFailures"]),
        "distinctContainerIds": len({
            run["environment"]["containerId"] for run in raw["processRuns"]
            if run["processRunId"] in valid_run_ids
        }),
        "admittedJvms": len(valid_run_ids),
    }
    block_qc["formatted"] = {
        "completeAtFirstAttemptWithinDataset": denominator(complete_blocks, 6),
        "completeOnRecordedExecution": denominator(complete_blocks, 6),
        "invalidated": denominator(block_qc["invalidated"], 6),
        "repeatedWithinDataset": denominator(0, 6),
        "finalAdmitted": denominator(block_qc["finalAdmitted"], 6),
        "invalidAttempts": denominator(
            block_qc["invalidAttemptsRetainedWithinDataset"],
            block_qc["invalidAttemptsWithinDataset"],
        ) if block_qc["invalidAttemptsWithinDataset"] else "0/0",
        "distinctContainerIds": denominator(
            block_qc["distinctContainerIds"], block_qc["admittedJvms"]
        ),
    }
    return {
        "protocolDeviationAssessment": {
            "scope": (
                "only parameters and invariants enforced by the strict v4.2 "
                "input validator and provenance checks"
            ),
            "allMachineVerifiableControlsPassed": True,
            "statement": NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT,
        },
        "denominatorDefinition": {
            "processesPerProvider": 6,
            "workloadWindowsPerProvider": 60,
            "forkPhasePairsPerProvider": 12,
            "cyclesTotal": 180,
            "workloadWindowsTotal": 360,
            "processesTotal": 36,
        },
        "byProvider": by_provider,
        "williamsBlocks": block_qc,
    }


def extract_primary_performance(analysis: dict[str, Any]) -> dict[str, Any]:
    summary_index = index_unique(
        analysis["summaries"], ("provider", "phase", "analysisSet"), "summary"
    )
    throughput_rows = []
    latency_rows = []
    for provider in PRIMARY_PROVIDERS:
        for phase in PHASES:
            source = summary_index[(provider, phase, "primary-all-cycles")]
            operations = stats_from_row(source, "operationsPerSecond")
            mops = scaled_stats(operations, 1_000_000.0)
            throughput = {
                "provider": provider,
                "displayName": DISPLAY_NAMES[provider],
                "phase": phase,
                "phaseDisplayName": PHASE_NAMES[phase],
                "includedForks": source["performanceIncludedForkCount"],
                "plannedForks": 6,
                "operationsPerSecond": operations,
                "millionsOperationsPerSecond": mops,
            }
            throughput["formatted"] = {
                "includedForks": denominator(throughput["includedForks"], 6),
                "medianMops": italian_number(mops["median"]),
                "q1Q3Mops": quartile_text(mops),
                "minMaxMops": range_text(mops),
            }
            throughput["formatted"]["paperRow"] = (
                f"| {DISPLAY_NAMES[provider]} | {PHASE_NAMES[phase]} | "
                f"{throughput['formatted']['includedForks']} | "
                f"{throughput['formatted']['medianMops']} | "
                f"{throughput['formatted']['q1Q3Mops']} | "
                f"{throughput['formatted']['minMaxMops']} |"
            )
            throughput_rows.append(throughput)

            p50_ns = stats_from_row(source, "latencyP50Nanos")
            p95_ns = stats_from_row(source, "latencyP95Nanos")
            p99_ns = stats_from_row(source, "latencyP99Nanos")
            latency = {
                "provider": provider,
                "displayName": DISPLAY_NAMES[provider],
                "phase": phase,
                "phaseDisplayName": PHASE_NAMES[phase],
                "includedForks": source["performanceIncludedForkCount"],
                "plannedForks": 6,
                "p50Nanoseconds": p50_ns,
                "p95Nanoseconds": p95_ns,
                "p99Nanoseconds": p99_ns,
                "p50Microseconds": scaled_stats(p50_ns, 1_000.0),
                "p95Microseconds": scaled_stats(p95_ns, 1_000.0),
                "p99Microseconds": scaled_stats(p99_ns, 1_000.0),
            }
            p50_us = latency["p50Microseconds"]
            p95_us = latency["p95Microseconds"]
            p99_us = latency["p99Microseconds"]
            latency["formatted"] = {
                "includedForks": denominator(latency["includedForks"], 6),
                "p50MedianMicroseconds": italian_number(p50_us["median"]),
                "p95MedianMicroseconds": italian_number(p95_us["median"]),
                "p99MedianMicroseconds": italian_number(p99_us["median"]),
                "p99Q1Q3Microseconds": quartile_text(p99_us),
                "p99MinMaxMicroseconds": range_text(p99_us),
            }
            latency["formatted"]["paperRow"] = (
                f"| {DISPLAY_NAMES[provider]} | {PHASE_NAMES[phase]} | "
                f"{latency['formatted']['includedForks']} | "
                f"{latency['formatted']['p50MedianMicroseconds']} | "
                f"{latency['formatted']['p95MedianMicroseconds']} | "
                f"{latency['formatted']['p99MedianMicroseconds']} | "
                f"{latency['formatted']['p99Q1Q3Microseconds']} | "
                f"{latency['formatted']['p99MinMaxMicroseconds']} |"
            )
            latency_rows.append(latency)
    return {
        "analysisSet": "primary-all-cycles",
        "statisticalUnit": analysis.get("statisticalUnit"),
        "throughput": throughput_rows,
        "sampledLatency": latency_rows,
    }


def extract_paired_ratios(analysis: dict[str, Any]) -> dict[str, Any]:
    rows = []
    order = {provider: index for index, provider in enumerate(PRIMARY_PROVIDERS)}
    phase_order = {phase: index for index, phase in enumerate(PHASES)}
    set_order = {name: index for index, name in enumerate(ANALYSIS_SETS)}
    sorted_rows = sorted(
        analysis["pairedRatios"],
        key=lambda row: (
            set_order[row["analysisSet"]],
            order[row["provider"]],
            phase_order[row["phase"]],
        ),
    )
    for source in sorted_rows:
        stats = stats_from_row(source, "ratioToJcs4")
        row = {
            "provider": source["provider"],
            "displayName": DISPLAY_NAMES[source["provider"]],
            "referenceProvider": "jcs4",
            "phase": source["phase"],
            "phaseDisplayName": PHASE_NAMES[source["phase"]],
            "analysisSet": source["analysisSet"],
            "pairingUnit": source["pairingUnit"],
            "valuesByBlock": source["valuesByBlock"],
            "ratio": stats,
        }
        row["formatted"] = {
            "includedPairs": denominator(stats["n"], 6),
            "median": f"{italian_number(stats['median'], 2)}×",
            "q1Q3": f"{quartile_text(stats, 2)}×",
            "minMax": f"{range_text(stats, 2)}×",
        }
        row["formatted"]["paperRow"] = (
            f"| {DISPLAY_NAMES[source['provider']]} | "
            f"{PHASE_NAMES[source['phase']]} | "
            f"{row['formatted']['includedPairs']} | {row['formatted']['median']} | "
            f"{row['formatted']['q1Q3']} | {row['formatted']['minMax']} |"
        )
        rows.append(row)
    return {
        "primary": [row for row in rows
                    if row["analysisSet"] == "primary-all-cycles"],
        "sensitivity": [row for row in rows
                        if row["analysisSet"] == "sensitivity-without-cycle-1"],
    }


def extract_sensitivity(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = index_unique(
        analysis["summaries"], ("provider", "phase", "analysisSet"), "summary"
    )
    fork_groups: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in analysis["forks"]:
        key = (row["provider"], row["phase"], row["analysisSet"])
        fork_groups[key][row["processRunId"]] = row

    output = []
    for provider in PRIMARY_PROVIDERS:
        for phase in PHASES:
            primary_key = (provider, phase, "primary-all-cycles")
            sensitivity_key = (provider, phase, "sensitivity-without-cycle-1")
            primary_summary = summaries[primary_key]
            sensitivity_summary = summaries[sensitivity_key]
            primary_rows = {
                run_id: row for run_id, row in fork_groups[primary_key].items()
                if row["includedInPerformanceSummary"] is True
            }
            sensitivity_rows = {
                run_id: row for run_id, row in fork_groups[sensitivity_key].items()
                if row["includedInPerformanceSummary"] is True
            }
            common_ids = sorted(
                set(primary_rows) & set(sensitivity_rows),
                key=lambda run_id: primary_rows[run_id]["fork"],
            )
            primary_common = [
                float(primary_rows[run_id]["comparisonMedian_operationsPerSecond"])
                for run_id in common_ids
            ]
            sensitivity_common = [
                float(sensitivity_rows[run_id]["comparisonMedian_operationsPerSecond"])
                for run_id in common_ids
            ]
            require(len(primary_common) == len(sensitivity_common),
                    f"{provider}/{phase}: sensitivity fork pairing differs")
            common_primary_median = (
                statistics.median(primary_common) if primary_common else None
            )
            common_sensitivity_median = (
                statistics.median(sensitivity_common) if sensitivity_common else None
            )
            if common_primary_median is None:
                variation_percent = None
            else:
                require(common_primary_median != 0,
                        f"{provider}/{phase}: zero primary common-fork median")
                variation_percent = (
                    (common_sensitivity_median - common_primary_median)
                    / common_primary_median * 100.0
                )
            values_by_fork = []
            for run_id in common_ids:
                primary_value = float(
                    primary_rows[run_id]["comparisonMedian_operationsPerSecond"]
                )
                sensitivity_value = float(
                    sensitivity_rows[run_id]["comparisonMedian_operationsPerSecond"]
                )
                values_by_fork.append({
                    "processRunId": run_id,
                    "fork": primary_rows[run_id]["fork"],
                    "block": primary_rows[run_id]["block"],
                    "primaryMedianOperationsPerSecond": primary_value,
                    "sensitivityMedianOperationsPerSecond": sensitivity_value,
                    "withinForkVariationPercent":
                    (sensitivity_value - primary_value) / primary_value * 100.0,
                })
            primary_published = stats_from_row(
                primary_summary, "operationsPerSecond"
            )
            sensitivity_published = stats_from_row(
                sensitivity_summary, "operationsPerSecond"
            )
            row = {
                "provider": provider,
                "displayName": DISPLAY_NAMES[provider],
                "phase": phase,
                "phaseDisplayName": PHASE_NAMES[phase],
                "primaryForkCount": len(primary_rows),
                "sensitivityForkCount": len(sensitivity_rows),
                "commonForkCount": len(common_ids),
                "plannedForkCount": 6,
                "forkSetUnchanged": set(primary_rows) == set(sensitivity_rows),
                "primaryForkIds": sorted(primary_rows,
                                         key=lambda run_id: primary_rows[run_id]["fork"]),
                "sensitivityForkIds": sorted(
                    sensitivity_rows,
                    key=lambda run_id: sensitivity_rows[run_id]["fork"],
                ),
                "commonForkIds": common_ids,
                "primaryPublishedOperationsPerSecond": primary_published,
                "sensitivityPublishedOperationsPerSecond": sensitivity_published,
                "commonForkPrimaryMedianOperationsPerSecond": common_primary_median,
                "commonForkSensitivityMedianOperationsPerSecond":
                common_sensitivity_median,
                "commonForkVariationPercent": variation_percent,
                "variationDefinition": (
                    "(median cycles 2-5 across common forks - median cycles 1-5 "
                    "across common forks) / median cycles 1-5 across common forks * 100"
                ),
                "valuesByCommonFork": values_by_fork,
            }
            formatted = {
                "primaryForks": denominator(len(primary_rows), 6),
                "primaryMedianMops": italian_number(
                    None if primary_published["median"] is None else
                    primary_published["median"] / 1_000_000.0
                ),
                "sensitivityForks": denominator(len(sensitivity_rows), 6),
                "sensitivityMedianMops": italian_number(
                    None if sensitivity_published["median"] is None else
                    sensitivity_published["median"] / 1_000_000.0
                ),
                "commonForks": denominator(len(common_ids), 6),
                "commonForkVariationPercent":
                f"{italian_number(variation_percent, 2, signed=True)}%",
            }
            formatted["paperRow"] = (
                f"| {DISPLAY_NAMES[provider]} | {PHASE_NAMES[phase]} | "
                f"{formatted['primaryForks']} | {formatted['primaryMedianMops']} | "
                f"{formatted['sensitivityForks']} | "
                f"{formatted['sensitivityMedianMops']} | "
                f"{formatted['commonForks']} | "
                f"{formatted['commonForkVariationPercent']} |"
            )
            row["formatted"] = formatted
            output.append(row)
    return output


def interval_evidence(run: dict[str, Any], cycle: dict[str, Any],
                      phase: str) -> dict[str, Any]:
    if phase == "first-undeploy":
        early_key = "firstUndeployThreadEvidenceEarly"
        final_key = "firstUndeployThreadEvidenceFinal"
        warnings_key = "firstUndeployThreadLeakWarnings"
        snapshot_key = "afterUndeploy"
    else:
        early_key = "finalUndeployThreadEvidenceEarly"
        final_key = "finalUndeployThreadEvidenceFinal"
        warnings_key = "secondUndeployThreadLeakWarnings"
        snapshot_key = "afterFinalUndeploy"
    early = nested_dict(cycle.get(early_key), early_key)
    final = nested_dict(cycle.get(final_key), final_key)
    warnings = as_list(cycle.get(warnings_key), warnings_key)
    early_signatures = as_list(early.get("jcsThreadSignatures", []),
                               f"{early_key}.jcsThreadSignatures")
    final_signatures = as_list(final.get("jcsThreadSignatures", []),
                               f"{final_key}.jcsThreadSignatures")
    snapshot = nested_dict(cycle.get(snapshot_key), snapshot_key)
    provider = run["provider"]
    require(all(isinstance(warning, str) for warning in warnings),
            f"{warnings_key} must contain log records")
    require(all(f"[{provider}]" in warning for warning in warnings),
            f"{warnings_key} contains a thread-leak warning for another context")
    expected_signature = {
        "jcs321": "jcs3-element-event-queue",
        "jcs4": "jcs4-thread-pool-event-queue",
    }.get(provider)
    for checkpoint_name, signatures in (
        (early_key, early_signatures), (final_key, final_signatures)
    ):
        require(all(isinstance(signature, dict) for signature in signatures),
                f"{checkpoint_name}.jcsThreadSignatures is malformed")
        if expected_signature is not None:
            require(all(signature.get("signature") == expected_signature
                        for signature in signatures),
                    f"{checkpoint_name} contains a signature for another JCS line")
        else:
            require(not signatures,
                    f"{checkpoint_name} unexpectedly contains a JCS signature")
    signature_count = len(early_signatures) + len(final_signatures)
    target_observed = validate_findleaks_snapshot(
        snapshot, provider,
        f"{run['processRunId']}.C{cycle['cycle']}.{snapshot_key}",
    )
    raw_target_flag = cycle.get(
        "tomcatFindLeaksTargetContextObservedAfterFirstUndeploy"
        if phase == "first-undeploy"
        else "tomcatFindLeaksTargetContextObservedAfterFinalUndeploy"
    )
    require(raw_target_flag is target_observed,
            f"{run['processRunId']} C{cycle['cycle']} {phase}: "
            "findleaks target flag differs from preserved occurrences")
    return {
        "processRunId": run["processRunId"],
        "provider": run["provider"],
        "fork": run["fork"],
        "block": run["block"],
        "cycle": cycle["cycle"],
        "undeployPhase": phase,
        "earlySignatureObservationCount": len(early_signatures),
        "finalSignatureObservationCount": len(final_signatures),
        "signatureObservationCountAcrossCheckpoints": signature_count,
        "threadLeakWarningEventCount": len(warnings),
        "targetContextObservedInFindleaks": target_observed,
        "corroborated": signature_count > 0 and len(warnings) > 0,
    }


def extract_post_undeploy_timing(raw: dict[str, Any]) -> dict[str, Any]:
    observed_fields = (
        "earlyThreadStartedSecondsAfterUndeploy",
        "earlyThreadCompletedSecondsAfterUndeploy",
        "finalDiagnosticStartedSecondsAfterUndeploy",
        "findLeaksCompletedSecondsAfterUndeploy",
        "finalSnapshotCompletedSecondsAfterUndeploy",
    )
    all_values: dict[str, list[float]] = defaultdict(list)
    by_phase_values: dict[str, dict[str, list[float]]] = {
        "first-undeploy": defaultdict(list),
        "final-undeploy": defaultdict(list),
    }
    timing_keys = (
        ("first-undeploy", "firstUndeployTiming"),
        ("final-undeploy", "finalUndeployTiming"),
    )
    interval_count = 0
    for run in raw["processRuns"]:
        for cycle in run["cycles"]:
            for phase, timing_key in timing_keys:
                timing = cycle[timing_key]
                interval_count += 1
                for field in observed_fields:
                    value = float(timing[field])
                    all_values[field].append(value)
                    by_phase_values[phase][field].append(value)
    require(interval_count == 360,
            "post-undeploy timing evidence must cover 360 intervals")
    return {
        "referenceOrigin": "return of the undeploy request",
        "clock": "monotonic elapsed seconds",
        "intervals": interval_count,
        "plannedIntervals": 360,
        "observedSecondsAfterUndeploy": {
            field: descriptive(all_values[field]) for field in observed_fields
        },
        "byUndeployPhase": {
            phase: {
                field: descriptive(values[field]) for field in observed_fields
            }
            for phase, values in by_phase_values.items()
        },
    }


def extract_lifecycle(raw: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    run_index = {run["processRunId"]: run for run in raw["processRuns"]}
    summaries = index_unique(
        analysis["lifecycleSummaries"], ("provider",), "lifecycle summary"
    )
    forks_by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in analysis["lifecycleForks"]:
        forks_by_provider[row["provider"]].append(row)

    by_provider = []
    for provider in PROVIDERS:
        summary = summaries[(provider,)]
        forks = sorted(forks_by_provider[provider], key=lambda row: row["fork"])
        valid_forks = [row for row in forks if row["blockValid"] is True]
        intervals = []
        delta_values = []
        fork_details = []
        final_checkpoint_count = 0
        for fork in valid_forks:
            run = run_index[fork["processRunId"]]
            process_baseline = nested_dict(run.get("processBaseline"),
                                           f"{run['processRunId']}.processBaseline")
            cycle5 = run["cycles"][-1]
            cycle5_final = nested_dict(cycle5.get("afterFinalUndeploy"),
                                       "cycle5.afterFinalUndeploy")
            baseline_thread_count = process_baseline.get("liveThreadCount")
            cycle5_thread_count = cycle5_final.get("liveThreadCount")
            require(isinstance(baseline_thread_count, int)
                    and not isinstance(baseline_thread_count, bool)
                    and baseline_thread_count >= 0,
                    f"{run['processRunId']}: invalid process-baseline thread count")
            require(isinstance(cycle5_thread_count, int)
                    and not isinstance(cycle5_thread_count, bool)
                    and cycle5_thread_count >= 0,
                    f"{run['processRunId']}: invalid C5 final thread count")
            delta = cycle5_thread_count - baseline_thread_count
            evidence_delta = cycle5.get(
                "finalUndeployThreadEvidenceFinal", {}
            ).get("threadStockDeltaVsProcessBaseline")
            require(isinstance(evidence_delta, int)
                    and not isinstance(evidence_delta, bool)
                    and evidence_delta == delta,
                    f"{run['processRunId']}: C5 thread delta disagrees with evidence")
            delta_values.append(delta)
            final_checkpoint_count += len(run["cycles"])
            interval_start = len(intervals)
            for cycle in run["cycles"]:
                intervals.append(interval_evidence(run, cycle, "first-undeploy"))
                intervals.append(interval_evidence(run, cycle, "final-undeploy"))
            run_intervals = intervals[interval_start:]
            require(
                len(as_list(run.get("threadLeakWarnings"),
                            f"{run['processRunId']}.threadLeakWarnings"))
                == sum(item["threadLeakWarningEventCount"]
                       for item in run_intervals),
                f"{run['processRunId']}: process and interval thread-leak "
                "warning counts differ",
            )
            fork_details.append({
                "processRunId": fork["processRunId"],
                "fork": fork["fork"],
                "block": fork["block"],
                "processBaselineLiveThreads": process_baseline["liveThreadCount"],
                "cycle5FinalLiveThreads": cycle5_final["liveThreadCount"],
                "cycle5FinalLiveThreadDeltaVsProcessBaseline": delta,
                "absoluteFinalLiveThreadSlopePerCycle":
                fork["absoluteFinalLiveThreadSlopePerCycle"],
                "absoluteFinalWebappClassloaderSlopePerCycle":
                fork["absoluteFinalWebappClassloaderSlopePerCycle"],
                "absoluteFinalHeapSlopeBytesPerCycle":
                fork["absoluteFinalHeapSlopeBytesPerCycle"],
                "absoluteFinalNativeCommittedSlopeBytesPerCycle":
                fork["absoluteFinalNativeCommittedSlopeBytesPerCycle"],
                "targetFindleaksObservationCount":
                fork["targetFindleaksObservationCount"],
                "threadLeakWarningCount": fork["threadLeakWarningCount"],
            })
        thread_delta_stats = descriptive(delta_values)
        thread_slope = stats_from_row(summary, "absoluteFinalLiveThreadSlopePerCycle")
        classloader_slope = stats_from_row(
            summary, "absoluteFinalWebappClassloaderSlopePerCycle"
        )
        heap_slope_bytes = stats_from_row(
            summary, "absoluteFinalHeapSlopeBytesPerCycle"
        )
        nmt_slope_bytes = stats_from_row(
            summary, "absoluteFinalNativeCommittedSlopeBytesPerCycle"
        )
        warning_intervals = sum(
            interval["threadLeakWarningEventCount"] > 0 for interval in intervals
        )
        warning_events = sum(
            interval["threadLeakWarningEventCount"] for interval in intervals
        )
        findleaks_intervals = sum(
            interval["targetContextObservedInFindleaks"] for interval in intervals
        )
        warning_by_phase = {
            phase: {
                "evaluableIntervals": sum(
                    interval["undeployPhase"] == phase for interval in intervals
                ),
                "intervalsWithWarning": sum(
                    interval["undeployPhase"] == phase
                    and interval["threadLeakWarningEventCount"] > 0
                    for interval in intervals
                ),
                "warningEvents": sum(
                    interval["threadLeakWarningEventCount"]
                    for interval in intervals
                    if interval["undeployPhase"] == phase
                ),
            }
            for phase in ("first-undeploy", "final-undeploy")
        }
        findleaks_by_phase = {
            phase: {
                "evaluableIntervals": sum(
                    interval["undeployPhase"] == phase for interval in intervals
                ),
                "intervalsWithTargetContext": sum(
                    interval["undeployPhase"] == phase
                    and interval["targetContextObservedInFindleaks"]
                    for interval in intervals
                ),
            }
            for phase in ("first-undeploy", "final-undeploy")
        }
        require(warning_events == sum(row["threadLeakWarningCount"]
                                      for row in valid_forks),
                f"{provider}: warning event count differs from lifecycle analysis")
        require(findleaks_intervals == sum(row["targetFindleaksObservationCount"]
                                          for row in valid_forks),
                f"{provider}: findleaks interval count differs from lifecycle analysis")
        require(
            summary["forksWithTargetFindleaksObservation"] == len({
                interval["processRunId"] for interval in intervals
                if interval["targetContextObservedInFindleaks"]
            }),
            f"{provider}: findleaks JVM count differs from lifecycle summary",
        )
        require(
            summary["forksWithThreadLeakWarning"] == len({
                interval["processRunId"] for interval in intervals
                if interval["threadLeakWarningEventCount"] > 0
            }),
            f"{provider}: warning JVM count differs from lifecycle summary",
        )
        generic_warning_lines = sum(
            list_count(run_index[row["processRunId"]].get("warnings", []),
                       "process warnings")
            for row in valid_forks
        )
        leak_warning_lines = sum(
            list_count(run_index[row["processRunId"]].get("leakWarnings", []),
                       "process leak warnings")
            for row in valid_forks
        )
        complete_series = sum(
            row["cycleCount"] == 5 and row["redeployReadyAllCycles"] is True
            for row in valid_forks
        )
        row = {
            "provider": provider,
            "displayName": DISPLAY_NAMES[provider],
            "validLifecycleJvms": len(valid_forks),
            "plannedLifecycleJvms": 6,
            "completeJvmSeries": complete_series,
            "finalCheckpointsAfterSecondUndeploy": final_checkpoint_count,
            "plannedFinalCheckpointsAfterSecondUndeploy": 30,
            "jvmsWithTargetContextInFindleaks":
            summary["forksWithTargetFindleaksObservation"],
            "targetFindleaksIntervals": findleaks_intervals,
            "evaluableFindleaksIntervals": len(intervals),
            "findleaksByUndeployPhase": findleaks_by_phase,
            "tomcatThreadLeak": {
                "evaluableIntervals": len(intervals),
                "intervalsWithWarning": warning_intervals,
                "jvmsWithWarning": summary["forksWithThreadLeakWarning"],
                "warningEvents": warning_events,
                "byUndeployPhase": warning_by_phase,
            },
            "runnerWarningLines": generic_warning_lines,
            "runnerLeakWarningLines": leak_warning_lines,
            "cycle5FinalLiveThreadDeltaVsProcessBaseline": thread_delta_stats,
            "absoluteFinalLiveThreadSlopePerCycle": thread_slope,
            "absoluteFinalWebappClassloaderSlopePerCycle": classloader_slope,
            "absoluteFinalHeapSlopeBytesPerCycle": heap_slope_bytes,
            "absoluteFinalHeapSlopeMebibytesPerCycle":
            scaled_stats(heap_slope_bytes, 1024.0 * 1024.0),
            "absoluteFinalNativeCommittedSlopeBytesPerCycle": nmt_slope_bytes,
            "absoluteFinalNativeCommittedSlopeMebibytesPerCycle":
            scaled_stats(nmt_slope_bytes, 1024.0 * 1024.0),
            "forks": fork_details,
            "undeployIntervals": intervals,
        }
        heap_mib = row["absoluteFinalHeapSlopeMebibytesPerCycle"]
        nmt_mib = row["absoluteFinalNativeCommittedSlopeMebibytesPerCycle"]
        formatted = {
            "validLifecycleJvms": denominator(len(valid_forks), 6),
            "completeJvmSeries": denominator(complete_series, 6),
            "finalCheckpoints": denominator(final_checkpoint_count, 30),
            "jvmsWithTargetContextInFindleaks": denominator(
                summary["forksWithTargetFindleaksObservation"], 6
            ),
            "warningIntervalsEvaluable": denominator(len(intervals), 60),
            "warningIntervalsWithWarning": denominator(warning_intervals, 60),
            "jvmsWithWarning": denominator(summary["forksWithThreadLeakWarning"], 6),
            "warningEvents": str(warning_events),
            "cycle5ThreadDeltaMedianRange": median_range_text(
                thread_delta_stats, smart=True, signed=True
            ),
            "threadSlopeMedianRange": median_range_text(
                thread_slope, 3, smart=True, signed=True
            ),
            "classloaderSlopeMedianRange": median_range_text(
                classloader_slope, 3, smart=True, signed=True
            ),
            "heapSlopeMibMedianRange": median_range_text(
                heap_mib, 3, smart=True, signed=True
            ),
            "nmtSlopeMibMedianRange": median_range_text(
                nmt_mib, 3, smart=True, signed=True
            ),
        }
        formatted["coveragePaperRow"] = (
            f"| {DISPLAY_NAMES[provider]} | {formatted['validLifecycleJvms']} | "
            f"{formatted['finalCheckpoints']} | "
            f"{formatted['jvmsWithTargetContextInFindleaks']} |"
        )
        formatted["warningPaperRow"] = (
            f"| {DISPLAY_NAMES[provider]} | "
            f"{formatted['warningIntervalsEvaluable']} | "
            f"{formatted['warningIntervalsWithWarning']} | "
            f"{formatted['jvmsWithWarning']} | {formatted['warningEvents']} |"
        )
        formatted["threadPaperRow"] = (
            f"| {DISPLAY_NAMES[provider]} | {formatted['completeJvmSeries']} | "
            f"{formatted['cycle5ThreadDeltaMedianRange']} | "
            f"{formatted['threadSlopeMedianRange']} | "
            f"{formatted['classloaderSlopeMedianRange']} |"
        )
        formatted["memoryPaperRow"] = (
            f"| {DISPLAY_NAMES[provider]} | {formatted['completeJvmSeries']} | "
            f"{formatted['heapSlopeMibMedianRange']} | "
            f"{formatted['nmtSlopeMibMedianRange']} |"
        )
        row["formatted"] = formatted
        by_provider.append(row)

    return {
        "checkpointDefinition": {
            "earlySeconds": raw["lifecycleProtocol"]["earlyThreadObservationSeconds"],
            "finalSeconds":
            raw["lifecycleProtocol"]["finalObservationAndFindleaksSeconds"],
            "earlyTargetSeconds":
            raw["lifecycleProtocol"]["earlyThreadObservationSeconds"],
            "finalDiagnosticTargetSeconds":
            raw["lifecycleProtocol"]["finalObservationAndFindleaksSeconds"],
            "targetSemantics": (
                "lower bounds for diagnostic start times, not exact sampling instants"
            ),
            "finalExplicitGcCount":
            raw["lifecycleProtocol"]["forcedGcCountPerFinalSnapshot"],
            "slopePointsPerJvm": 5,
            "slopeEstimator": "ordinary least squares over cycle numbers 1..5",
        },
        "timingEvidence": extract_post_undeploy_timing(raw),
        "countingDefinitions": {
            "threadLeakWarningEvent": (
                "one retained Tomcat warning log record matched in the log delta "
                "of one undeploy; stack-trace continuation lines are not counted"
            ),
            "findleaksInterval": (
                "one post-undeploy Manager observation whose preserved occurrence "
                "list contains the provider context path"
            ),
        },
        "byProvider": by_provider,
    }


def extract_jcs248(raw: dict[str, Any], analysis: dict[str, Any],
                   lifecycle: dict[str, Any]) -> dict[str, Any]:
    lifecycle_by_provider = {
        row["provider"]: row for row in lifecycle["byProvider"]
    }
    lifecycle_forks = {
        row["processRunId"]: row for row in analysis["lifecycleForks"]
    }
    output = []
    for provider in JCS_PROVIDERS:
        runs = sorted(
            (run for run in raw["processRuns"] if run["provider"] == provider),
            key=lambda run: run["fork"],
        )
        intervals = [
            interval_evidence(run, cycle, phase)
            for run in runs
            for cycle in run["cycles"]
            for phase in ("first-undeploy", "final-undeploy")
        ]
        require(len(intervals) == 60,
                f"{provider}: JCS-248 requires 60 evaluable intervals")
        positive_run_ids = sorted({
            interval["processRunId"] for interval in intervals
            if interval["corroborated"]
        }, key=lambda run_id: lifecycle_forks[run_id]["fork"])
        corroborated_count = sum(interval["corroborated"] for interval in intervals)
        early_total = sum(
            interval["earlySignatureObservationCount"] for interval in intervals
        )
        final_total = sum(
            interval["finalSignatureObservationCount"] for interval in intervals
        )
        warning_intervals = sum(
            interval["threadLeakWarningEventCount"] > 0 for interval in intervals
        )
        warning_events = sum(
            interval["threadLeakWarningEventCount"] for interval in intervals
        )
        findleaks_jvms = len({
            interval["processRunId"] for interval in intervals
            if interval["targetContextObservedInFindleaks"]
        })
        for run in runs:
            source = lifecycle_forks[run["processRunId"]]
            derived = [
                {
                    "cycle": interval["cycle"],
                    "phase": interval["undeployPhase"],
                    "signatureObservationCount":
                    interval["signatureObservationCountAcrossCheckpoints"],
                    "threadLeakWarningCount":
                    interval["threadLeakWarningEventCount"],
                }
                for interval in intervals
                if interval["processRunId"] == run["processRunId"]
                and interval["corroborated"]
            ]
            require(source["jcs248CorroboratedIntervals"] == derived,
                    f"{run['processRunId']}: corroborated interval details differ")
            require(source["jcs248CorroboratedUndeployCount"] == len(derived),
                    f"{run['processRunId']}: corroborated interval count differs")
            require(source["jcs248CorroboratedSignalObserved"] is bool(derived),
                    f"{run['processRunId']}: corroborated JVM boolean differs")
        observational_threshold_met = len(positive_run_ids) >= 5
        lifecycle_row = lifecycle_by_provider[provider]
        row = {
            "provider": provider,
            "displayName": DISPLAY_NAMES[provider],
            "validJvms": len(runs),
            "plannedJvms": 6,
            "evaluablePostUndeployIntervals": len(intervals),
            "plannedPostUndeployIntervals": 60,
            "positiveJvms": len(positive_run_ids),
            "positiveJvmIds": positive_run_ids,
            "corroboratedIntervals": corroborated_count,
            "earlyCheckpoint": {
                "signatureObservations": early_total,
                "intervalsWithAtLeastOneSignature": sum(
                    interval["earlySignatureObservationCount"] > 0
                    for interval in intervals
                ),
                "jvmsWithAtLeastOneSignature": len({
                    interval["processRunId"] for interval in intervals
                    if interval["earlySignatureObservationCount"] > 0
                }),
            },
            "finalCheckpoint": {
                "signatureObservations": final_total,
                "intervalsWithAtLeastOneSignature": sum(
                    interval["finalSignatureObservationCount"] > 0
                    for interval in intervals
                ),
                "jvmsWithAtLeastOneSignature": len({
                    interval["processRunId"] for interval in intervals
                    if interval["finalSignatureObservationCount"] > 0
                }),
            },
            "threadLeakWarningIntervals": warning_intervals,
            "threadLeakWarningJvms": lifecycle_row["tomcatThreadLeak"]["jvmsWithWarning"],
            "threadLeakWarningEvents": warning_events,
            "jvmsWithTargetContextInFindleaks": findleaks_jvms,
            "prespecifiedPositiveControlCriterionApplies": provider == "jcs321",
            "prespecifiedPositiveControlCriterion": "at least 5 positive JVMs out of 6",
            "prespecifiedPositiveControlCriterionMet":
            observational_threshold_met if provider == "jcs321" else None,
            "sameThresholdMetObservationally": observational_threshold_met,
            "intervals": intervals,
            "lifecycleSlopes": {
                "threadPerCycle":
                lifecycle_row["absoluteFinalLiveThreadSlopePerCycle"],
                "classloaderPerCycle":
                lifecycle_row["absoluteFinalWebappClassloaderSlopePerCycle"],
                "heapMebibytesPerCycle":
                lifecycle_row["absoluteFinalHeapSlopeMebibytesPerCycle"],
                "nativeCommittedMebibytesPerCycle":
                lifecycle_row[
                    "absoluteFinalNativeCommittedSlopeMebibytesPerCycle"
                ],
            },
        }
        formatted = {
            "validJvms": denominator(len(runs), 6),
            "evaluableIntervals": denominator(len(intervals), 60),
            "positiveJvms": denominator(len(positive_run_ids), 6),
            "corroboratedIntervals": denominator(corroborated_count, 60),
            "earlySignatures": str(early_total),
            "finalSignatures": str(final_total),
            "warningCardinalities": (
                f"{warning_intervals}/60; "
                f"{lifecycle_row['tomcatThreadLeak']['jvmsWithWarning']}/6; "
                f"{warning_events}"
            ),
            "findleaksJvms": denominator(findleaks_jvms, 6),
            "criterion": (
                "soddisfatto" if observational_threshold_met else "non soddisfatto"
            ),
        }
        formatted["coveragePaperCells"] = {
            "validJvms": formatted["validJvms"],
            "evaluableIntervals": formatted["evaluableIntervals"],
            "positiveJvms": formatted["positiveJvms"],
            "corroboratedIntervals": formatted["corroboratedIntervals"],
            "criterion": formatted["criterion"],
        }
        row["formatted"] = formatted
        output.append(row)
    return {
        "definition": {
            "intervalsPerJvm": 10,
            "corroboratedInterval": (
                "at least one JCS-specific signature at the early or final dump AND "
                "at least one Tomcat thread-leak warning in the same undeploy log delta"
            ),
            "positiveJvm": "at least one corroborated interval out of ten",
            "positiveControlThreshold": "at least five positive JCS 3.2.1 JVMs out of six",
            "signatureObservation": (
                "one JCS-specific worker record in one checkpoint dump; the same "
                "surviving worker observed at both checkpoints contributes two observations"
            ),
            "warningEvent": "one retained Tomcat warning log record",
        },
        "byJcsLine": output,
    }


def extract_environment_and_provenance(raw: dict[str, Any],
                                       results_path: Path,
                                       analysis_path: Path) -> dict[str, Any]:
    preflight = raw["campaignPreflight"]
    source = raw["sourceProvenance"]
    protocol_row = next(
        row for row in source["files"]
        if row["path"] == EXPECTED_PROTOCOL_PATH
    )
    environment = {
        "recordedCampaignPreflight": preflight,
        "campaignStartedAt": raw["campaignStartedAt"],
        "campaignFinishedAt": raw["campaignFinishedAt"],
        "tomcatVersion": preflight.get("Tomcat Version"),
        "jvmVersion": preflight.get("JVM Version"),
        "jvmVendor": preflight.get("JVM Vendor"),
        "containerOs": preflight.get("containerOS"),
        "containerKernel": preflight.get("containerKernel"),
        "containerCpuModel": preflight.get("containerCpuModel"),
        "containerVisibleProcessors": preflight.get("containerVisibleProcessors"),
        "containerCpuLimit": preflight.get("containerCpuLimit"),
        "containerMemoryLimitBytes": preflight.get("containerMemoryLimitBytes"),
        "dockerServerVersion": preflight.get("dockerServerVersion"),
        "dockerServerOperatingSystem": preflight.get("dockerServerOperatingSystem"),
        "dockerServerKernelVersion": preflight.get("dockerServerKernelVersion"),
        "dockerServerArchitecture": preflight.get("dockerServerArchitecture"),
        "javaOptions": preflight.get("javaOptions"),
        "jvmCommandLine": preflight.get("jvmCommandLine"),
        "jvmFlags": preflight.get("jvmFlags"),
        "runtimeBaseImage": preflight.get("runtimeBaseImage"),
        "buildBaseImage": preflight.get("buildBaseImage"),
        "benchmarkConfiguration": raw["configuration"],
        "lifecycleProtocol": raw["lifecycleProtocol"],
        "schedule": raw["schedule"],
    }
    memory_bytes = int(preflight["containerMemoryLimitBytes"])
    environment["formatted"] = {
        "cpuLimit": italian_smart_number(preflight["containerCpuLimit"]),
        "memoryLimitGiB": f"{italian_number(memory_bytes / (1024.0 ** 3), 2)} GiB",
        "jvm": f"{preflight.get('JVM Vendor')} {preflight.get('JVM Version')}",
        "tomcat": str(preflight.get("Tomcat Version")),
    }
    provenance = {
        "resultsFile": results_path.name,
        "resultsSha256": sha256_file(results_path),
        "analysisFile": analysis_path.name,
        "analysisSha256": sha256_file(analysis_path),
        "analysisSha256DeclaredInResults": raw["analysisSha256"],
        "sourceManifestSha256": source.get("manifestSha256"),
        "sourceFiles": source.get("files"),
        "protocol": protocol_row,
        "jcs4": {
            "version": preflight.get("jcs4Version"),
            "sourceCommit": preflight.get("jcs4SourceCommit"),
            "artifactCoordinates": preflight.get("jcs4ArtifactCoordinates"),
            "artifactSha256": preflight.get("jcs4ArtifactSha256"),
        },
        "jcs321": {
            "version": preflight.get("jcs321Version"),
            "artifactCoordinates": preflight.get("jcs321ArtifactCoordinates"),
            "artifactSha256": preflight.get("jcs321ArtifactSha256"),
            "expectedArtifactSha256": preflight.get("jcs321ExpectedSha256"),
        },
        "warSha256": preflight.get("warSha256"),
        "artifactManifest": preflight.get("artifactManifest"),
        "archivedBuildFiles": preflight.get("archivedBuildFiles"),
        "diagnosticArchive": raw.get("diagnosticArchive"),
    }
    return {"environment": environment, "provenance": provenance}


def extract(results_path: Path, analysis_path: Path) -> dict[str, Any]:
    raw = load_json_object(results_path, "results")
    analysis = load_json_object(analysis_path, "analysis")
    campaign_id = validate_inputs(raw, analysis, results_path, analysis_path)

    valid_run_ids = {
        row["processRunId"] for row in analysis["lifecycleForks"]
        if row["blockValid"] is True
    }
    quality = extract_quality_control(raw, analysis, valid_run_ids)
    primary = extract_primary_performance(analysis)
    ratios = extract_paired_ratios(analysis)
    sensitivity = extract_sensitivity(analysis)
    lifecycle = extract_lifecycle(raw, analysis)
    jcs248 = extract_jcs248(raw, analysis, lifecycle)
    environment_and_provenance = extract_environment_and_provenance(
        raw, results_path, analysis_path
    )

    return {
        "schemaVersion": 1,
        "campaignId": campaign_id,
        "protocolVersion": EXPECTED_PROTOCOL_VERSION,
        "datasetStatus": "complete-and-accepted",
        "numericPolicy": {
            "numericFields": "unrounded source values or unrounded deterministic derivations",
            "formattedFields": "rounded presentation strings; never use them for recomputation",
            "quartiles": "linear interpolation at (n - 1) * p, matching campaign analysis",
        },
        "qualityControl": quality,
        "primaryPerformance": primary,
        "pairedThroughputRatios": ratios,
        "sensitivityWithoutCycle1": sensitivity,
        "lifecycle": lifecycle,
        "jcs248PositiveControl": jcs248,
        **environment_and_provenance,
    }


def validate_output_destination(
    results_path: Path, analysis_path: Path, output_path: Path
) -> None:
    require(output_path != results_path,
            "refusing to overwrite the definitive results JSON")
    require(output_path != analysis_path,
            "refusing to overwrite the definitive analysis JSON")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract unrounded and paper-formatted values from the definitive "
            "Beyond Throughput v4.2 campaign."
        )
    )
    parser.add_argument("--results", required=True, type=Path,
                        help="definitive ...-results.json")
    parser.add_argument("--analysis", required=True, type=Path,
                        help="matching definitive ...-analysis.json")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional path for the extracted JSON; stdout is used when omitted",
    )
    arguments = parser.parse_args(argv)
    results_path = arguments.results.resolve()
    analysis_path = arguments.analysis.resolve()
    destination = arguments.output.resolve() if arguments.output is not None else None
    try:
        require(results_path != analysis_path,
                "results and analysis paths must differ")
        if destination is not None:
            validate_output_destination(results_path, analysis_path, destination)
        output = extract(results_path, analysis_path)
        if destination is not None:
            campaign_id = output["campaignId"]
            require(
                destination.name == f"{campaign_id}-paper-values.json",
                "output filename must exactly match the v4.2 campaignId and "
                "end with -paper-values.json",
            )
        serialized = json.dumps(
            output, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False
        ) + "\n"
        if destination is None:
            sys.stdout.write(serialized)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(serialized, encoding="utf-8")
            print(f"Extracted paper values: {destination}", file=sys.stderr)
    except (ExtractionError, OSError, UnicodeError) as failure:
        print(f"extract_paper_v4_2: {failure}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

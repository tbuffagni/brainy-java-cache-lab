#!/usr/bin/env python3
"""Fill the v4.2 paper template from one definitive paper-values JSON.

The filler deliberately accepts only the strict output of
``extract_paper_v4_2.py``.  It never reads v4.1, raw results, or analysis files,
and it refuses partial templates and partial mappings.

Source note
-----------
The extractor does not expose a field named ``completedCycles``.  The only
derived completion value in this module is therefore the number of observed
post-undeploy timing intervals divided by two (the frozen protocol has two
undeploy intervals per cycle).  The result must exactly match
``qualityControl.denominatorDefinition.cyclesTotal``.  No campaign total is
hard-coded as a replacement value.  Abstract and conclusion strings are only
deterministic prose compositions of values that also populate the tables.
There are no other known source gaps.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore")
PRIMARY_PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4")
RATIO_PROVIDERS = ("caffeine", "ehcache", "cache2k")
PAPER_LIFECYCLE_PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4", "nostore")
JCS_PROVIDERS = ("jcs321", "jcs4")
PHASES = ("initial", "redeploy")

PROVIDER_TOKEN = {
    "caffeine": "CAFFEINE",
    "ehcache": "EHCACHE",
    "cache2k": "CACHE2K",
    "jcs4": "JCS4",
    "jcs321": "JCS321",
    "nostore": "NOSTORE",
}
SUMMARY_NAME = {
    "caffeine": "Caffeine",
    "ehcache": "Ehcache",
    "cache2k": "cache2k",
    "jcs4": "snapshot JCS 4",
    "jcs321": "JCS 3.2.1",
    "nostore": "`no-store`",
}

EXPECTED_SCHEMA_VERSION = 1
EXPECTED_PROTOCOL_VERSION = "4.2"
EXPECTED_DATASET_STATUS = "complete-and-accepted"
EXPECTED_CAMPAIGN_ID = re.compile(
    r"article1-unified-v4-2-fb3f101b-\d{8}-\d{6}"
)
EXPECTED_PROTOCOL_PATH = "press/article/protocollo-campagna-v4-2.md"
EXPECTED_PROTOCOL_SHA256 = (
    "4f364de62f696c687d3175931f29c69013f4ad9d96303558e2444bfc5c73596f"
)
NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT = (
    "Nessuna deviazione dai parametri machine-verificabili del protocollo "
    "è registrata nel dataset"
)
PLACEHOLDER_RE = re.compile(r"\{\{(V42_[A-Z0-9_]+)\}\}")
EXPECTED_PLACEHOLDER_COUNT = 279


class FillError(ValueError):
    """Raised when publication values cannot be mapped without guessing."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FillError(message)


def object_value(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def array_value(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def text_value(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    require("{{" not in value and "}}" not in value,
            f"{label} unexpectedly contains a template marker")
    return value


def integer_value(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool),
            f"{label} must be an integer")
    require(value >= 0, f"{label} must be non-negative")
    return value


def boolean_value(value: Any, label: str) -> bool:
    require(isinstance(value, bool), f"{label} must be boolean")
    return value


def number_value(value: Any, label: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{label} must be numeric")
    number = float(value)
    require(math.isfinite(number), f"{label} must be finite")
    return number


def member(mapping: Mapping[str, Any], key: str, label: str) -> Any:
    require(key in mapping, f"missing source value {label}.{key}")
    return mapping[key]


def child_object(mapping: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    return object_value(member(mapping, key, label), f"{label}.{key}")


def child_array(mapping: Mapping[str, Any], key: str, label: str) -> list[Any]:
    return array_value(member(mapping, key, label), f"{label}.{key}")


def child_text(mapping: Mapping[str, Any], key: str, label: str) -> str:
    return text_value(member(mapping, key, label), f"{label}.{key}")


def child_integer(mapping: Mapping[str, Any], key: str, label: str) -> int:
    return integer_value(member(mapping, key, label), f"{label}.{key}")


def child_boolean(mapping: Mapping[str, Any], key: str, label: str) -> bool:
    return boolean_value(member(mapping, key, label), f"{label}.{key}")


def index_rows(rows: Iterable[Any], keys: tuple[str, ...], label: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    output: dict[tuple[Any, ...], dict[str, Any]] = {}
    for position, raw_row in enumerate(rows):
        row = object_value(raw_row, f"{label}[{position}]")
        index_key = tuple(member(row, key, f"{label}[{position}]") for key in keys)
        require(index_key not in output, f"duplicate {label} key {index_key!r}")
        output[index_key] = row
    return output


def require_exact_keys(index: Mapping[tuple[Any, ...], Any],
                       expected: set[tuple[Any, ...]], label: str) -> None:
    actual = set(index)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    require(not missing and not unexpected,
            f"{label} keys differ; missing={missing!r}, unexpected={unexpected!r}")


def italian_number(value: float | int, decimals: int = 3,
                   signed: bool = False) -> str:
    number = number_value(value, "number to format")
    text = f"{number:+.{decimals}f}" if signed else f"{number:.{decimals}f}"
    return text.replace(".", ",")


def italian_smart_number(value: float | int, decimals: int = 3,
                         signed: bool = False) -> str:
    number = number_value(value, "number to format")
    if number.is_integer():
        return f"{int(number):+d}" if signed else str(int(number))
    text = italian_number(number, decimals, signed=signed)
    while text.endswith("0"):
        text = text[:-1]
    return text[:-1] if text.endswith(",") else text


def italian_integer(value: int) -> str:
    integer = integer_value(value, "integer to format")
    return f"{integer:,}".replace(",", ".")


def min_max_text(minimum: float | int, maximum: float | int,
                 decimals: int = 3) -> str:
    return f"{italian_number(minimum, decimals)}–{italian_number(maximum, decimals)}"


def integer_min_max_text(minimum: int, maximum: int) -> str:
    return f"{italian_integer(minimum)}–{italian_integer(maximum)}"


def median_range_text(stats_value: Any, decimals: int = 3,
                      smart: bool = True, signed: bool = True) -> str:
    stats = object_value(stats_value, "descriptive statistics")
    formatter = italian_smart_number if smart else italian_number
    median = formatter(member(stats, "median", "descriptive statistics"), decimals,
                       signed=signed)
    minimum = formatter(member(stats, "minimum", "descriptive statistics"), decimals,
                        signed=signed)
    maximum = formatter(member(stats, "maximum", "descriptive statistics"), decimals,
                        signed=signed)
    return f"{median} [{minimum}–{maximum}]"


def remove_required_suffix(value: Any, suffix: str, label: str) -> str:
    text = text_value(value, label)
    require(text.endswith(suffix), f"{label} must end with {suffix!r}")
    stripped = text[:-len(suffix)]
    require(bool(stripped), f"{label} contains no value before {suffix!r}")
    return stripped


def validate_metadata(values: Mapping[str, Any]) -> str:
    require(member(values, "schemaVersion", "paper-values") == EXPECTED_SCHEMA_VERSION,
            "paper-values schemaVersion must be 1")
    protocol_version = member(values, "protocolVersion", "paper-values")
    require(protocol_version == EXPECTED_PROTOCOL_VERSION,
            "paper-values protocolVersion must be 4.2; v4.1 is not accepted")
    require(member(values, "datasetStatus", "paper-values") == EXPECTED_DATASET_STATUS,
            "paper-values datasetStatus must be complete-and-accepted")
    campaign_id = text_value(member(values, "campaignId", "paper-values"),
                             "paper-values.campaignId")
    require(EXPECTED_CAMPAIGN_ID.fullmatch(campaign_id) is not None,
            "paper-values campaignId is not the frozen v4.2 fb3f101b campaign")
    require("v4-1" not in campaign_id.lower(), "v4.1 campaign identifiers are forbidden")

    provenance = child_object(values, "provenance", "paper-values")
    protocol = child_object(provenance, "protocol", "paper-values.provenance")
    require(child_text(protocol, "path", "paper-values.provenance.protocol")
            == EXPECTED_PROTOCOL_PATH,
            "paper-values points to a different protocol path")
    require(child_text(protocol, "sha256", "paper-values.provenance.protocol").lower()
            == EXPECTED_PROTOCOL_SHA256,
            "paper-values protocol SHA-256 differs from the frozen v4.2 protocol")
    return campaign_id


def build_replacements(values_value: Any) -> dict[str, str]:
    """Return the complete, strict placeholder mapping for the current paper."""
    values = object_value(values_value, "paper-values")
    validate_metadata(values)
    replacements: dict[str, str] = {}

    def put(name: str, value: Any) -> None:
        require(PLACEHOLDER_RE.fullmatch("{{" + name + "}}") is not None,
                f"invalid placeholder name {name!r}")
        require(name not in replacements, f"duplicate replacement {name}")
        replacements[name] = text_value(str(value), f"replacement {name}")

    quality = child_object(values, "qualityControl", "paper-values")
    deviations = child_object(
        quality, "protocolDeviationAssessment", "paper-values.qualityControl"
    )
    require(
        child_boolean(
            deviations,
            "allMachineVerifiableControlsPassed",
            "paper-values.qualityControl.protocolDeviationAssessment",
        ),
        "the machine-verifiable v4.2 controls did not all pass",
    )
    deviation_statement = child_text(
        deviations,
        "statement",
        "paper-values.qualityControl.protocolDeviationAssessment",
    )
    require(
        deviation_statement == NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT,
        "protocol-deviation statement is not the prudent frozen wording",
    )
    put("V42_PROTOCOL_DEVIATIONS", deviation_statement)
    denominators = child_object(quality, "denominatorDefinition",
                                "paper-values.qualityControl")
    expected_denominators = {
        "processesPerProvider": 6,
        "workloadWindowsPerProvider": 60,
        "forkPhasePairsPerProvider": 12,
        "cyclesTotal": 180,
        "workloadWindowsTotal": 360,
        "processesTotal": 36,
    }
    for key, expected in expected_denominators.items():
        require(child_integer(denominators, key,
                              "paper-values.qualityControl.denominatorDefinition") == expected,
                f"unexpected v4.2 denominator {key}")

    qc_index = index_rows(child_array(quality, "byProvider",
                                      "paper-values.qualityControl"),
                          ("provider",), "qualityControl.byProvider")
    require_exact_keys(qc_index, {(provider,) for provider in PROVIDERS},
                       "qualityControl.byProvider")
    observed_ranges_by_provider: dict[str, dict[str, Any]] = {}
    for provider in PROVIDERS:
        row = qc_index[(provider,)]
        token = PROVIDER_TOKEN[provider]
        qc_label = f"qualityControl.byProvider.{provider}"
        processes_acquired = child_integer(row, "processesAcquired", qc_label)
        valid_jvms = child_integer(row, "validJvms", qc_label)
        workload_windows = child_integer(row, "workloadWindowsAcquired", qc_label)
        gates_passed = child_integer(row, "semanticGateWindowsPassed", qc_label)
        require(
            processes_acquired == 6
            and valid_jvms == 6
            and workload_windows == 60
            and gates_passed <= workload_windows,
            f"{qc_label} has cardinalities incompatible with the definitive campaign",
        )
        put(f"V42_{token}_PROCESSES", processes_acquired)
        put(f"V42_{token}_VALID_JVMS", valid_jvms)
        put(f"V42_{token}_WINDOWS", workload_windows)
        put(f"V42_{token}_GATES", gates_passed)
        if provider in PRIMARY_PROVIDERS:
            phase_pairs = child_integer(
                row, "performanceForkPhasePairsIncluded", qc_label
            )
            require(phase_pairs <= 12,
                    f"{qc_label} has more than 12 performance phase pairs")
            put(f"V42_{token}_PHASE_PAIRS", phase_pairs)

        evidence_label = (
            f"qualityControl.byProvider.{provider}.observedSemanticEvidence"
        )
        evidence = child_object(row, "observedSemanticEvidence",
                                f"qualityControl.byProvider.{provider}")
        def checked_range(source_key: str, *, integer: bool = False,
                          fraction: bool = False) -> tuple[float | int, float | int]:
            stats = child_object(evidence, source_key, evidence_label)
            require(child_integer(stats, "n", f"{evidence_label}.{source_key}") == 60,
                    f"{provider}.{source_key} must describe all 60 windows")
            minimum_raw = member(stats, "minimum", f"{evidence_label}.{source_key}")
            maximum_raw = member(stats, "maximum", f"{evidence_label}.{source_key}")
            if integer:
                minimum: float | int = integer_value(
                    minimum_raw, f"{evidence_label}.{source_key}.minimum"
                )
                maximum: float | int = integer_value(
                    maximum_raw, f"{evidence_label}.{source_key}.maximum"
                )
            else:
                minimum = number_value(
                    minimum_raw, f"{evidence_label}.{source_key}.minimum"
                )
                maximum = number_value(
                    maximum_raw, f"{evidence_label}.{source_key}.maximum"
                )
            require(minimum <= maximum,
                    f"{evidence_label}.{source_key} has reversed bounds")
            if fraction:
                require(0.0 <= float(minimum) <= float(maximum) <= 1.0,
                        f"{evidence_label}.{source_key} must be a fraction")
            return minimum, maximum

        duration_min, duration_max = checked_range("measurementDurationSeconds")
        require(float(duration_min) > 0.0,
                f"{evidence_label}.measurementDurationSeconds must be positive")
        operations_min, operations_max = checked_range(
            "measuredOperations", integer=True
        )
        hit_min, hit_max = checked_range("hitRate", fraction=True)
        after_workload_min, after_workload_max = checked_range(
            "entriesAfterWorkload", integer=True
        )
        after_write_min, after_write_max = checked_range(
            "entriesAfterWriteProbe", integer=True
        )
        single_flight = child_object(evidence, "singleFlight", evidence_label)
        gate_applicable = child_boolean(
            single_flight, "gateApplicable", f"{evidence_label}.singleFlight"
        )
        applicable = child_integer(single_flight, "applicableWindows",
                                   f"{evidence_label}.singleFlight")
        if provider == "nostore":
            require(
                gate_applicable is False
                and applicable == 0
                and member(single_flight, "passedWindows",
                           f"{evidence_label}.singleFlight") is None
                and member(single_flight, "failedWindows",
                           f"{evidence_label}.singleFlight") is None
                and member(single_flight, "allApplicableWindowsPassed",
                           f"{evidence_label}.singleFlight") is None,
                    "no-store single-flight must be represented as inapplicable")
            passed = 0
        else:
            passed = child_integer(single_flight, "passedWindows",
                                   f"{evidence_label}.singleFlight")
            failed = child_integer(single_flight, "failedWindows",
                                   f"{evidence_label}.singleFlight")
            all_passed = child_boolean(
                single_flight,
                "allApplicableWindowsPassed",
                f"{evidence_label}.singleFlight",
            )
            require(
                gate_applicable is True
                and applicable == 60
                and passed <= applicable
                and failed == applicable - passed
                and all_passed is (passed == applicable),
                f"{provider} single-flight cardinalities are inconsistent",
            )
        redeploy_ready = child_object(evidence, "redeployReady", evidence_label)
        redeploy_applicable = child_integer(
            redeploy_ready, "applicableCycles", f"{evidence_label}.redeployReady"
        )
        redeploy_passed = child_integer(
            redeploy_ready, "passedCycles", f"{evidence_label}.redeployReady"
        )
        require(redeploy_applicable == 30 and redeploy_passed <= redeploy_applicable,
                f"{provider} must describe 30 post-redeploy readiness checks")
        if provider == "nostore":
            every_window_meets_components = (
                float(duration_min) >= 5.0
                and int(operations_min) >= 400_000
                and float(hit_min) == 0.0
                and float(hit_max) == 0.0
                and int(after_workload_min) == 0
                and int(after_workload_max) == 0
                and int(after_write_min) == 0
                and int(after_write_max) == 0
            )
        else:
            every_window_meets_components = (
                float(duration_min) >= 5.0
                and int(operations_min) >= 400_000
                and float(hit_min) >= 0.945
                and float(hit_max) <= 0.955
                and int(after_workload_min) >= 9_900
                and int(after_write_min) >= 9_900
                and passed == applicable
            )
        require(
            (gates_passed == 60) is every_window_meets_components,
            f"{provider} aggregate gate count disagrees with the reported RQ1 extrema",
        )

        formatted = child_object(evidence, "formatted", evidence_label)
        expected_formatted = {
            "measurementDurationSecondsMinMax": min_max_text(
                duration_min, duration_max, 3
            ),
            "measuredOperationsMinMax": integer_min_max_text(
                int(operations_min), int(operations_max)
            ),
            "hitRatePercentMinMax": min_max_text(
                float(hit_min) * 100.0, float(hit_max) * 100.0, 3
            ),
            "entriesAfterWorkloadMinMax": integer_min_max_text(
                int(after_workload_min), int(after_workload_max)
            ),
            "entriesAfterWriteProbeMinMax": integer_min_max_text(
                int(after_write_min), int(after_write_max)
            ),
            "singleFlightPassedApplicable": (
                f"{passed}/{applicable}" if applicable else "non applicabile"
            ),
            "redeployReadyPassedApplicable": (
                f"{redeploy_passed}/{redeploy_applicable}"
            ),
        }
        observed_ranges_by_provider[provider] = {
            "durationMinimum": duration_min,
            "durationMaximum": duration_max,
            "operationsMinimum": operations_min,
            "operationsMaximum": operations_max,
            "hitRateMinimum": hit_min,
            "hitRateMaximum": hit_max,
            "entriesAfterWorkloadMinimum": after_workload_min,
            "entriesAfterWorkloadMaximum": after_workload_max,
            "entriesAfterWriteMinimum": after_write_min,
            "entriesAfterWriteMaximum": after_write_max,
            "singleFlightApplicable": applicable,
            "singleFlightPassed": passed,
            "redeployReadyApplicable": redeploy_applicable,
            "redeployReadyPassed": redeploy_passed,
        }
        for source_key, expected_text in expected_formatted.items():
            actual_text = child_text(formatted, source_key,
                                     f"{evidence_label}.formatted")
            require(actual_text == expected_text,
                    f"{evidence_label}.formatted.{source_key} disagrees with raw bounds")

        put(f"V42_{token}_RQ1_DURATION_RANGE_SECONDS",
            expected_formatted["measurementDurationSecondsMinMax"])
        put(f"V42_{token}_RQ1_OPERATIONS_RANGE",
            expected_formatted["measuredOperationsMinMax"])
        put(f"V42_{token}_RQ1_HIT_RATE_RANGE_PERCENT",
            expected_formatted["hitRatePercentMinMax"])
        put(f"V42_{token}_RQ1_POPULATION_AFTER_WORKLOAD_RANGE",
            expected_formatted["entriesAfterWorkloadMinMax"])
        put(f"V42_{token}_RQ1_POPULATION_AFTER_WRITE_RANGE",
            expected_formatted["entriesAfterWriteProbeMinMax"])
        put(f"V42_{token}_RQ1_SINGLE_FLIGHT",
            expected_formatted["singleFlightPassedApplicable"])
        put(f"V42_{token}_RQ1_REDEPLOY_READY",
            expected_formatted["redeployReadyPassedApplicable"])

    blocks = child_object(quality, "williamsBlocks", "paper-values.qualityControl")
    put("V42_COMPLETE_BLOCKS", child_integer(blocks, "completeAtFirstAttemptWithinDataset",
                                              "qualityControl.williamsBlocks"))
    put("V42_INVALID_BLOCKS", child_integer(blocks, "invalidated",
                                             "qualityControl.williamsBlocks"))
    put("V42_REPEATED_BLOCKS", child_integer(blocks, "repeatedWithinDataset",
                                              "qualityControl.williamsBlocks"))
    put("V42_DISTINCT_CONTAINERS", child_integer(blocks, "distinctContainerIds",
                                                  "qualityControl.williamsBlocks"))

    primary = child_object(values, "primaryPerformance", "paper-values")
    throughput_index = index_rows(child_array(primary, "throughput",
                                              "paper-values.primaryPerformance"),
                                  ("provider", "phase"),
                                  "primaryPerformance.throughput")
    performance_keys = {(provider, phase) for provider in PRIMARY_PROVIDERS
                        for phase in PHASES}
    require_exact_keys(throughput_index, performance_keys,
                       "primaryPerformance.throughput")
    latency_index = index_rows(child_array(primary, "sampledLatency",
                                           "paper-values.primaryPerformance"),
                               ("provider", "phase"),
                               "primaryPerformance.sampledLatency")
    require_exact_keys(latency_index, performance_keys,
                       "primaryPerformance.sampledLatency")

    for provider, phase in sorted(performance_keys):
        token = PROVIDER_TOKEN[provider]
        phase_token = phase.upper()
        throughput = throughput_index[(provider, phase)]
        throughput_formatted = child_object(
            throughput, "formatted", f"primaryPerformance.throughput.{provider}.{phase}"
        )
        put(f"V42_{token}_{phase_token}_N",
            child_integer(throughput, "includedForks",
                          f"primaryPerformance.throughput.{provider}.{phase}"))
        put(f"V42_{token}_{phase_token}_TPUT_MEDIAN",
            child_text(throughput_formatted, "medianMops",
                       f"primaryPerformance.throughput.{provider}.{phase}.formatted"))
        put(f"V42_{token}_{phase_token}_TPUT_IQR",
            child_text(throughput_formatted, "q1Q3Mops",
                       f"primaryPerformance.throughput.{provider}.{phase}.formatted"))
        put(f"V42_{token}_{phase_token}_TPUT_RANGE",
            child_text(throughput_formatted, "minMaxMops",
                       f"primaryPerformance.throughput.{provider}.{phase}.formatted"))

        latency = latency_index[(provider, phase)]
        latency_formatted = child_object(
            latency, "formatted", f"primaryPerformance.sampledLatency.{provider}.{phase}"
        )
        put(f"V42_{token}_{phase_token}_LATENCY_N",
            child_integer(latency, "includedForks",
                          f"primaryPerformance.sampledLatency.{provider}.{phase}"))
        for placeholder_suffix, source_key in (
            ("P50_US", "p50MedianMicroseconds"),
            ("P95_US", "p95MedianMicroseconds"),
            ("P99_US", "p99MedianMicroseconds"),
            ("P99_IQR_US", "p99Q1Q3Microseconds"),
        ):
            put(f"V42_{token}_{phase_token}_{placeholder_suffix}",
                child_text(latency_formatted, source_key,
                           f"primaryPerformance.sampledLatency.{provider}.{phase}.formatted"))

    ratios = child_object(values, "pairedThroughputRatios", "paper-values")
    ratio_index = index_rows(child_array(ratios, "primary",
                                         "paper-values.pairedThroughputRatios"),
                             ("provider", "phase"),
                             "pairedThroughputRatios.primary")
    ratio_keys = {(provider, phase) for provider in RATIO_PROVIDERS for phase in PHASES}
    require_exact_keys(ratio_index, ratio_keys, "pairedThroughputRatios.primary")
    for provider, phase in sorted(ratio_keys):
        row = ratio_index[(provider, phase)]
        formatted = child_object(row, "formatted",
                                 f"pairedThroughputRatios.primary.{provider}.{phase}")
        stats = child_object(row, "ratio",
                             f"pairedThroughputRatios.primary.{provider}.{phase}")
        token = PROVIDER_TOKEN[provider]
        phase_token = phase.upper()
        put(f"V42_{token}_{phase_token}_RATIO_N",
            child_integer(stats, "n",
                          f"pairedThroughputRatios.primary.{provider}.{phase}.ratio"))
        for placeholder_suffix, source_key in (
            ("RATIO_MEDIAN", "median"),
            ("RATIO_IQR", "q1Q3"),
            ("RATIO_RANGE", "minMax"),
        ):
            put(f"V42_{token}_{phase_token}_{placeholder_suffix}",
                remove_required_suffix(
                    member(formatted, source_key,
                           f"pairedThroughputRatios.primary.{provider}.{phase}.formatted"),
                    "×",
                    f"pairedThroughputRatios.primary.{provider}.{phase}.formatted.{source_key}",
                ))

    sensitivity_index = index_rows(
        child_array(values, "sensitivityWithoutCycle1", "paper-values"),
        ("provider", "phase"), "sensitivityWithoutCycle1"
    )
    require_exact_keys(sensitivity_index, performance_keys,
                       "sensitivityWithoutCycle1")
    for provider, phase in sorted(performance_keys):
        row = sensitivity_index[(provider, phase)]
        formatted = child_object(row, "formatted",
                                 f"sensitivityWithoutCycle1.{provider}.{phase}")
        token = PROVIDER_TOKEN[provider]
        phase_token = phase.upper()
        put(f"V42_{token}_{phase_token}_PRIMARY_MEDIAN",
            child_text(formatted, "primaryMedianMops",
                       f"sensitivityWithoutCycle1.{provider}.{phase}.formatted"))
        put(f"V42_{token}_{phase_token}_SENSITIVITY_MEDIAN",
            child_text(formatted, "sensitivityMedianMops",
                       f"sensitivityWithoutCycle1.{provider}.{phase}.formatted"))
        put(f"V42_{token}_{phase_token}_COMMON_FORKS",
            child_integer(row, "commonForkCount",
                          f"sensitivityWithoutCycle1.{provider}.{phase}"))
        put(f"V42_{token}_{phase_token}_SENSITIVITY_DELTA",
            remove_required_suffix(
                member(formatted, "commonForkVariationPercent",
                       f"sensitivityWithoutCycle1.{provider}.{phase}.formatted"),
                "%",
                f"sensitivityWithoutCycle1.{provider}.{phase}.formatted.commonForkVariationPercent",
            ))

    lifecycle = child_object(values, "lifecycle", "paper-values")
    lifecycle_index = index_rows(child_array(lifecycle, "byProvider",
                                             "paper-values.lifecycle"),
                                 ("provider",), "lifecycle.byProvider")
    require_exact_keys(lifecycle_index, {(provider,) for provider in PROVIDERS},
                       "lifecycle.byProvider")
    for provider in PAPER_LIFECYCLE_PROVIDERS:
        row = lifecycle_index[(provider,)]
        formatted = child_object(row, "formatted", f"lifecycle.byProvider.{provider}")
        warnings = child_object(row, "tomcatThreadLeak",
                                f"lifecycle.byProvider.{provider}")
        token = PROVIDER_TOKEN[provider]
        lifecycle_label = f"lifecycle.byProvider.{provider}"
        warning_label = f"{lifecycle_label}.tomcatThreadLeak"
        valid_lifecycle_jvms = child_integer(row, "validLifecycleJvms",
                                             lifecycle_label)
        evaluable_intervals = child_integer(row, "evaluableFindleaksIntervals",
                                             lifecycle_label)
        warning_evaluable = child_integer(warnings, "evaluableIntervals",
                                          warning_label)
        warning_intervals = child_integer(warnings, "intervalsWithWarning",
                                          warning_label)
        warning_jvms = child_integer(warnings, "jvmsWithWarning", warning_label)
        warning_events = child_integer(warnings, "warningEvents", warning_label)
        findleaks_jvms = child_integer(row, "jvmsWithTargetContextInFindleaks",
                                      lifecycle_label)
        require(
            valid_lifecycle_jvms == 6
            and evaluable_intervals == 60
            and warning_evaluable == 60
            and warning_jvms <= valid_lifecycle_jvms
            and warning_jvms <= warning_intervals <= warning_jvms * 10
            and warning_events >= warning_intervals
            and (warning_events == 0) is (warning_intervals == 0)
            and findleaks_jvms <= valid_lifecycle_jvms,
            f"{lifecycle_label} has inconsistent lifecycle cardinalities",
        )
        put(f"V42_{token}_LIFECYCLE_JVMS", valid_lifecycle_jvms)
        put(f"V42_{token}_LIFECYCLE_INTERVALS", evaluable_intervals)
        put(f"V42_{token}_THREAD_WARNING_INTERVALS", warning_intervals)
        put(f"V42_{token}_THREAD_WARNING_JVMS", warning_jvms)
        put(f"V42_{token}_FINDLEAKS_JVMS", findleaks_jvms)
        for placeholder_suffix, source_key in (
            ("THREAD_FINAL_DELTA", "cycle5ThreadDeltaMedianRange"),
            ("THREAD_SLOPE", "threadSlopeMedianRange"),
            ("CLASSLOADER_SLOPE", "classloaderSlopeMedianRange"),
            ("HEAP_SLOPE", "heapSlopeMibMedianRange"),
            ("NMT_SLOPE", "nmtSlopeMibMedianRange"),
        ):
            put(f"V42_{token}_{placeholder_suffix}",
                child_text(formatted, source_key,
                           f"lifecycle.byProvider.{provider}.formatted"))

    jcs = child_object(values, "jcs248PositiveControl", "paper-values")
    jcs_index = index_rows(child_array(jcs, "byJcsLine",
                                       "paper-values.jcs248PositiveControl"),
                           ("provider",), "jcs248PositiveControl.byJcsLine")
    require_exact_keys(jcs_index, {(provider,) for provider in JCS_PROVIDERS},
                       "jcs248PositiveControl.byJcsLine")
    for provider in JCS_PROVIDERS:
        row = jcs_index[(provider,)]
        token = PROVIDER_TOKEN[provider]
        valid_jvms = child_integer(
            row, "validJvms", f"jcs248PositiveControl.byJcsLine.{provider}"
        )
        evaluable_intervals = child_integer(
            row,
            "evaluablePostUndeployIntervals",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        positive_jvms = child_integer(
            row, "positiveJvms", f"jcs248PositiveControl.byJcsLine.{provider}"
        )
        corroborated_intervals = child_integer(
            row,
            "corroboratedIntervals",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        jcs_warning_intervals = child_integer(
            row,
            "threadLeakWarningIntervals",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        jcs_warning_jvms = child_integer(
            row,
            "threadLeakWarningJvms",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        jcs_warning_events = child_integer(
            row,
            "threadLeakWarningEvents",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        jcs_findleaks_jvms = child_integer(
            row,
            "jvmsWithTargetContextInFindleaks",
            f"jcs248PositiveControl.byJcsLine.{provider}",
        )
        lifecycle_row_for_jcs = lifecycle_index[(provider,)]
        lifecycle_warnings_for_jcs = child_object(
            lifecycle_row_for_jcs,
            "tomcatThreadLeak",
            f"lifecycle.byProvider.{provider}",
        )
        require(
            valid_jvms == 6
            and evaluable_intervals == 60
            and positive_jvms <= valid_jvms
            and positive_jvms <= corroborated_intervals
            and corroborated_intervals <= positive_jvms * 10
            and positive_jvms <= jcs_warning_jvms <= valid_jvms
            and jcs_warning_jvms <= jcs_warning_intervals <= jcs_warning_jvms * 10
            and jcs_warning_intervals <= evaluable_intervals
            and jcs_warning_events >= jcs_warning_intervals
            and (jcs_warning_events == 0) is (jcs_warning_intervals == 0)
            and jcs_findleaks_jvms <= valid_jvms,
            f"JCS-248 cardinalities are inconsistent for {provider}",
        )
        require(
            corroborated_intervals <= jcs_warning_intervals
            and jcs_warning_intervals
            == child_integer(lifecycle_warnings_for_jcs, "intervalsWithWarning",
                             f"lifecycle.byProvider.{provider}.tomcatThreadLeak")
            and jcs_warning_jvms
            == child_integer(lifecycle_warnings_for_jcs, "jvmsWithWarning",
                             f"lifecycle.byProvider.{provider}.tomcatThreadLeak")
            and jcs_warning_events
            == child_integer(lifecycle_warnings_for_jcs, "warningEvents",
                             f"lifecycle.byProvider.{provider}.tomcatThreadLeak")
            and jcs_findleaks_jvms
            == child_integer(lifecycle_row_for_jcs,
                             "jvmsWithTargetContextInFindleaks",
                             f"lifecycle.byProvider.{provider}"),
            f"JCS-248 and lifecycle counts disagree for {provider}",
        )
        for placeholder_suffix, source_key in (
            ("VALID_JVMS", "validJvms"),
            ("INTERVALS", "evaluablePostUndeployIntervals"),
            ("CORROBORATED_INTERVALS", "corroboratedIntervals"),
            ("POSITIVE_JVMS", "positiveJvms"),
            ("WARNING_EVENTS", "threadLeakWarningEvents"),
        ):
            put(f"V42_{token}_JCS248_{placeholder_suffix}",
                child_integer(row, source_key,
                              f"jcs248PositiveControl.byJcsLine.{provider}"))
        slopes = child_object(row, "lifecycleSlopes",
                              f"jcs248PositiveControl.byJcsLine.{provider}")
        lifecycle_formatted = child_object(
            lifecycle_index[(provider,)], "formatted", f"lifecycle.byProvider.{provider}"
        )
        for placeholder_suffix, source_key, lifecycle_key in (
            ("THREAD_SLOPE", "threadPerCycle", "threadSlopeMedianRange"),
            ("CLASSLOADER_SLOPE", "classloaderPerCycle", "classloaderSlopeMedianRange"),
            ("HEAP_SLOPE", "heapMebibytesPerCycle", "heapSlopeMibMedianRange"),
            ("NMT_SLOPE", "nativeCommittedMebibytesPerCycle", "nmtSlopeMibMedianRange"),
        ):
            rendered = median_range_text(
                member(slopes, source_key,
                       f"jcs248PositiveControl.byJcsLine.{provider}.lifecycleSlopes")
            )
            expected_rendered = child_text(
                lifecycle_formatted, lifecycle_key,
                f"lifecycle.byProvider.{provider}.formatted"
            )
            require(rendered == expected_rendered,
                    f"JCS-248 and lifecycle formatting disagree for {provider}.{source_key}")
            put(f"V42_{token}_JCS248_{placeholder_suffix}", rendered)

    jcs321_row = jcs_index[("jcs321",)]
    jcs4_row = jcs_index[("jcs4",)]
    require(
        child_boolean(
            jcs321_row,
            "prespecifiedPositiveControlCriterionApplies",
            "jcs248PositiveControl.byJcsLine.jcs321",
        ),
        "the prespecified positive-control criterion must apply to JCS 3.2.1",
    )
    jcs321_positive = child_integer(
        jcs321_row, "positiveJvms", "jcs248PositiveControl.byJcsLine.jcs321"
    )
    jcs321_intervals = child_integer(
        jcs321_row,
        "corroboratedIntervals",
        "jcs248PositiveControl.byJcsLine.jcs321",
    )
    jcs321_criterion_met = child_boolean(
        jcs321_row,
        "prespecifiedPositiveControlCriterionMet",
        "jcs248PositiveControl.byJcsLine.jcs321",
    )
    require(jcs321_criterion_met is (jcs321_positive >= 5),
            "JCS 3.2.1 positive-control criterion is inconsistent with its count")
    require(
        child_boolean(
            jcs321_row,
            "sameThresholdMetObservationally",
            "jcs248PositiveControl.byJcsLine.jcs321",
        ) is jcs321_criterion_met,
        "JCS 3.2.1 observational threshold flag is inconsistent",
    )

    require(
        child_boolean(
            jcs4_row,
            "prespecifiedPositiveControlCriterionApplies",
            "jcs248PositiveControl.byJcsLine.jcs4",
        ) is False,
        "the JCS 3.2.1 positive-control criterion must not be applied to JCS 4",
    )
    require(
        member(
            jcs4_row,
            "prespecifiedPositiveControlCriterionMet",
            "jcs248PositiveControl.byJcsLine.jcs4",
        ) is None,
        "the JCS 4 positive-control criterion outcome must be null",
    )
    jcs4_positive = child_integer(
        jcs4_row, "positiveJvms", "jcs248PositiveControl.byJcsLine.jcs4"
    )
    jcs4_intervals = child_integer(
        jcs4_row,
        "corroboratedIntervals",
        "jcs248PositiveControl.byJcsLine.jcs4",
    )
    require(
        child_boolean(
            jcs4_row,
            "sameThresholdMetObservationally",
            "jcs248PositiveControl.byJcsLine.jcs4",
        ) is (jcs4_positive >= 5),
        "JCS 4 observational threshold flag is inconsistent with its count",
    )

    if not jcs321_criterion_met:
        jcs248_interpretation = (
            f"JCS 3.2.1 presenta il difetto in {jcs321_positive}/6 repliche e "
            f"{jcs321_intervals}/60 controlli con doppia conferma: la soglia "
            "di almeno 5/6 repliche, definita prima dell'esecuzione, non è stata raggiunta. Il "
            "caso osservato in JCS 3.2.1 non è stato quindi riprodotto con "
            "sufficiente consistenza in questa campagna; "
            f"il confronto con lo snapshot JCS 4 (difetto rilevato in "
            f"{jcs4_positive}/6 repliche, {jcs4_intervals}/60 controlli con doppia "
            "conferma) non consente di "
            "concludere se lo specifico leak dei worker sia stato eliminato."
        )
    elif jcs4_intervals == 0 and jcs4_positive == 0:
        interval_detail = ""
        jcs321_interval_rows = jcs321_row.get("intervals")
        jcs4_interval_rows = jcs4_row.get("intervals")
        if (isinstance(jcs321_interval_rows, list)
                and isinstance(jcs4_interval_rows, list)
                and len(jcs321_interval_rows) == 60
                and len(jcs4_interval_rows) == 60):
            jcs321_checkpoint_counts = [
                (
                    child_integer(item, "earlySignatureObservationCount",
                                  "jcs248.jcs321.intervals"),
                    child_integer(item, "finalSignatureObservationCount",
                                  "jcs248.jcs321.intervals"),
                )
                for item in jcs321_interval_rows
            ]
            jcs4_checkpoint_counts = [
                (
                    child_integer(item, "earlySignatureObservationCount",
                                  "jcs248.jcs4.intervals"),
                    child_integer(item, "finalSignatureObservationCount",
                                  "jcs248.jcs4.intervals"),
                )
                for item in jcs4_interval_rows
            ]
            if (all(early == final for early, final in jcs321_checkpoint_counts)
                    and min(early for early, _ in jcs321_checkpoint_counts) == 1
                    and max(early for early, _ in jcs321_checkpoint_counts) == 10
                    and all(early == 0 and final == 0
                            for early, final in jcs4_checkpoint_counts)):
                interval_detail = (
                    " In JCS 3.2.1 le firme persistono dal checkpoint precoce a "
                    "quello finale e aumentano da una a dieci lungo i dieci "
                    "undeploy di ciascuna JVM; nello snapshot JCS 4 non compare "
                    "alcuna firma nei 120 dump post-undeploy."
                )
        jcs248_interpretation = (
            f"Il leak dei worker è riprodotto in JCS 3.2.1 con "
            f"{jcs321_positive}/6 repliche e {jcs321_intervals}/60 controlli con "
            "doppia conferma. Nello snapshot JCS 4 il difetto non è rilevato in "
            "alcuna replica e nessun controllo presenta la doppia conferma."
            f"{interval_detail} Nel perimetro del protocollo v4.2, il leak "
            "rilevato analizzando JCS 3.2.1 e successivamente registrato come "
            "JCS-248 non è osservato nello snapshot JCS 4 che incorpora la "
            "correzione upstream. L'evidenza è coerente con la risoluzione dello "
            "specifico difetto nella revisione esaminata; non dimostra l'assenza "
            "di altre forme di ritenzione e, poiché il confronto non è "
            "un'ablazione, non attribuisce l'esito a un singolo commit."
        )
    else:
        jcs248_interpretation = (
            f"Il leak dei worker è riprodotto in JCS 3.2.1 con "
            f"{jcs321_positive}/6 repliche e {jcs321_intervals}/60 controlli con "
            "doppia conferma. Nello snapshot "
            f"JCS 4 il difetto è rilevato in {jcs4_positive}/6 repliche e in "
            f"{jcs4_intervals}/60 controlli con doppia conferma: il pattern resta osservabile nella linea "
            "esaminata. Il confronto non dimostra da solo un memory leak, non "
            "localizza la ritenzione e non stima l'effetto causale dei singoli "
            "commit upstream."
        )
    put("V42_JCS248_INTERPRETATION", jcs248_interpretation)

    completed_jvms = sum(child_integer(qc_index[(provider,)], "processesAcquired",
                                       f"qualityControl.byProvider.{provider}")
                         for provider in PROVIDERS)
    completed_windows = sum(
        child_integer(qc_index[(provider,)], "workloadWindowsAcquired",
                      f"qualityControl.byProvider.{provider}")
        for provider in PROVIDERS
    )
    valid_windows = sum(
        child_integer(qc_index[(provider,)], "semanticGateWindowsPassed",
                      f"qualityControl.byProvider.{provider}")
        for provider in PROVIDERS
    )
    timing = child_object(lifecycle, "timingEvidence", "paper-values.lifecycle")
    observed_intervals = child_integer(timing, "intervals",
                                       "paper-values.lifecycle.timingEvidence")
    require(observed_intervals % 2 == 0,
            "lifecycle timing interval count cannot represent two intervals per cycle")
    completed_cycles = observed_intervals // 2
    require(completed_cycles == child_integer(denominators, "cyclesTotal",
                                               "qualityControl.denominatorDefinition"),
            "observed lifecycle intervals do not cover every declared v4.2 cycle")
    require(completed_jvms == child_integer(denominators, "processesTotal",
                                             "qualityControl.denominatorDefinition"),
            "acquired process count differs from the accepted v4.2 denominator")
    require(completed_windows == child_integer(denominators, "workloadWindowsTotal",
                                                "qualityControl.denominatorDefinition"),
            "acquired workload-window count differs from the accepted v4.2 denominator")

    lifecycle_valid = sum(child_integer(lifecycle_index[(provider,)], "validLifecycleJvms",
                                        f"lifecycle.byProvider.{provider}")
                          for provider in PAPER_LIFECYCLE_PROVIDERS)
    lifecycle_intervals = sum(
        child_integer(lifecycle_index[(provider,)], "evaluableFindleaksIntervals",
                      f"lifecycle.byProvider.{provider}")
        for provider in PAPER_LIFECYCLE_PROVIDERS
    )
    lifecycle_warning_intervals = sum(
        child_integer(child_object(lifecycle_index[(provider,)], "tomcatThreadLeak",
                                   f"lifecycle.byProvider.{provider}"),
                      "intervalsWithWarning",
                      f"lifecycle.byProvider.{provider}.tomcatThreadLeak")
        for provider in PAPER_LIFECYCLE_PROVIDERS
    )
    lifecycle_warning_jvms = sum(
        child_integer(child_object(lifecycle_index[(provider,)], "tomcatThreadLeak",
                                   f"lifecycle.byProvider.{provider}"),
                      "jvmsWithWarning",
                      f"lifecycle.byProvider.{provider}.tomcatThreadLeak")
        for provider in PAPER_LIFECYCLE_PROVIDERS
    )
    lifecycle_findleaks_jvms = sum(
        child_integer(lifecycle_index[(provider,)], "jvmsWithTargetContextInFindleaks",
                      f"lifecycle.byProvider.{provider}")
        for provider in PAPER_LIFECYCLE_PROVIDERS
    )
    lifecycle_findleaks_interval_values = [
        lifecycle_index[(provider,)].get("targetFindleaksIntervals")
        for provider in PAPER_LIFECYCLE_PROVIDERS
    ]
    lifecycle_findleaks_interval_suffix = ""
    if all(isinstance(value, int) and not isinstance(value, bool)
           for value in lifecycle_findleaks_interval_values):
        lifecycle_findleaks_interval_suffix = (
            f" e {sum(lifecycle_findleaks_interval_values)}/300 intervalli"
        )
    lifecycle_numbers = (
        f"{lifecycle_valid}/30 JVM valide e "
        f"{lifecycle_intervals}/300 intervalli valutabili; warning thread-leak in "
        f"{lifecycle_warning_intervals}/300 intervalli ({lifecycle_warning_jvms}/30 JVM); "
        f"context path rilevato da `findleaks` in {lifecycle_findleaks_jvms}/30 JVM"
        f"{lifecycle_findleaks_interval_suffix}"
    )
    def jcs_count_summary(provider: str) -> str:
        row = jcs_index[(provider,)]
        return (
            f"{SUMMARY_NAME[provider]}: "
            f"difetto rilevato in {child_integer(row, 'positiveJvms', f'jcs248.{provider}')}/6 repliche e "
            f"{child_integer(row, 'corroboratedIntervals', f'jcs248.{provider}')}/60 "
            "controlli con doppia conferma"
        )

    jcs_summary = "; ".join(jcs_count_summary(provider) for provider in JCS_PROVIDERS)
    completion_summary = (
        f"{completed_jvms}/36 JVM, {completed_cycles}/180 cicli e "
        f"{completed_windows}/360 finestre completati; "
        f"{valid_windows}/360 gate semantici superati"
    )
    ratio_medians = [
        number_value(
            member(
                child_object(row, "ratio", "pairedThroughputRatios.primary"),
                "median",
                "pairedThroughputRatios.primary.ratio",
            ),
            "pairedThroughputRatios.primary.ratio.median",
        )
        for row in ratio_index.values()
    ]
    performance_summary = (
        "il throughput di Caffeine, Ehcache e cache2k risulta compreso fra "
        f"{italian_number(min(ratio_medians), 2)} e "
        f"{italian_number(max(ratio_medians), 2)} volte quello dello snapshot "
        "JCS 4, considerando le mediane dei confronti svolti nella stessa fase "
        "del test"
    )

    duration_minimum = min(
        float(observed_ranges_by_provider[provider]["durationMinimum"])
        for provider in PROVIDERS
    )
    duration_maximum = max(
        float(observed_ranges_by_provider[provider]["durationMaximum"])
        for provider in PROVIDERS
    )
    operations_minimum = min(
        int(observed_ranges_by_provider[provider]["operationsMinimum"])
        for provider in PROVIDERS
    )
    operations_maximum = max(
        int(observed_ranges_by_provider[provider]["operationsMaximum"])
        for provider in PROVIDERS
    )
    cache_providers = tuple(provider for provider in PROVIDERS if provider != "nostore")
    cache_hit_minimum = min(
        float(observed_ranges_by_provider[provider]["hitRateMinimum"])
        for provider in cache_providers
    )
    cache_hit_maximum = max(
        float(observed_ranges_by_provider[provider]["hitRateMaximum"])
        for provider in cache_providers
    )
    cache_after_workload_minimum = min(
        int(observed_ranges_by_provider[provider]["entriesAfterWorkloadMinimum"])
        for provider in cache_providers
    )
    cache_after_workload_maximum = max(
        int(observed_ranges_by_provider[provider]["entriesAfterWorkloadMaximum"])
        for provider in cache_providers
    )
    cache_after_write_minimum = min(
        int(observed_ranges_by_provider[provider]["entriesAfterWriteMinimum"])
        for provider in cache_providers
    )
    cache_after_write_maximum = max(
        int(observed_ranges_by_provider[provider]["entriesAfterWriteMaximum"])
        for provider in cache_providers
    )
    single_flight_applicable = sum(
        int(observed_ranges_by_provider[provider]["singleFlightApplicable"])
        for provider in cache_providers
    )
    single_flight_passed = sum(
        int(observed_ranges_by_provider[provider]["singleFlightPassed"])
        for provider in cache_providers
    )
    redeploy_ready_applicable = sum(
        int(observed_ranges_by_provider[provider]["redeployReadyApplicable"])
        for provider in PROVIDERS
    )
    redeploy_ready_passed = sum(
        int(observed_ranges_by_provider[provider]["redeployReadyPassed"])
        for provider in PROVIDERS
    )
    require(single_flight_applicable == 300,
            "RQ1 single-flight denominator must be 300 cache windows")
    require(redeploy_ready_applicable == 180,
            "RQ1 redeploy-readiness denominator must be 180 cycles")
    nostore_ranges = observed_ranges_by_provider["nostore"]
    rq1_answer = (
        f"Le {completed_windows}/360 finestre previste sono state acquisite e "
        f"{valid_windows}/360 hanno superato il gate semantico; il ritorno in "
        f"servizio dopo il redeploy è stato osservato in {redeploy_ready_passed}/"
        f"{redeploy_ready_applicable} cicli e la prova single-flight è riuscita "
        f"in {single_flight_passed}/{single_flight_applicable} finestre "
        "applicabili. Gli estremi di durata, operazioni, hit rate e popolamento "
        "sono riportati nelle tabelle 6.1 e 6.2."
    )

    def rq2_throughput(provider: str) -> str:
        cells = []
        for phase, phase_name in (("initial", "iniziale"),
                                  ("redeploy", "post-redeploy")):
            row = throughput_index[(provider, phase)]
            formatted = child_object(row, "formatted", "primaryPerformance.throughput")
            cells.append(
                f"{phase_name} "
                f"{child_text(formatted, 'medianMops', 'throughput.formatted')} "
                f"Mops/s (n={child_integer(row, 'includedForks', 'throughput')}/6)"
            )
        return f"{SUMMARY_NAME[provider]}: " + ", ".join(cells)

    def rq2_ratio(provider: str) -> str:
        cells = []
        for phase, phase_name in (("initial", "iniziale"),
                                  ("redeploy", "post-redeploy")):
            row = ratio_index[(provider, phase)]
            formatted = child_object(row, "formatted", "pairedThroughputRatios.primary")
            stats = child_object(row, "ratio", "pairedThroughputRatios.primary")
            cells.append(
                f"{phase_name} "
                f"{child_text(formatted, 'median', 'ratio.formatted')} "
                f"(n={child_integer(stats, 'n', 'ratio')}/6 coppie)"
            )
        return f"{SUMMARY_NAME[provider]}: " + ", ".join(cells)

    def rq2_p99(provider: str) -> str:
        values_by_phase = []
        for phase in PHASES:
            row = latency_index[(provider, phase)]
            formatted = child_object(
                row, "formatted", "primaryPerformance.sampledLatency"
            )
            values_by_phase.append(
                child_text(
                    formatted,
                    "p99MedianMicroseconds",
                    "primaryPerformance.sampledLatency.formatted",
                )
            )
        return f"{SUMMARY_NAME[provider]} {values_by_phase[0]}/{values_by_phase[1]} µs"

    rq2_answer = (
        "Nel workload configurato, la mediana dei rapporti appaiati dei tre "
        "provider alternativi rispetto allo snapshot JCS 4 varia da "
        f"{italian_number(min(ratio_medians), 2)}× a "
        f"{italian_number(max(ratio_medians), 2)}×. Le mediane del p99 "
        "campionato, nella forma iniziale/redeploy, sono: "
        + "; ".join(rq2_p99(provider) for provider in PRIMARY_PROVIDERS)
        + ". Le tabelle 6.3 e 6.4 riportano distribuzioni e denominatori; i "
        "valori descrivono il percorso adapter–provider, non la latenza HTTP."
    )

    rq3_rows = [lifecycle_index[(provider,)]
                for provider in PAPER_LIFECYCLE_PROVIDERS]
    rq3_valid_jvms = sum(
        child_integer(row, "validLifecycleJvms", "lifecycle.byProvider")
        for row in rq3_rows
    )
    rq3_evaluable_intervals = sum(
        child_integer(
            child_object(row, "tomcatThreadLeak", "lifecycle.byProvider"),
            "evaluableIntervals",
            "lifecycle.byProvider.tomcatThreadLeak",
        )
        for row in rq3_rows
    )
    rq3_warning_intervals = sum(
        child_integer(
            child_object(row, "tomcatThreadLeak", "lifecycle.byProvider"),
            "intervalsWithWarning",
            "lifecycle.byProvider.tomcatThreadLeak",
        )
        for row in rq3_rows
    )
    rq3_warning_jvms = sum(
        child_integer(
            child_object(row, "tomcatThreadLeak", "lifecycle.byProvider"),
            "jvmsWithWarning",
            "lifecycle.byProvider.tomcatThreadLeak",
        )
        for row in rq3_rows
    )
    rq3_findleaks_jvms = sum(
        child_integer(row, "jvmsWithTargetContextInFindleaks",
                      "lifecycle.byProvider")
        for row in rq3_rows
    )
    rq3_findleaks_interval_values = [
        row.get("targetFindleaksIntervals") for row in rq3_rows
    ]
    rq3_findleaks_intervals = (
        sum(rq3_findleaks_interval_values)
        if all(isinstance(value, int) and not isinstance(value, bool)
               for value in rq3_findleaks_interval_values)
        else None
    )
    nostore_row = lifecycle_index[("nostore",)]
    nostore_findleaks_jvms = child_integer(
        nostore_row,
        "jvmsWithTargetContextInFindleaks",
        "lifecycle.byProvider.nostore",
    )
    if rq3_findleaks_jvms == rq3_valid_jvms and nostore_findleaks_jvms == 6:
        interval_detail = (
            f" e in {rq3_findleaks_intervals}/{rq3_evaluable_intervals} intervalli"
            if rq3_findleaks_intervals is not None else ""
        )
        findleaks_sentence = (
            f"`findleaks` ha restituito il context path in tutte le "
            f"{rq3_findleaks_jvms}/{rq3_valid_jvms} JVM, comprese le 6/6 "
            f"JVM `no-store`{interval_detail}: in questa campagna il segnale non distingue quindi "
            "un motore di cache dall'infrastruttura comune"
        )
    else:
        findleaks_sentence = (
            f"`findleaks` ha restituito il context path in "
            f"{rq3_findleaks_jvms}/{rq3_valid_jvms} JVM, incluse "
            f"{nostore_findleaks_jvms}/6 JVM `no-store`; questo solo conteggio "
            "non attribuisce il segnale a un provider"
        )

    ehcache_warnings = child_object(
        lifecycle_index[("ehcache",)],
        "tomcatThreadLeak",
        "lifecycle.byProvider.ehcache",
    )
    ehcache_warning_intervals = child_integer(
        ehcache_warnings,
        "intervalsWithWarning",
        "lifecycle.byProvider.ehcache.tomcatThreadLeak",
    )
    ehcache_warning_jvms = child_integer(
        ehcache_warnings,
        "jvmsWithWarning",
        "lifecycle.byProvider.ehcache.tomcatThreadLeak",
    )
    if (rq3_warning_intervals == 1 and rq3_warning_jvms == 1
            and ehcache_warning_intervals == 1 and ehcache_warning_jvms == 1):
        warning_sentence = (
            "un solo intervallo su 300 contiene un warning thread-leak; "
            "riguarda `Catalina-utility-2`, un thread Tomcat già presente nei "
            "baseline di processo e di ciclo. Lo stack è nel background processor "
            "di Tomcat, non in codice Ehcache; l'evento non ricorre negli altri "
            "59 intervalli Ehcache e resta non attribuito"
        )
    else:
        warning_sentence = (
            f"i warning thread-leak compaiono in {rq3_warning_intervals}/"
            f"{rq3_evaluable_intervals} intervalli e in "
            f"{rq3_warning_jvms}/{rq3_valid_jvms} JVM"
        )

    caffeine_formatted = child_object(
        lifecycle_index[("caffeine",)],
        "formatted",
        "lifecycle.byProvider.caffeine",
    )
    caffeine_delta = child_text(
        caffeine_formatted,
        "cycle5ThreadDeltaMedianRange",
        "lifecycle.byProvider.caffeine.formatted",
    )
    caffeine_slope = child_text(
        caffeine_formatted,
        "threadSlopeMedianRange",
        "lifecycle.byProvider.caffeine.formatted",
    )
    thread_slopes = [
        child_text(
            child_object(row, "formatted", "lifecycle.byProvider"),
            "threadSlopeMedianRange",
            "lifecycle.byProvider.formatted",
        )
        for row in rq3_rows
    ]
    if all(value == "+0 [+0–+0]" for value in thread_slopes):
        thread_slope_sentence = (
            "La pendenza mediana dei thread è zero in tutte e cinque le condizioni"
        )
    else:
        thread_slope_sentence = (
            "Le pendenze dei thread per condizione sono riportate nella sezione 6.6"
        )

    rq3_answer = (
        f"Sono valutabili {rq3_evaluable_intervals}/300 intervalli nelle cinque "
        f"condizioni della tabella. {findleaks_sentence}; {warning_sentence}.\n\n"
        "Per Caffeine, il delta dei thread vivi al quinto ciclo rispetto al "
        f"baseline è {caffeine_delta}, mentre la pendenza per ciclo è "
        f"{caffeine_slope}: l'offset è stabile e non descrive una crescita "
        f"progressiva. {thread_slope_sentence}.\n\n"
        "Gli intervalli min–max delle pendenze di heap e NMT dei provider "
        "primari si sovrappongono a quelli di `no-store`; heap, NMT e righe "
        "`ParallelWebappClassLoader` sono grandezze process-wide. Questi segnali "
        "non dimostrano da soli un leak e non ne attribuiscono la causa a un "
        "provider. Il confronto fra JCS 3.2.1 e lo snapshot JCS 4 è sviluppato "
        "separatamente nella sezione 7."
    )

    put("V42_CONCLUSION_COMPLETION_AND_GATES", completion_summary)
    put("V42_CONCLUSION_PERFORMANCE_MEDIANS", performance_summary)
    put("V42_CONCLUSION_LIFECYCLE_COUNTS", lifecycle_numbers)
    put("V42_CONCLUSION_JCS248_COUNTS", jcs_summary)
    put("V42_RQ1_ANSWER", rq1_answer)
    put("V42_RQ2_ANSWER", rq2_answer)
    put("V42_RQ3_ANSWER", rq3_answer)

    require(len(replacements) == EXPECTED_PLACEHOLDER_COUNT,
            f"internal mapping has {len(replacements)} entries; expected {EXPECTED_PLACEHOLDER_COUNT}")
    return replacements


def fill_template(template: str, replacements: Mapping[str, str]) -> str:
    placeholders = set(PLACEHOLDER_RE.findall(template))
    require(len(placeholders) == EXPECTED_PLACEHOLDER_COUNT,
            f"paper contains {len(placeholders)} distinct v4.2 placeholders; "
            f"expected {EXPECTED_PLACEHOLDER_COUNT}")
    missing = sorted(placeholders - set(replacements))
    unused = sorted(set(replacements) - placeholders)
    require(not missing, f"paper placeholders have no source mapping: {missing!r}")
    require(not unused, f"mapping contains placeholders absent from paper: {unused!r}")

    def replace(match: re.Match[str]) -> str:
        return text_value(replacements[match.group(1)],
                          f"replacement {match.group(1)}")

    filled = PLACEHOLDER_RE.sub(replace, template)
    remaining = PLACEHOLDER_RE.findall(filled)
    require(not remaining, f"unfilled v4.2 placeholders remain: {sorted(set(remaining))!r}")
    require("{{V41_" not in filled and "{{V4_1" not in filled,
            "a v4.1 placeholder remains in the generated paper")
    return filled


def load_json_object(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise FillError(f"non-finite JSON constant {value!r} in {path}")

    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"),
                            parse_constant=reject_constant)
    except FillError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as failure:
        raise FillError(f"cannot read paper-values JSON {path}: {failure}") from failure
    return object_value(loaded, "paper-values")


def write_atomic(destination: Path, content: str, force: bool) -> None:
    require(not destination.exists() or force,
            f"output already exists (pass --force to replace it): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    require(not temporary.exists(), f"temporary output already exists: {temporary}")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, destination)
    except OSError as failure:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise FillError(f"cannot write filled paper {destination}: {failure}") from failure


def main(argv: list[str] | None = None) -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Fill all v4.2 paper placeholders from definitive paper-values JSON."
    )
    parser.add_argument("--values", required=True, type=Path,
                        help="definitive ...-paper-values.json produced by extract_paper_v4_2.py")
    parser.add_argument(
        "--paper", type=Path,
        default=repository / "press" / "article" / "beyond-throughput-tomcat-lifecycle.md",
        help="paper template (defaults to the repository article)",
    )
    parser.add_argument("--output", required=True, type=Path,
                        help="new Markdown file to create; must differ from --paper")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing output file")
    arguments = parser.parse_args(argv)

    try:
        values_path = arguments.values.resolve()
        paper_path = arguments.paper.resolve()
        output_path = arguments.output.resolve()
        require(values_path != paper_path, "paper-values and paper paths must differ")
        require(output_path != paper_path,
                "refusing to overwrite the placeholder template; choose a distinct --output")
        require(output_path != values_path, "output and paper-values paths must differ")
        values = load_json_object(values_path)
        campaign_id = validate_metadata(values)
        require(values_path.name == f"{campaign_id}-paper-values.json",
                "paper-values filename must exactly match its v4.2 campaignId")
        try:
            template = paper_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as failure:
            raise FillError(f"cannot read paper template {paper_path}: {failure}") from failure
        replacements = build_replacements(values)
        filled = fill_template(template, replacements)
        write_atomic(output_path, filled, arguments.force)
    except FillError as failure:
        print(f"fill_paper_v4_2: {failure}", file=sys.stderr)
        return 2

    print(f"Filled {len(replacements)} v4.2 placeholders: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

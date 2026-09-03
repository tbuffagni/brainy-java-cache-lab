#!/usr/bin/env python3
"""Validate a finalized protocol-v4.2 cache benchmark campaign without changing it."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore")
PRIMARY_PERFORMANCE_PROVIDERS = {"caffeine", "ehcache", "cache2k", "jcs4"}
PROTOCOL_VERSION = "4.2"
CAMPAIGN_PREFIX = "article1-unified-v4-2"
PROTOCOL_PATH = "press/article/protocollo-campagna-v4-2.md"
EXPECTED_PROTOCOL_SHA256 = (
    "4f364de62f696c687d3175931f29c69013f4ad9d96303558e2444bfc5c73596f"
)
ANALYSIS_PERFORMANCE_FIELDS = (
    "operationsPerSecond",
    "readOperationsPerSecond",
    "fillOperationsPerSecond",
    "latencyP50Nanos",
    "latencyP95Nanos",
    "latencyP99Nanos",
    "measuredLatencySamples",
)
WILLIAMS_ROWS = (
    ("caffeine", "ehcache", "nostore", "cache2k", "jcs321", "jcs4"),
    ("ehcache", "cache2k", "caffeine", "jcs4", "nostore", "jcs321"),
    ("cache2k", "jcs4", "ehcache", "jcs321", "caffeine", "nostore"),
    ("jcs4", "jcs321", "cache2k", "nostore", "ehcache", "caffeine"),
    ("jcs321", "nostore", "jcs4", "caffeine", "cache2k", "ehcache"),
    ("nostore", "caffeine", "jcs321", "ehcache", "jcs4", "cache2k"),
)
HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
HEX40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


@dataclass
class ValidationReport:
    checks: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def require(self, condition: bool, code: str, message: str) -> bool:
        self.checks += 1
        if not condition:
            self.errors.append(f"[{code}] {message}")
        return condition

    def warn(self, condition: bool, code: str, message: str) -> bool:
        self.checks += 1
        if not condition:
            self.warnings.append(f"[{code}] {message}")
        return condition

    @property
    def passed(self) -> bool:
        return not self.errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_container_kernel(value: Any) -> tuple[str, ...] | None:
    """Normalize only the per-container hostname (field 2 of ``uname -a``)."""
    if not isinstance(value, str):
        return None
    fields = value.split()
    if len(fields) < 3:
        return None
    return (fields[0], "<container-hostname>", *fields[2:])


def finite_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def validate_post_undeploy_timing(
    timing: Any,
    expected_early_target: float,
    expected_final_target: float,
    report: ValidationReport,
    label: str,
) -> None:
    if not report.require(isinstance(timing, dict), "post-undeploy-timing",
                          f"{label}: timing evidence must be an object"):
        return
    fields = (
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
    values = {field: timing.get(field) for field in fields}
    well_formed = all(finite_nonnegative_number(value) for value in values.values())
    if not report.require(
        well_formed,
        "post-undeploy-timing-fields",
        f"{label}: monotonic elapsed timing fields are missing or malformed",
    ):
        return

    early_legacy = float(values["earlyThreadSecondsAfterUndeploy"])
    final_legacy = float(values["finalMeasurementSecondsAfterUndeploy"])
    early_target = float(values["earlyThreadTargetSecondsAfterUndeploy"])
    final_target = float(values["finalDiagnosticTargetSecondsAfterUndeploy"])
    early_started = float(values["earlyThreadStartedSecondsAfterUndeploy"])
    early_completed = float(values["earlyThreadCompletedSecondsAfterUndeploy"])
    final_started = float(values["finalDiagnosticStartedSecondsAfterUndeploy"])
    findleaks_completed = float(values["findLeaksCompletedSecondsAfterUndeploy"])
    final_completed = float(values["finalSnapshotCompletedSecondsAfterUndeploy"])

    report.require(
        math.isclose(early_legacy, expected_early_target)
        and math.isclose(early_target, expected_early_target),
        "early-diagnostic-target-coherence",
        f"{label}: early target differs from lifecycleProtocol",
    )
    report.require(
        math.isclose(final_legacy, expected_final_target)
        and math.isclose(final_target, expected_final_target),
        "final-diagnostic-target-coherence",
        f"{label}: final target differs from lifecycleProtocol",
    )
    report.require(
        early_started >= early_target,
        "early-diagnostic-start",
        f"{label}: early thread collection started before its target",
    )
    report.require(
        early_completed >= early_started,
        "early-diagnostic-completion",
        f"{label}: early thread collection completed before it started",
    )
    report.require(
        final_started >= final_target and final_started >= early_completed,
        "final-diagnostic-start",
        f"{label}: final diagnostics started before their target or early completion",
    )
    report.require(
        findleaks_completed >= final_started,
        "findleaks-completion",
        f"{label}: findleaks completion precedes final diagnostic start",
    )
    report.require(
        final_completed >= findleaks_completed,
        "final-snapshot-completion",
        f"{label}: final snapshot completion precedes findleaks completion",
    )


def sha256_zip_member(archive: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with archive.open(member) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paired_request_seed(base_seed: int, schedule_seed: int, block: int, cycle: int) -> int:
    material = (
        f"cache-benchmark-v4:base:{base_seed}:campaign:{schedule_seed}:"
        f"block:{block}:cycle:{cycle}"
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big") & 0x7fffffff


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


def descriptive(values: list[float], prefix: str) -> dict[str, Any]:
    if not values:
        return {
            f"{prefix}N": 0,
            f"{prefix}Median": None,
            f"{prefix}Mean": None,
            f"{prefix}SampleStandardDeviation": None,
            f"{prefix}FirstQuartile": None,
            f"{prefix}ThirdQuartile": None,
            f"{prefix}Minimum": None,
            f"{prefix}Maximum": None,
        }
    return {
        f"{prefix}N": len(values),
        f"{prefix}Median": statistics.median(values),
        f"{prefix}Mean": statistics.mean(values),
        f"{prefix}SampleStandardDeviation": (
            statistics.stdev(values) if len(values) > 1 else None
        ),
        f"{prefix}FirstQuartile": interpolated_quantile(values, 0.25),
        f"{prefix}ThirdQuartile": interpolated_quantile(values, 0.75),
        f"{prefix}Minimum": min(values),
        f"{prefix}Maximum": max(values),
    }


def analysis_scalar_equal(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if (isinstance(actual, (int, float))
            and isinstance(expected, (int, float))):
        return math.isclose(float(actual), float(expected),
                            rel_tol=1e-12, abs_tol=1e-9)
    return actual == expected


def load_json(path: Path, report: ValidationReport, code: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as failure:
        report.require(False, code, f"cannot read {path}: {failure}")
        return None
    if not report.require(isinstance(value, dict), code, f"{path} must contain a JSON object"):
        return None
    return value


def sibling_file(directory: Path, filename: object, report: ValidationReport,
                 code: str) -> Path | None:
    if not isinstance(filename, str) or not filename:
        report.require(False, code, "missing artifact filename")
        return None
    candidate = (directory / filename).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        report.require(False, code, f"artifact escapes campaign directory: {filename}")
        return None
    return candidate


def validate_shape(raw: dict[str, Any], report: ValidationReport) -> None:
    report.require(raw.get("schemaVersion") == 4, "schema", "raw schemaVersion must be 4")
    report.require(raw.get("protocolVersion") == PROTOCOL_VERSION,
                   "protocol-version",
                   f"raw protocolVersion must be {PROTOCOL_VERSION}")
    report.require(raw.get("providers") == list(PROVIDERS), "providers",
                   f"providers must be {list(PROVIDERS)} in canonical order")
    report.require(raw.get("forks") == 6, "fork-count", "campaign must declare six forks")
    report.require(raw.get("cyclesPerProcessRun") == 5, "cycle-count",
                   "campaign must declare five cycles per process run")
    matrix = raw.get("matrix", {})
    report.require(all(len(matrix.get(key, [])) == 1 for key in
                       ("threads", "hitPercent", "workloads", "jcsMemoryModes")),
                   "single-scenario", "final campaign must contain one request scenario")
    runs = raw.get("processRuns", [])
    report.require(isinstance(runs, list) and len(runs) == 36, "run-count",
                   "campaign must contain exactly 36 process runs")
    report.require(raw.get("infrastructureFailures") == [], "infrastructure-failures",
                   "campaign contains infrastructure failures")
    report.require(raw.get("invalidBlocks", []) == [], "raw-invalid-blocks",
                   "raw campaign contains invalid Williams blocks")
    report.require(bool(raw.get("campaignStartedAt")) and bool(raw.get("campaignFinishedAt")),
                   "campaign-timestamps", "campaign start/finish timestamps are required")
    protocol = raw.get("lifecycleProtocol", {})
    report.require(protocol.get("freshContainerPerProcessRun") is True,
                   "fresh-container-protocol", "fresh-container protocol is not declared")
    report.require(protocol.get("earlyThreadObservationSeconds") == 2.0,
                   "early-diagnostic-time", "early thread observation must be at 2 seconds")
    report.require(protocol.get("finalObservationAndFindleaksSeconds") == 10.0,
                   "final-diagnostic-time", "final observation/findleaks must be at 10 seconds")
    report.require(protocol.get("findleaksOccurrencesPreserved") is True,
                   "findleaks-occurrences", "findleaks occurrences must be preserved")


def validate_schedule(raw: dict[str, Any], report: ValidationReport) -> None:
    schedule = raw.get("schedule", {})
    report.require(schedule.get("design") == "frozen canonical Williams 6x6",
                   "williams-design", "campaign is not marked as frozen Williams 6x6")
    report.require(schedule.get("rowsAreShuffled") is False, "williams-shuffle",
                   "Williams rows must not be shuffled")
    report.require(schedule.get("canonicalRows") == [list(row) for row in WILLIAMS_ROWS],
                   "williams-rows", "canonical Williams rows differ from the frozen protocol")
    report.require(schedule.get("selectedProviders") == list(PROVIDERS),
                   "williams-selected-providers", "selected provider list is not canonical")
    rows = schedule.get("forkRows", [])
    report.require(len(rows) == 6, "williams-fork-rows", "six Williams fork rows are required")
    for index, expected in enumerate(WILLIAMS_ROWS, 1):
        row = rows[index - 1] if len(rows) >= index else {}
        report.require(row.get("fork") == index and row.get("block") == index,
                       "williams-row-id", f"row {index} must map to fork/block {index}")
        report.require(row.get("williamsRow") == index,
                       "williams-row-number", f"row {index} number is inconsistent")
        report.require(row.get("order") == list(expected), "williams-row-order",
                       f"block {index} provider order does not match the frozen row")
    plan = raw.get("executionPlan", [])
    report.require(len(plan) == 36, "execution-plan-count",
                   "execution plan must contain exactly 36 runs")
    seen_ids: set[str] = set()
    for block, expected_row in enumerate(WILLIAMS_ROWS, 1):
        planned = sorted((item for item in plan if item.get("block") == block),
                         key=lambda item: item.get("orderPosition", -1))
        report.require([item.get("provider") for item in planned] == list(expected_row),
                       "execution-plan-order", f"execution plan for block {block} is not frozen")
        for position, item in enumerate(planned, 1):
            run_id = item.get("processRunId")
            report.require(item.get("fork") == block and item.get("williamsRow") == block,
                           "execution-plan-row", f"plan entry {run_id} has inconsistent row IDs")
            report.require(item.get("orderPosition") == position,
                           "execution-plan-position", f"plan entry {run_id} has wrong position")
            report.require(isinstance(run_id, str) and run_id not in seen_ids,
                           "execution-plan-id", f"duplicate or missing processRunId {run_id!r}")
            if isinstance(run_id, str):
                seen_ids.add(run_id)


def validate_source_provenance(raw: dict[str, Any], report: ValidationReport) -> None:
    source = raw.get("sourceProvenance", {})
    files = source.get("files", [])
    report.require(isinstance(files, list) and bool(files), "source-files",
                   "source provenance file manifest is missing")
    well_formed = all(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sizeBytes"), int)
        and item.get("sizeBytes", -1) >= 0
        and isinstance(item.get("sha256"), str)
        and bool(HEX64.fullmatch(item["sha256"]))
        for item in files
    )
    report.require(well_formed, "source-file-manifest", "source file manifest is malformed")
    if well_formed:
        calculated = hashlib.sha256(
            "\n".join(f"{item['sha256']}  {item['path']}" for item in files).encode("utf-8")
        ).hexdigest()
        report.require(source.get("manifestSha256") == calculated, "source-manifest-sha",
                       "source provenance aggregate SHA-256 is inconsistent")
        protocol_rows = [item for item in files if item["path"] == PROTOCOL_PATH]
        report.require(
            len(protocol_rows) == 1
            and protocol_rows[0]["sha256"].lower() == EXPECTED_PROTOCOL_SHA256,
            "protocol-sha",
            "source provenance does not identify the frozen v4.2 protocol checksum",
        )


def validate_environment(raw: dict[str, Any], runs: list[dict[str, Any]],
                         report: ValidationReport) -> None:
    preflight = raw.get("campaignPreflight", {})
    report.require(preflight.get("provenanceValidationPassed") is True,
                   "preflight-provenance", "campaign preflight provenance did not pass")
    report.require(preflight.get("nativeMemoryTrackingSummaryAvailable") is True,
                   "preflight-nmt", "Native Memory Tracking preflight is missing")
    expected_cpu = preflight.get("containerCpuLimit")
    expected_memory = preflight.get("containerMemoryLimitBytes")
    report.require(isinstance(expected_cpu, (int, float)) and expected_cpu > 0,
                   "cpu-limit", "preflight CPU limit must be positive")
    report.require(isinstance(expected_memory, int) and expected_memory > 0,
                   "memory-limit", "preflight memory limit must be positive")
    common_fields = ("dockerImageId", "containerImageName", "containerOS", "javaOptions",
                     "JVM Version", "JVM Vendor", "OS Name", "OS Version", "OS Architecture",
                     "containerCpuModel", "containerVisibleProcessors", "containerKernel",
                     "dockerServerVersion",
                     "dockerServerOperatingSystem", "dockerServerKernelVersion",
                     "dockerServerArchitecture", "dockerServerName")
    for field_name in common_fields:
        report.require(bool(preflight.get(field_name)), "preflight-environment",
                       f"preflight is missing environment field {field_name}")
    expected_image_digests: dict[str, str | None] = {}
    for image_field in ("runtimeBaseImage", "buildBaseImage"):
        image_metadata = preflight.get(image_field, {})
        pinned_digest = image_metadata.get("pinnedDigest") if isinstance(image_metadata, dict) else None
        reference = image_metadata.get("reference") if isinstance(image_metadata, dict) else None
        valid_digest = (
            isinstance(pinned_digest, str)
            and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", pinned_digest, re.IGNORECASE))
        )
        report.require(valid_digest, "preflight-base-image-digest",
                       f"preflight {image_field} lacks an immutable digest")
        report.require(
            valid_digest and isinstance(reference, str)
            and reference.lower().endswith("@" + pinned_digest.lower()),
            "preflight-base-image-reference",
            f"preflight {image_field} reference does not contain its pinned digest",
        )
        report.require(image_metadata.get("inspectionAvailable") is True,
                       "preflight-base-image-inspection",
                       f"preflight {image_field} could not be inspected")
        expected_image_digests[image_field] = pinned_digest if valid_digest else None
    container_ids: list[str] = []
    for run in runs:
        run_id = run.get("processRunId")
        environment = run.get("environment", {})
        container_id = environment.get("containerId")
        container_ids.append(container_id)
        report.require(isinstance(container_id, str) and bool(HEX64.fullmatch(container_id)),
                       "container-id", f"{run_id}: invalid full container ID")
        report.require(environment.get("provenanceValidationPassed") is True,
                       "run-provenance", f"{run_id}: provenance validation did not pass")
        report.require(environment.get("provenanceValidationErrors") == [],
                       "run-provenance-errors", f"{run_id}: provenance errors are present")
        report.require(environment.get("containerCpuLimit") == expected_cpu,
                       "cpu-coherence", f"{run_id}: CPU limit differs from preflight")
        report.require(environment.get("containerMemoryLimitBytes") == expected_memory,
                       "memory-coherence", f"{run_id}: memory limit differs from preflight")
        for field_name in common_fields:
            report.require(bool(environment.get(field_name)), "jvm-provenance",
                           f"{run_id}: missing environment field {field_name}")
            if preflight.get(field_name) is not None:
                if field_name == "containerKernel":
                    report.require(
                        normalized_container_kernel(environment.get(field_name))
                        == normalized_container_kernel(preflight.get(field_name)),
                        "container-kernel-coherence",
                        f"{run_id}: containerKernel differs from preflight after "
                        "normalizing only the per-container hostname",
                    )
                else:
                    report.require(
                        environment.get(field_name) == preflight.get(field_name),
                        "environment-coherence",
                        f"{run_id}: {field_name} differs from preflight",
                    )
        report.require(bool(environment.get("jvmCommandLine")), "jvm-command-line",
                       f"{run_id}: JVM command line is missing")
        report.require(bool(environment.get("jvmFlags")), "jvm-flags",
                       f"{run_id}: JVM flags are missing")
        report.require(environment.get("containerVisibleProcessors", 0) > 0,
                       "visible-processors",
                       f"{run_id}: visible processor count must be positive")
        for image_field in ("runtimeBaseImage", "buildBaseImage"):
            image_metadata = environment.get(image_field, {})
            pinned_digest = image_metadata.get("pinnedDigest") if isinstance(image_metadata, dict) else None
            reference = image_metadata.get("reference") if isinstance(image_metadata, dict) else None
            report.require(
                isinstance(pinned_digest, str)
                and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", pinned_digest, re.IGNORECASE)),
                "base-image-digest",
                f"{run_id}: {image_field} lacks an immutable digest",
            )
            report.require(
                isinstance(reference, str) and isinstance(pinned_digest, str)
                and reference.lower().endswith("@" + pinned_digest.lower()),
                "base-image-reference",
                f"{run_id}: {image_field} reference does not match pinnedDigest",
            )
            report.require(
                image_metadata.get("inspectionAvailable") is True,
                "base-image-inspection",
                f"{run_id}: {image_field} could not be inspected",
            )
            report.require(
                pinned_digest == expected_image_digests.get(image_field),
                "base-image-digest-coherence",
                f"{run_id}: {image_field} digest differs from preflight",
            )
        jcs4_commit = environment.get("jcs4SourceCommit")
        report.require(isinstance(jcs4_commit, str) and bool(HEX40.fullmatch(jcs4_commit)),
                       "jcs4-commit", f"{run_id}: JCS 4 commit is not exact")
        report.require(environment.get("imageJcs4RevisionLabel") == jcs4_commit,
                       "jcs4-image-label", f"{run_id}: JCS 4 image label mismatch")
        for checksum_field in ("warSha256", "jcs4ArtifactSha256", "jcs321ArtifactSha256"):
            checksum = environment.get(checksum_field)
            report.require(isinstance(checksum, str) and bool(HEX64.fullmatch(checksum)),
                           "artifact-sha", f"{run_id}: invalid {checksum_field}")
        artifact_manifest = environment.get("artifactManifest", [])
        paths = {item.get("containerPath") for item in artifact_manifest
                 if isinstance(item, dict)}
        report.require(any(str(path).endswith(".war") for path in paths),
                       "artifact-manifest-war", f"{run_id}: WAR absent from artifact manifest")
        report.require(sum(str(path).endswith(".jar") for path in paths) >= 2,
                       "artifact-manifest-jars", f"{run_id}: both JCS artifacts are required")
    report.require(len(set(container_ids)) == 36, "container-identity",
                   "all 36 process runs must have distinct container IDs")


def validate_runs(raw: dict[str, Any], report: ValidationReport) -> dict[tuple[int, int], dict[str, set[Any]]]:
    runs = raw.get("processRuns", [])
    plan_by_id = {item.get("processRunId"): item for item in raw.get("executionPlan", [])}
    grouped: dict[tuple[int, int], dict[str, set[Any]]] = defaultdict(
        lambda: {"providers": set(), "seeds": set(), "accessPlans": set()}
    )
    run_ids: set[str] = set()
    for run in runs:
        run_id = run.get("processRunId")
        provider = run.get("provider")
        block = run.get("block")
        run_ids.add(run_id)
        planned = plan_by_id.get(run_id, {})
        report.require(provider in PROVIDERS, "run-provider", f"{run_id}: unknown provider")
        report.require(run.get("fork") == block and block in range(1, 7),
                       "run-block", f"{run_id}: fork/block must be 1..6 and identical")
        report.require(provider == planned.get("provider")
                       and run.get("orderPosition") == planned.get("orderPosition"),
                       "run-plan-coherence", f"{run_id}: completed run differs from plan")
        cycles = run.get("cycles", [])
        report.require(len(cycles) == 5, "run-cycle-count", f"{run_id}: expected five cycles")
        report.require([cycle.get("cycle") for cycle in cycles] == [1, 2, 3, 4, 5],
                       "cycle-sequence", f"{run_id}: cycle sequence must be 1..5")
        for cycle in cycles:
            cycle_number = cycle.get("cycle")
            request = cycle.get("request", {})
            seed = cycle.get("requestSeed")
            expected_seed = paired_request_seed(
                int(raw.get("configuration", {}).get("seed", 0)),
                int(raw.get("schedule", {}).get("scheduleSeed", 0)),
                int(block), int(cycle_number),
            )
            plan_seed = planned.get("pairedRequestSeedsByCycle", {}).get(str(cycle_number))
            report.require(seed == expected_seed == plan_seed == request.get("seed"),
                           "paired-seed", f"{run_id} C{cycle_number}: request seed mismatch")
            grouped[(block, cycle_number)]["providers"].add(provider)
            grouped[(block, cycle_number)]["seeds"].add(seed)
            for phase, workload_key, validation_key in (
                ("initial", "workload", "protocolValidation"),
                ("redeploy", "redeployWorkload", "redeployProtocolValidation"),
            ):
                workload = cycle.get(workload_key, {})
                validation = cycle.get(validation_key, {})
                label = f"{run_id} C{cycle_number} {phase}"
                access_plan = workload.get("accessPlanSha256")
                grouped[(block, cycle_number)]["accessPlans"].add(access_plan)
                report.require(isinstance(access_plan, str) and bool(HEX64.fullmatch(access_plan)),
                               "access-plan-sha", f"{label}: invalid accessPlanSha256")
                report.require(workload.get("provider") == provider, "workload-provider",
                               f"{label}: response provider mismatch")
                measurement_nanos = workload.get("measurementNanos", 0)
                warmup_nanos = workload.get("warmupNanos", 0)
                minimum_measurement = int(
                    float(request.get("measurementSeconds", 0)) * 1e9
                )
                minimum_warmup = float(request.get("warmupSeconds", 0)) * 1e9
                measurement_well_formed = (
                    isinstance(measurement_nanos, int)
                    and not isinstance(measurement_nanos, bool)
                    and measurement_nanos >= 0
                )
                report.require(measurement_well_formed, "measurement-duration-value",
                               f"{label}: measurementNanos is malformed")
                duration_passed = (
                    measurement_well_formed
                    and (minimum_measurement == 0
                         or measurement_nanos >= minimum_measurement)
                )
                report.require(isinstance(warmup_nanos, int) and warmup_nanos >= minimum_warmup,
                               "warmup-duration", f"{label}: warmup window is too short")
                measured_operations = workload.get("measuredOperations", 0)
                operations_per_second = workload.get("operationsPerSecond", 0)
                requested_operations = request.get("operations")
                measured_well_formed = (
                    isinstance(measured_operations, int)
                    and not isinstance(measured_operations, bool)
                    and measured_operations >= 0
                )
                requested_well_formed = (
                    isinstance(requested_operations, int)
                    and not isinstance(requested_operations, bool)
                    and requested_operations > 0
                )
                rate_well_formed = (
                    isinstance(operations_per_second, (int, float))
                    and not isinstance(operations_per_second, bool)
                    and math.isfinite(float(operations_per_second))
                    and operations_per_second >= 0
                )
                report.require(measured_well_formed and rate_well_formed,
                               "throughput-shape",
                               f"{label}: measured operations/rate are malformed")
                report.require(requested_well_formed, "requested-operations",
                               f"{label}: requested operation count is malformed")
                operation_measurements_valid = (
                    requested_well_formed and measured_well_formed
                    and rate_well_formed and operations_per_second > 0
                )
                completed_operations = (
                    operation_measurements_valid
                    and measured_operations >= requested_operations
                )
                report.require(workload.get("warmupOperationsExecuted", 0) > 0,
                               "positive-warmup", f"{label}: no warmup operations")
                report.require(
                    validation.get("completedOperations") is completed_operations
                    and validation.get("requiredOperations") == requested_operations
                    and validation.get("measuredOperations") == measured_operations
                    and validation.get("operationMeasurementsValid")
                    is operation_measurements_valid,
                    "completed-operations-flag",
                    f"{label}: completed-operations evidence is inconsistent",
                )
                report.require(
                    validation.get("requestedMeasurementNanos")
                    == minimum_measurement
                    and validation.get("observedMeasurementNanos")
                    == measurement_nanos
                    and validation.get("measurementDurationPassed")
                    is duration_passed,
                    "duration-gate-coherence",
                    f"{label}: measurement-duration evidence is inconsistent",
                )
                metrics_after_workload = workload.get("providerMetricsAfterWorkload")
                metrics_after_write_probe = workload.get("providerMetricsAfterWriteProbe")
                metrics = workload.get("providerMetrics")
                after_workload_valid = (
                    isinstance(metrics_after_workload, dict)
                    and isinstance(metrics_after_workload.get("currentEntries"), int)
                    and not isinstance(
                        metrics_after_workload.get("currentEntries"), bool
                    )
                    and metrics_after_workload.get("currentEntries") >= 0
                    and finite_nonnegative_number(
                        metrics_after_workload.get("hitRate")
                    )
                    and float(metrics_after_workload.get("hitRate")) <= 1.0
                )
                after_write_probe_valid = (
                    isinstance(metrics_after_write_probe, dict)
                    and isinstance(
                        metrics_after_write_probe.get("currentEntries"), int
                    )
                    and not isinstance(
                        metrics_after_write_probe.get("currentEntries"), bool
                    )
                    and metrics_after_write_probe.get("currentEntries") >= 0
                )
                metric_checkpoints_valid = (
                    after_workload_valid and after_write_probe_valid
                )
                metrics_shape_valid = (
                    isinstance(metrics_after_workload, dict)
                    and isinstance(metrics_after_write_probe, dict)
                    and isinstance(metrics, dict)
                )
                report.require(
                    metrics_shape_valid,
                    "provider-metrics-checkpoints",
                    f"{label}: both provider metric checkpoints and the legacy alias are required",
                )
                if not metrics_shape_valid:
                    metrics_after_workload = {}
                    metrics_after_write_probe = {}
                    metrics = {}
                report.require(
                    metric_checkpoints_valid,
                    "provider-metrics-checkpoint-values",
                    f"{label}: provider metric checkpoints are malformed",
                )
                report.require(
                    metrics == metrics_after_write_probe,
                    "provider-metrics-alias",
                    f"{label}: providerMetrics must exactly alias the post-write checkpoint",
                )
                observed_hit_rate = (
                    float(metrics_after_workload.get("hitRate"))
                    if after_workload_valid else 0.0
                )
                observed_entries_after_workload = (
                    int(metrics_after_workload.get("currentEntries"))
                    if after_workload_valid else 0
                )
                observed_entries_after_write_probe = (
                    int(metrics_after_write_probe.get("currentEntries"))
                    if after_write_probe_valid else 0
                )
                if provider == "nostore":
                    report.require(validation.get("gateType") == "no-store-control",
                                   "nostore-gate", f"{label}: wrong no-store gate")
                    report.require(validation.get("performanceComparisonEligible") is False,
                                   "nostore-performance", f"{label}: no-store marked comparable")
                    zero_hits = observed_hit_rate == 0.0
                    capacity_after_workload_passed = (
                        after_workload_valid
                        and observed_entries_after_workload == 0
                    )
                    capacity_after_write_probe_passed = (
                        after_write_probe_valid
                        and observed_entries_after_write_probe == 0
                    )
                    no_entries_retained = (
                        capacity_after_workload_passed
                        and capacity_after_write_probe_passed
                    )
                    report.require(
                        validation.get("expectedStoredEntries") == 0
                        and validation.get("providerMetricCheckpointsValid")
                        is metric_checkpoints_valid
                        and validation.get("observedEntriesAfterWorkload")
                        == observed_entries_after_workload
                        and validation.get("capacityAfterWorkloadPassed")
                        is capacity_after_workload_passed
                        and validation.get("observedEntriesAfterWriteProbe")
                        == observed_entries_after_write_probe
                        and validation.get("capacityAfterWriteProbePassed")
                        is capacity_after_write_probe_passed
                        and validation.get("capacityCheckPassed")
                        is no_entries_retained
                        and validation.get("noEntriesRetained")
                        is no_entries_retained
                        and validation.get("hitRate") == observed_hit_rate
                        and validation.get("zeroHits") is zero_hits
                        and validation.get("hitRateGateApplicable") is False
                        and validation.get("singleFlightGateApplicable") is False,
                        "nostore-validation-coherence",
                        f"{label}: no-store gate evidence is inconsistent",
                    )
                    expected_passed = (
                        completed_operations and duration_passed
                        and no_entries_retained and zero_hits
                    )
                else:
                    report.require(validation.get("gateType") == "cache-semantics",
                                   "cache-gate", f"{label}: wrong cache semantic gate")
                    expected_eligible = provider in PRIMARY_PERFORMANCE_PROVIDERS
                    report.require(validation.get("performanceComparisonEligible")
                                   is expected_eligible, "performance-eligibility",
                                   f"{label}: comparison eligibility mismatch")
                    expected_hit_rate = float(request.get("hitPercent", 0)) / 100.0
                    hit_rate_passed = (
                        str(request.get("workload", "")).lower() != "uniform"
                        or abs(observed_hit_rate - expected_hit_rate) <= 0.005
                    )
                    minimum_entries = int(int(request.get("entries", 0)) * 0.99)
                    capacity_after_workload_passed = (
                        after_workload_valid
                        and observed_entries_after_workload >= minimum_entries
                    )
                    capacity_after_write_probe_passed = (
                        after_write_probe_valid
                        and observed_entries_after_write_probe >= minimum_entries
                    )
                    capacity_passed = (
                        capacity_after_workload_passed
                        and capacity_after_write_probe_passed
                    )
                    single_flight_passed = bool(
                        workload.get("singleFlightPassed", False)
                    )
                    report.require(
                        validation.get("expectedHitRate") == expected_hit_rate
                        and validation.get("providerMetricCheckpointsValid")
                        is metric_checkpoints_valid
                        and validation.get("observedHitRate") == observed_hit_rate
                        and validation.get("hitRateWithinHalfPercentagePoint")
                        is hit_rate_passed
                        and validation.get("minimumExpectedEntriesAfterWorkload")
                        == minimum_entries
                        and validation.get("minimumExpectedEntriesAfterWriteProbe")
                        == minimum_entries
                        and validation.get("observedEntriesAfterWorkload")
                        == observed_entries_after_workload
                        and validation.get("capacityAfterWorkloadPassed")
                        is capacity_after_workload_passed
                        and validation.get("observedEntriesAfterWriteProbe")
                        == observed_entries_after_write_probe
                        and validation.get("capacityAfterWriteProbePassed")
                        is capacity_after_write_probe_passed
                        and validation.get("capacityCheckPassed")
                        is capacity_passed
                        and validation.get("singleFlightPassed")
                        is single_flight_passed,
                        "cache-validation-coherence",
                        f"{label}: cache gate evidence is inconsistent",
                    )
                    expected_passed = (
                        completed_operations and duration_passed
                        and hit_rate_passed and capacity_passed
                        and single_flight_passed
                    )
                report.require(
                    validation.get("passed") is expected_passed,
                    "semantic-gate-coherence",
                    f"{label}: aggregate semantic-gate outcome does not match "
                    "its recorded component checks",
                )
            protocol = raw.get("lifecycleProtocol", {})
            early_target = float(protocol.get("earlyThreadObservationSeconds", 0.0))
            final_target = float(protocol.get("finalObservationAndFindleaksSeconds", 0.0))
            validate_post_undeploy_timing(
                cycle.get("firstUndeployTiming"), early_target, final_target,
                report, f"{run_id} C{cycle_number} first undeploy",
            )
            validate_post_undeploy_timing(
                cycle.get("finalUndeployTiming"), early_target, final_target,
                report, f"{run_id} C{cycle_number} final undeploy",
            )
        for cycle in cycles:
            first_hash = cycle.get("workload", {}).get("accessPlanSha256")
            second_hash = cycle.get("redeployWorkload", {}).get("accessPlanSha256")
            report.require(first_hash == second_hash, "phase-access-plan-pairing",
                           f"{run_id} C{cycle.get('cycle')}: phase plans differ")
    report.require(len(run_ids) == 36, "completed-run-ids",
                   "completed processRunId values must be unique")
    report.require(set(grouped) == {(block, cycle) for block in range(1, 7)
                                    for cycle in range(1, 6)},
                   "pairing-groups", "expected 30 block/cycle pairing groups")
    for (block, cycle), values in sorted(grouped.items()):
        report.require(values["providers"] == set(PROVIDERS), "paired-provider-set",
                       f"block {block} C{cycle}: incomplete provider pairing")
        report.require(len(values["seeds"]) == 1, "paired-seed-set",
                       f"block {block} C{cycle}: providers used different seeds")
        report.require(len(values["accessPlans"]) == 1, "paired-access-plan-set",
                       f"block {block} C{cycle}: providers/phases used different access plans")
    validate_environment(raw, runs, report)
    return grouped


def csv_scalar_equal(text: str, value: Any) -> bool:
    if value is None:
        return text == ""
    if isinstance(value, bool):
        return text == str(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = float(text)
        except ValueError:
            return False
        return math.isclose(parsed, float(value), rel_tol=1e-12, abs_tol=1e-12)
    return text == str(value)


def validate_csv_table(path: Path, json_rows: list[dict[str, Any]],
                       report: ValidationReport, code: str) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            headers = reader.fieldnames or []
    except (OSError, UnicodeError, csv.Error) as failure:
        report.require(False, code, f"cannot read {path}: {failure}")
        return
    expected_headers: list[str] = []
    for row in json_rows:
        for key in row:
            if key not in expected_headers:
                expected_headers.append(key)
    report.require(headers == expected_headers, f"{code}-headers",
                   f"{path.name}: CSV headers differ from analysis JSON")
    report.require(len(rows) == len(json_rows), f"{code}-rows",
                   f"{path.name}: CSV/JSON row count differs")
    for index, (csv_row, json_row) in enumerate(zip(rows, json_rows), 1):
        for key in expected_headers:
            if not csv_scalar_equal(csv_row.get(key, ""), json_row.get(key)):
                report.require(False, f"{code}-value",
                               f"{path.name} row {index} field {key} differs from JSON")
                return


def validate_analysis(raw: dict[str, Any], analysis: dict[str, Any], directory: Path,
                      prefix: str, report: ValidationReport) -> None:
    report.require(analysis.get("schemaVersion") == 4, "analysis-schema",
                   "analysis schemaVersion must be 4")
    report.require(analysis.get("protocolVersion") == PROTOCOL_VERSION,
                   "analysis-protocol-version",
                   f"analysis protocolVersion must be {PROTOCOL_VERSION}")
    report.require(analysis.get("invalidBlocks") == [], "analysis-invalid-blocks",
                   "analysis contains invalid blocks")
    report.require(analysis.get("rankingProduced") is False and "winner" not in analysis,
                   "no-ranking", "protocol v4 must not emit a winner/ranking")
    expected_counts = {
        "observations": 360,
        "forks": 144,
        "lifecycleForks": 36,
        "summaries": 24,
        "lifecycleSummaries": 6,
    }
    for key, count in expected_counts.items():
        report.require(len(analysis.get(key, [])) == count, "analysis-count",
                       f"analysis.{key} must contain {count} rows")
    for key in ("observations", "forks", "lifecycleForks"):
        report.require(all(row.get("blockValid") is True for row in analysis.get(key, [])),
                       "analysis-block-valid", f"analysis.{key} contains an invalid block")
    runs_by_id = {run.get("processRunId"): run for run in raw.get("processRuns", [])}
    for lifecycle_fork in analysis.get("lifecycleForks", []):
        run_id = lifecycle_fork.get("processRunId")
        run = runs_by_id.get(run_id, {})
        corroborated_intervals = []
        for cycle in run.get("cycles", []):
            for phase, early_key, final_key, warning_key in (
                ("first-undeploy", "firstUndeployThreadEvidenceEarly",
                 "firstUndeployThreadEvidenceFinal", "firstUndeployThreadLeakWarnings"),
                ("final-undeploy", "finalUndeployThreadEvidenceEarly",
                 "finalUndeployThreadEvidenceFinal", "secondUndeployThreadLeakWarnings"),
            ):
                signatures = (
                    cycle.get(early_key, {}).get("jcsThreadSignatures", [])
                    + cycle.get(final_key, {}).get("jcsThreadSignatures", [])
                )
                warnings = cycle.get(warning_key, [])
                if signatures and warnings:
                    corroborated_intervals.append({
                        "cycle": cycle.get("cycle"),
                        "phase": phase,
                        "signatureObservationCount": len(signatures),
                        "threadLeakWarningCount": len(warnings),
                    })
        corroborated_count = len(corroborated_intervals)
        report.require(
            lifecycle_fork.get("jcs248CorroboratedUndeployCount") == corroborated_count,
            "jcs248-interval-count",
            f"{run_id}: JCS-248 corroborated undeploy count differs from raw",
        )
        report.require(
            lifecycle_fork.get("jcs248CorroboratedSignalObserved")
            is (corroborated_count > 0),
            "jcs248-interval-boolean",
            f"{run_id}: JCS-248 corroborated signal boolean differs from raw",
        )
        report.require(
            lifecycle_fork.get("jcs248CorroboratedIntervals") == corroborated_intervals,
            "jcs248-interval-details",
            f"{run_id}: JCS-248 corroborated interval details differ from raw",
        )
    raw_observations: dict[tuple[str, int, str], tuple[Any, ...]] = {}
    analysis_timing_fields = (
        "earlyThreadTargetSecondsAfterUndeploy",
        "finalDiagnosticTargetSecondsAfterUndeploy",
        "earlyThreadStartedSecondsAfterUndeploy",
        "earlyThreadCompletedSecondsAfterUndeploy",
        "finalDiagnosticStartedSecondsAfterUndeploy",
        "findLeaksCompletedSecondsAfterUndeploy",
        "finalSnapshotCompletedSecondsAfterUndeploy",
    )
    for run in raw.get("processRuns", []):
        for cycle in run.get("cycles", []):
            for phase, workload_key, validation_key in (
                ("initial", "workload", "protocolValidation"),
                ("redeploy", "redeployWorkload", "redeployProtocolValidation"),
            ):
                workload = cycle[workload_key]
                validation = cycle[validation_key]
                metrics_after_workload = workload.get("providerMetricsAfterWorkload", {})
                metrics_after_write_probe = workload.get(
                    "providerMetricsAfterWriteProbe", {}
                )
                timing = cycle.get(
                    "finalUndeployTiming" if phase == "redeploy"
                    else "firstUndeployTiming", {}
                )
                raw_observations[(run["processRunId"], cycle["cycle"], phase)] = (
                    cycle["requestSeed"], float(workload["operationsPerSecond"]),
                    float(metrics_after_workload.get("hitRate", 0.0)),
                    int(metrics_after_write_probe.get("currentEntries", 0)),
                    int(metrics_after_workload.get("currentEntries", 0)),
                    int(metrics_after_write_probe.get("currentEntries", 0)),
                    validation["passed"], validation["performanceComparisonEligible"],
                ) + tuple(timing.get(field) for field in analysis_timing_fields)
    seen: set[tuple[str, int, str]] = set()
    for observation in analysis.get("observations", []):
        key = (observation.get("processRunId"), observation.get("cycle"),
               observation.get("phase"))
        seen.add(key)
        expected = raw_observations.get(key)
        actual = (
            observation.get("requestSeed"), observation.get("operationsPerSecond"),
            observation.get("observedHitRate"), observation.get("observedEntries"),
            observation.get("observedEntriesAfterWorkload"),
            observation.get("observedEntriesAfterWriteProbe"),
            observation.get("semanticGatePassed"),
            observation.get("performanceComparisonEligible"),
        ) + tuple(observation.get(field) for field in analysis_timing_fields)
        report.require(expected == actual, "analysis-observation-coherence",
                       f"analysis observation {key} differs from raw")
    report.require(seen == set(raw_observations), "analysis-observation-keys",
                   "analysis observations do not cover raw phases exactly once")

    observations_by_run_phase: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for observation in analysis.get("observations", []):
        observations_by_run_phase[(
            observation.get("processRunId"), observation.get("phase")
        )].append(observation)
    fork_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fork in analysis.get("forks", []):
        key = (
            fork.get("processRunId"), fork.get("phase"), fork.get("analysisSet")
        )
        report.require(key not in fork_index, "analysis-fork-identity",
                       f"duplicate analysis fork row {key}")
        fork_index[key] = fork
        selected_cycles = (
            {1, 2, 3, 4, 5}
            if fork.get("analysisSet") == "primary-all-cycles"
            else {2, 3, 4, 5}
            if fork.get("analysisSet") == "sensitivity-without-cycle-1"
            else set()
        )
        selected = [
            observation
            for observation in observations_by_run_phase.get(
                (fork.get("processRunId"), fork.get("phase")), []
            )
            if observation.get("cycle") in selected_cycles
        ]
        expected_semantic = bool(selected) and all(
            observation.get("semanticGatePassed") is True
            for observation in selected
        )
        expected_eligible = bool(selected) and all(
            observation.get("performanceComparisonEligible") is True
            for observation in selected
        )
        expected_included = (
            fork.get("blockValid") is True
            and expected_semantic
            and expected_eligible
        )
        selected_operation_rates = [
            float(observation["operationsPerSecond"])
            for observation in selected
            if observation.get("operationsPerSecond") is not None
        ]
        expected_observed_median = (
            statistics.median(selected_operation_rates)
            if selected_operation_rates else None
        )
        expected_comparison_median = (
            expected_observed_median if expected_included else None
        )
        report.require(
            len(selected) == len(selected_cycles)
            and fork.get("cycleObservationCount") == len(selected_cycles),
            "analysis-fork-cycle-set",
            f"analysis fork row {key} has the wrong cycle set",
        )
        report.require(
            fork.get("semanticGatePassed") is expected_semantic,
            "analysis-fork-semantic-gate",
            f"analysis fork row {key} does not aggregate its window gates",
        )
        report.require(
            fork.get("performanceComparisonEligible") is expected_eligible,
            "analysis-fork-eligibility",
            f"analysis fork row {key} does not aggregate comparison eligibility",
        )
        report.require(
            fork.get("includedInPerformanceSummary") is expected_included,
            "analysis-fork-inclusion",
            f"analysis fork row {key} is not excluded according to its gates/block",
        )
        report.require(
            analysis_scalar_equal(
                fork.get("observedMedian_operationsPerSecond"),
                expected_observed_median,
            )
            and analysis_scalar_equal(
                fork.get("comparisonMedian_operationsPerSecond"),
                expected_comparison_median,
            ),
            "analysis-fork-throughput-median",
            f"analysis fork row {key} retains an excluded throughput value "
            "or has the wrong cycle median",
        )
        for field in ANALYSIS_PERFORMANCE_FIELDS[1:]:
            if (f"observedMedian_{field}" not in fork
                    and not any(field in observation for observation in selected)):
                continue
            selected_values = [
                float(observation[field])
                for observation in selected
                if observation.get(field) is not None
            ]
            expected_observed = (
                statistics.median(selected_values) if selected_values else None
            )
            expected_comparison = (
                expected_observed if expected_included else None
            )
            report.require(
                analysis_scalar_equal(
                    fork.get(f"observedMedian_{field}"), expected_observed
                )
                and analysis_scalar_equal(
                    fork.get(f"comparisonMedian_{field}"), expected_comparison
                ),
                "analysis-fork-metric-median",
                f"analysis fork row {key} retains excluded {field} data "
                "or has the wrong cycle median",
            )

    expected_fork_keys = {
        (run_id, phase, analysis_set)
        for run_id in runs_by_id
        for phase in ("initial", "redeploy")
        for analysis_set in (
            "primary-all-cycles", "sensitivity-without-cycle-1"
        )
    }
    report.require(set(fork_index) == expected_fork_keys,
                   "analysis-fork-coverage",
                   "analysis fork rows do not cover every JVM/phase/analysis set")

    summary_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for summary in analysis.get("summaries", []):
        key = (
            summary.get("scenario", "default"), summary.get("provider"),
            summary.get("phase"), summary.get("analysisSet"),
        )
        report.require(key not in summary_index, "analysis-summary-identity",
                       f"duplicate analysis summary row {key}")
        summary_index[key] = summary
        rows = [
            fork for fork in analysis.get("forks", [])
            if (
                fork.get("scenario", "default"), fork.get("provider"),
                fork.get("phase"), fork.get("analysisSet"),
            ) == key
        ]
        valid_rows = [row for row in rows if row.get("blockValid") is True]
        included_rows = [
            row for row in valid_rows
            if row.get("includedInPerformanceSummary") is True
        ]
        report.require(
            summary.get("observedForkCount") == len(rows)
            and summary.get("forkCount") == len(valid_rows)
            and summary.get("invalidBlockForkCount")
            == len(rows) - len(valid_rows),
            "analysis-summary-denominators",
            f"analysis summary {key} has inconsistent fork denominators",
        )
        report.require(
            summary.get("semanticGatePassForkCount") == sum(
                row.get("semanticGatePassed") is True for row in valid_rows
            ),
            "analysis-summary-semantic-count",
            f"analysis summary {key} has an inconsistent semantic-gate count",
        )
        report.require(
            summary.get("performanceIncludedForkCount") == len(included_rows),
            "analysis-summary-inclusion-count",
            f"analysis summary {key} includes a fork excluded by its gate",
        )
        included_throughputs = [
            float(row["comparisonMedian_operationsPerSecond"])
            for row in included_rows
            if row.get("comparisonMedian_operationsPerSecond") is not None
        ]
        expected_throughput_summary = descriptive(
            included_throughputs, "operationsPerSecond"
        )
        report.require(
            all(analysis_scalar_equal(summary.get(field), expected)
                for field, expected in expected_throughput_summary.items()),
            "analysis-summary-throughput",
            f"analysis summary {key} does not summarize only admitted fork medians",
        )
        for field in ANALYSIS_PERFORMANCE_FIELDS[1:]:
            if not any(f"observedMedian_{field}" in row for row in rows):
                continue
            included_values = [
                float(row[f"comparisonMedian_{field}"])
                for row in included_rows
                if row.get(f"comparisonMedian_{field}") is not None
            ]
            expected_metric_summary = descriptive(included_values, field)
            report.require(
                all(analysis_scalar_equal(summary.get(metric), expected)
                    for metric, expected in expected_metric_summary.items()),
                "analysis-summary-metric",
                f"analysis summary {key} does not summarize only admitted "
                f"{field} fork medians",
            )

    for provider in ("jcs321", "nostore"):
        report.require(all(row.get("performanceComparisonEligible") is False
                           and row.get("performanceIncludedForkCount") == 0
                           for row in analysis.get("summaries", [])
                           if row.get("provider") == provider),
                       "control-performance-exclusion",
                       f"{provider} is not fully excluded from performance summaries")
    paired = analysis.get("pairedRatios", [])
    report.require(isinstance(paired, list) and len(paired) <= 12,
                   "paired-ratio-count",
                   "pairedRatios must be an array with at most 12 rows")
    report.require(all(row.get("provider") in {"caffeine", "ehcache", "cache2k"}
                       for row in paired),
                   "paired-ratio-providers",
                   "paired ratios may contain only caffeine, ehcache, and cache2k")
    report.require(all(row.get("referenceProvider") == "jcs4" for row in paired),
                   "paired-ratio-reference", "all paired ratios must reference JCS 4")
    expected_ratio_blocks: dict[tuple[str, str, str, str], list[int]] = {}
    for provider in ("caffeine", "ehcache", "cache2k"):
        for phase in ("initial", "redeploy"):
            for analysis_set in (
                "primary-all-cycles", "sensitivity-without-cycle-1"
            ):
                blocks = []
                for block in range(1, 7):
                    numerator = next((
                        row for row in analysis.get("forks", [])
                        if row.get("scenario", "default") == "default"
                        and row.get("provider") == provider
                        and row.get("block") == block
                        and row.get("phase") == phase
                        and row.get("analysisSet") == analysis_set
                    ), None)
                    reference = next((
                        row for row in analysis.get("forks", [])
                        if row.get("scenario", "default") == "default"
                        and row.get("provider") == "jcs4"
                        and row.get("block") == block
                        and row.get("phase") == phase
                        and row.get("analysisSet") == analysis_set
                    ), None)
                    if (numerator is not None and reference is not None
                            and numerator.get("includedInPerformanceSummary") is True
                            and reference.get("includedInPerformanceSummary") is True):
                        blocks.append(block)
                if blocks:
                    expected_ratio_blocks[(
                        "default", provider, phase, analysis_set
                    )] = blocks
    actual_ratio_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in paired:
        key = (
            row.get("scenario", "default"), row.get("provider"),
            row.get("phase"), row.get("analysisSet"),
        )
        report.require(key not in actual_ratio_index, "paired-ratio-identity",
                       f"duplicate paired-ratio row {key}")
        actual_ratio_index[key] = row
        values = row.get("valuesByBlock", [])
        actual_blocks = [
            value.get("block") for value in values if isinstance(value, dict)
        ] if isinstance(values, list) else []
        report.require(
            actual_blocks == expected_ratio_blocks.get(key, []),
            "paired-ratio-blocks",
            f"paired ratio {key} does not contain exactly the admitted blocks",
        )
        if "ratioToJcs4N" in row:
            report.require(row.get("ratioToJcs4N") == len(actual_blocks),
                           "paired-ratio-denominator",
                           f"paired ratio {key} has the wrong pair denominator")
    report.require(set(actual_ratio_index) == set(expected_ratio_blocks),
                   "paired-ratio-coverage",
                   "paired-ratio rows do not match the admitted provider/JCS4 pairs")
    exclusions = analysis.get("performanceExclusions", {})
    report.require("jcs321" in exclusions and "nostore" in exclusions,
                   "analysis-control-exclusions", "analysis exclusion reasons are incomplete")
    csv_mapping = {
        "summary": "summaries",
        "forks": "forks",
        "observations": "observations",
        "lifecycle-summary": "lifecycleSummaries",
        "lifecycle-forks": "lifecycleForks",
    }
    for suffix, key in csv_mapping.items():
        validate_csv_table(directory / f"{prefix}-{suffix}.csv", analysis.get(key, []),
                           report, f"csv-{suffix}")


def referenced_diagnostic_files(raw: dict[str, Any]) -> Iterable[str]:
    stack: list[Any] = [raw]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            artifacts = value.get("diagnosticArtifacts")
            if isinstance(artifacts, dict):
                for filename in artifacts.values():
                    if isinstance(filename, str):
                        yield filename
            archived = value.get("archivedBuildFiles")
            if isinstance(archived, list):
                for item in archived:
                    if isinstance(item, dict) and isinstance(item.get("file"), str):
                        yield item["file"]
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def validate_diagnostics(raw: dict[str, Any], directory: Path,
                         report: ValidationReport) -> None:
    metadata = raw.get("diagnosticArchive", {})
    if not report.require(isinstance(metadata, dict), "diagnostic-archive-metadata",
                          "diagnosticArchive metadata must be an object"):
        return
    archive_path = sibling_file(directory, metadata.get("file"), report,
                                "diagnostic-archive-name")
    if archive_path is None:
        return
    if not report.require(archive_path.is_file(), "diagnostic-archive",
                          f"diagnostic archive not found: {archive_path}"):
        return
    report.require(archive_path.stat().st_size == metadata.get("sizeBytes"),
                   "diagnostic-archive-size", "diagnostic archive size mismatch")
    report.require(sha256_file(archive_path) == metadata.get("sha256"),
                   "diagnostic-archive-sha", "diagnostic archive SHA-256 mismatch")
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as failure:
        report.require(False, "diagnostic-archive-zip", f"invalid ZIP archive: {failure}")
        return
    with archive:
        names = {name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")}
        references = set(referenced_diagnostic_files(raw))
        report.require(bool(references), "diagnostic-references",
                       "raw campaign contains no diagnostic artifact references")
        for filename in sorted(references):
            report.require(filename.replace("\\", "/") in names,
                           "diagnostic-member", f"missing diagnostic member {filename}")
        jcs_heap_dumps = 0
        for run in raw.get("processRuns", []):
            run_id = run.get("processRunId")
            provider = run.get("provider")
            heap_dump = run.get("finalHeapDump")
            if provider in {"jcs4", "jcs321"}:
                jcs_heap_dumps += 1
                if not report.require(isinstance(heap_dump, dict), "jcs-heap-dump",
                                      f"{run_id}: JCS final heap dump is missing"):
                    continue
            if not isinstance(heap_dump, dict):
                continue
            filename = str(heap_dump.get("file", "")).replace("\\", "/")
            if not report.require(filename in names, "heap-dump-member",
                                  f"{run_id}: heap dump absent from diagnostics ZIP"):
                continue
            info = archive.getinfo(filename)
            report.require(info.file_size == heap_dump.get("sizeBytes"),
                           "heap-dump-size", f"{run_id}: heap dump size mismatch")
            report.require(sha256_zip_member(archive, filename) == heap_dump.get("sha256"),
                           "heap-dump-sha", f"{run_id}: heap dump SHA-256 mismatch")
            command_artifact = heap_dump.get("jcmdOutput")
            report.require(isinstance(command_artifact, str)
                           and command_artifact.replace("\\", "/") in names,
                           "heap-dump-command", f"{run_id}: heap dump command log is missing")
        report.require(jcs_heap_dumps == 12, "jcs-heap-dump-count",
                       "exactly 12 JCS process runs must carry heap dumps")
        for run in raw.get("processRuns", []):
            for cycle in run.get("cycles", []):
                for early_key in ("afterUndeployEarly", "afterFinalUndeployEarly"):
                    artifacts = cycle.get(early_key, {}).get("diagnosticArtifacts", {})
                    report.require({"threadDump", "tomcatLog"} <= set(artifacts),
                                   "early-thread-diagnostic",
                                   f"{run.get('processRunId')} C{cycle.get('cycle')}: "
                                   f"{early_key} early diagnostic set is incomplete")
                for final_key in ("afterUndeploy", "afterFinalUndeploy"):
                    artifacts = cycle.get(final_key, {}).get("diagnosticArtifacts", {})
                    required = {"heapInfo", "classloaderStats", "threadDump", "nativeMemory",
                                "classHistogram", "tomcatFindLeaks"}
                    report.require(required <= set(artifacts), "final-diagnostic-set",
                                   f"{run.get('processRunId')} C{cycle.get('cycle')}: "
                                   f"{final_key} diagnostic set is incomplete")


def validate_campaign(results_path: Path) -> ValidationReport:
    report = ValidationReport()
    results_path = results_path.resolve()
    raw = load_json(results_path, report, "raw-json")
    if raw is None:
        return report
    directory = results_path.parent
    suffix = "-results.json"
    prefix = results_path.name[:-len(suffix)] if results_path.name.endswith(suffix) else results_path.stem
    report.require(prefix.startswith(CAMPAIGN_PREFIX + "-"),
                   "campaign-prefix",
                   f"campaign filename must start with {CAMPAIGN_PREFIX}-")
    validate_shape(raw, report)
    validate_schedule(raw, report)
    validate_source_provenance(raw, report)
    runs = raw.get("processRuns", []) if isinstance(raw.get("processRuns"), list) else []
    if len(runs) == 36:
        validate_runs(raw, report)
    analysis_path = sibling_file(directory, raw.get("analysisFile"), report,
                                 "analysis-file-name")
    if analysis_path is not None and report.require(analysis_path.is_file(), "analysis-file",
                                                    f"analysis JSON not found: {analysis_path}"):
        expected_sha = raw.get("analysisSha256")
        report.require(isinstance(expected_sha, str) and bool(HEX64.fullmatch(expected_sha)),
                       "analysis-sha-format", "analysis SHA-256 is malformed")
        report.require(sha256_file(analysis_path) == expected_sha, "analysis-sha",
                       "analysis JSON SHA-256 mismatch")
        analysis = load_json(analysis_path, report, "analysis-json")
        if analysis is not None:
            validate_analysis(raw, analysis, directory, prefix, report)
    validate_diagnostics(raw, directory, report)
    return report


def print_report(path: Path, report: ValidationReport) -> None:
    state = "PASS" if report.passed else "FAIL"
    print(f"Campaign v4.2 validation: {state}")
    print(f"Input: {path.resolve()}")
    print(f"Checks: {report.checks}; errors: {len(report.errors)}; "
          f"warnings: {len(report.warnings)}")
    for error in report.errors:
        print(f"ERROR {error}")
    for warning in report.warnings:
        print(f"WARNING {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a completed 36-run protocol-v4.2 cache campaign read-only."
    )
    parser.add_argument("results_json", type=Path,
                        help="path to <campaign>-results.json")
    arguments = parser.parse_args(argv)
    report = validate_campaign(arguments.results_json)
    print_report(arguments.results_json, report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())

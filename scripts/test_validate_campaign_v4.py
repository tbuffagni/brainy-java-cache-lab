import csv
import hashlib
import json
import statistics
import tempfile
import unittest
import zipfile
from pathlib import Path

import validate_campaign_v4 as validator


class SyntheticCampaign:
    def __init__(self, directory: Path):
        self.directory = directory
        self.prefix = "article1-unified-v4-2-synthetic"
        self.members = {
            "early-thread.txt": b"thread dump\n",
            "early-log.txt": b"tomcat log\n",
            "heap.txt": b"heap\n",
            "loaders.txt": b"loaders\n",
            "thread.txt": b"thread\n",
            "native.txt": b"native\n",
            "histogram.txt": b"histogram\n",
            "findleaks.txt": b"OK - No memory leaks found\n",
        }
        self.analysis = self._analysis()
        self.raw = self._raw()
        self.results_path = directory / f"{self.prefix}-results.json"
        self._write_all()

    @staticmethod
    def _environment(container_id: str) -> dict:
        checksum = "b" * 64
        return {
            "Tomcat Version": "Apache Tomcat/11.0-test",
            "OS Name": "Linux",
            "OS Version": "test",
            "OS Architecture": "amd64",
            "JVM Version": "25-test",
            "JVM Vendor": "Eclipse Adoptium",
            "dockerImageId": "sha256:" + "c" * 64,
            "containerImageName": "testcache-tomcat:latest",
            "containerId": container_id,
            "containerStartedAt": "2026-09-02T00:00:00Z",
            "imageJcs4RevisionLabel": "a" * 40,
            "containerCpuLimit": 4.0,
            "containerMemoryLimitBytes": 1610612736,
            "containerOS": "Ubuntu test",
            "containerCpuModel": "Synthetic Benchmark CPU",
            "containerVisibleProcessors": 8,
            "containerKernel": "Linux synthetic 6.6.0 #1 SMP x86_64 GNU/Linux",
            "dockerServerVersion": "28.3.3",
            "dockerServerOperatingSystem": "Docker Desktop",
            "dockerServerKernelVersion": "6.6.0-linuxkit",
            "dockerServerArchitecture": "x86_64",
            "dockerServerName": "docker-desktop",
            "javaOptions": "-Xms256m -Xmx768m -XX:NativeMemoryTracking=summary",
            "jcs4SourceCommit": "a" * 40,
            "jvmCommandLine": "VM Arguments: -Xmx768m",
            "jvmFlags": "-XX:MaxHeapSize=805306368",
            "runtimeBaseImage": {
                "reference": "tomcat:test@sha256:" + "1" * 64,
                "inspectionAvailable": True,
                "pinnedDigest": "sha256:" + "1" * 64,
            },
            "buildBaseImage": {
                "reference": "maven:test@sha256:" + "2" * 64,
                "inspectionAvailable": True,
                "pinnedDigest": "sha256:" + "2" * 64,
            },
            "warSha256": checksum,
            "jcs4ArtifactSha256": "c" * 64,
            "jcs321ArtifactSha256": "d" * 64,
            "artifactManifest": [
                {"sha256": checksum, "containerPath": "/artifacts/cache-benchmark.war"},
                {"sha256": "c" * 64, "containerPath": "/artifacts/commons-jcs4-core.jar"},
                {"sha256": "d" * 64, "containerPath": "/artifacts/commons-jcs3-core.jar"},
            ],
            "provenanceValidationPassed": True,
            "provenanceValidationErrors": [],
        }

    @staticmethod
    def _descriptive(values: list[float], prefix: str) -> dict:
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

        def quantile(probability: float) -> float:
            ordered = sorted(values)
            position = (len(ordered) - 1) * probability
            lower = int(position)
            upper = min(lower + 1, len(ordered) - 1)
            fraction = position - lower
            return ordered[lower] + fraction * (ordered[upper] - ordered[lower])

        return {
            f"{prefix}N": len(values),
            f"{prefix}Median": statistics.median(values),
            f"{prefix}Mean": statistics.mean(values),
            f"{prefix}SampleStandardDeviation": statistics.stdev(values),
            f"{prefix}FirstQuartile": quantile(0.25),
            f"{prefix}ThirdQuartile": quantile(0.75),
            f"{prefix}Minimum": min(values),
            f"{prefix}Maximum": max(values),
        }

    @staticmethod
    def _validation(provider: str) -> dict:
        if provider == "nostore":
            return {
                "gateType": "no-store-control",
                "performanceComparisonEligible": False,
                "completedOperations": True,
                "requiredOperations": 1000,
                "measuredOperations": 1000,
                "operationMeasurementsValid": True,
                "providerMetricCheckpointsValid": True,
                "requestedMeasurementNanos": 5_000_000_000,
                "observedMeasurementNanos": 5_000_000_000,
                "measurementDurationPassed": True,
                "expectedStoredEntries": 0,
                "observedEntriesAfterWorkload": 0,
                "capacityAfterWorkloadPassed": True,
                "observedEntriesAfterWriteProbe": 0,
                "capacityAfterWriteProbePassed": True,
                "capacityCheckPassed": True,
                "zeroHits": True,
                "noEntriesRetained": True,
                "hitRate": 0.0,
                "hitRateGateApplicable": False,
                "singleFlightGateApplicable": False,
                "passed": True,
            }
        return {
            "gateType": "cache-semantics",
            "performanceComparisonEligible": provider in validator.PRIMARY_PERFORMANCE_PROVIDERS,
            "completedOperations": True,
            "requiredOperations": 1000,
            "measuredOperations": 1000,
            "operationMeasurementsValid": True,
            "providerMetricCheckpointsValid": True,
            "requestedMeasurementNanos": 5_000_000_000,
            "observedMeasurementNanos": 5_000_000_000,
            "measurementDurationPassed": True,
            "expectedHitRate": 0.95,
            "observedHitRate": 0.95,
            "hitRateWithinHalfPercentagePoint": True,
            "minimumExpectedEntriesAfterWorkload": 9900,
            "minimumExpectedEntriesAfterWriteProbe": 9900,
            "observedEntriesAfterWorkload": 10000,
            "capacityAfterWorkloadPassed": True,
            "observedEntriesAfterWriteProbe": 10000,
            "capacityAfterWriteProbePassed": True,
            "capacityCheckPassed": True,
            "singleFlightPassed": True,
            "passed": True,
        }

    @staticmethod
    def _snapshot() -> dict:
        return {
            "heapUsedBytes": 1000000,
            "nativeCommittedBytes": 2000000,
            "webappClassloaderCount": 1,
            "liveThreadCount": 20,
            "jcsThreadSignatures": [],
            "tomcatFindLeaksOccurrenceCount": 0,
            "tomcatFindLeaksOccurrenceCountsByContext": {},
            "tomcatFindLeaksContexts": [],
            "diagnosticArtifacts": {
                "heapInfo": "heap.txt",
                "classloaderStats": "loaders.txt",
                "threadDump": "thread.txt",
                "nativeMemory": "native.txt",
                "classHistogram": "histogram.txt",
                "tomcatFindLeaks": "findleaks.txt",
            },
        }

    @staticmethod
    def _early_snapshot() -> dict:
        return {
            "jcsThreadSignatures": [],
            "diagnosticArtifacts": {
                "threadDump": "early-thread.txt",
                "tomcatLog": "early-log.txt",
            },
        }

    @staticmethod
    def _timing() -> dict:
        return {
            "earlyThreadSecondsAfterUndeploy": 2.0,
            "finalMeasurementSecondsAfterUndeploy": 10.0,
            "earlyThreadTargetSecondsAfterUndeploy": 2.0,
            "finalDiagnosticTargetSecondsAfterUndeploy": 10.0,
            "earlyThreadStartedSecondsAfterUndeploy": 2.01,
            "earlyThreadCompletedSecondsAfterUndeploy": 2.10,
            "finalDiagnosticStartedSecondsAfterUndeploy": 10.25,
            "findLeaksCompletedSecondsAfterUndeploy": 12.0,
            "finalSnapshotCompletedSecondsAfterUndeploy": 15.0,
        }

    @staticmethod
    def _workload(provider: str, access_plan: str, operations: float) -> dict:
        nostore = provider == "nostore"
        metrics_after_workload = {
            "hitRate": 0.0 if nostore else 0.95,
            "currentEntries": 0 if nostore else 10000,
        }
        metrics_after_write_probe = {
            "hitRate": 0.0 if nostore else 0.95,
            "currentEntries": 0 if nostore else 10000,
        }
        return {
            "provider": provider,
            "warmupOperationsExecuted": 1000,
            "warmupNanos": 3_000_000_000,
            "accessPlanSha256": access_plan,
            "operationsPerSecond": operations,
            "measuredOperations": 1000,
            "measurementNanos": 5_000_000_000,
            "singleFlightPassed": not nostore,
            "providerMetricsAfterWorkload": metrics_after_workload,
            "providerMetricsAfterWriteProbe": metrics_after_write_probe,
            "providerMetrics": metrics_after_write_probe,
        }

    def _raw(self) -> dict:
        base_seed = 24301
        schedule_seed = 2482026
        plan = []
        runs = []
        for block, row in enumerate(validator.WILLIAMS_ROWS, 1):
            for position, provider in enumerate(row, 1):
                run_id = f"run-f{block:02d}-p{position}-{provider}"
                plan.append({
                    "processRunId": run_id,
                    "scenario": "default",
                    "provider": provider,
                    "fork": block,
                    "block": block,
                    "williamsRow": block,
                    "orderPosition": position,
                    "pairedRequestSeedsByCycle": {
                        str(cycle): validator.paired_request_seed(
                            base_seed, schedule_seed, block, cycle
                        ) for cycle in range(1, 6)
                    },
                })
                cycles = []
                for cycle in range(1, 6):
                    seed = validator.paired_request_seed(base_seed, schedule_seed, block, cycle)
                    access_plan = hashlib.sha256(f"{block}:{cycle}".encode()).hexdigest()
                    operation_rate = 1000.0 + block * 10 + cycle
                    request = {
                        "seed": seed,
                        "entries": 10000,
                        "operations": 1000,
                        "hitPercent": 95,
                        "workload": "uniform",
                        "warmupSeconds": 3.0,
                        "measurementSeconds": 5.0,
                    }
                    jcs321_signature = (
                        [{"id": cycle, "name": "JCS-ElementEventQueue-Thread-1",
                          "signature": "jcs3-element-event-queue"}]
                        if provider == "jcs321" else []
                    )
                    thread_warning = (
                        ["WARNING web application started a thread JCS-ElementEventQueue-Thread-1"]
                        if provider == "jcs321" else []
                    )
                    cycles.append({
                        "cycle": cycle,
                        "requestSeed": seed,
                        "request": request,
                        "workload": self._workload(provider, access_plan, operation_rate),
                        "redeployWorkload": self._workload(provider, access_plan,
                                                            operation_rate + 1),
                        "protocolValidation": self._validation(provider),
                        "redeployProtocolValidation": self._validation(provider),
                        "afterUndeployEarly": self._early_snapshot(),
                        "afterFinalUndeployEarly": self._early_snapshot(),
                        "afterUndeploy": self._snapshot(),
                        "afterFinalUndeploy": self._snapshot(),
                        "firstUndeployTiming": self._timing(),
                        "finalUndeployTiming": self._timing(),
                        "firstUndeployThreadEvidenceEarly": {
                            "jcsThreadSignatures": jcs321_signature,
                        },
                        "firstUndeployThreadEvidenceFinal": {
                            "jcsThreadSignatures": [],
                        },
                        "finalUndeployThreadEvidenceEarly": {
                            "jcsThreadSignatures": jcs321_signature,
                        },
                        "finalUndeployThreadEvidenceFinal": {
                            "jcsThreadSignatures": [],
                        },
                        "firstUndeployThreadLeakWarnings": thread_warning,
                        "secondUndeployThreadLeakWarnings": thread_warning,
                    })
                heap_dump = None
                if provider in {"jcs4", "jcs321"}:
                    heap_name = f"{run_id}.hprof"
                    command_name = f"{run_id}-heap-command.txt"
                    content = f"heap dump {run_id}".encode()
                    self.members[heap_name] = content
                    self.members[command_name] = b"Heap dump file created\n"
                    heap_dump = {
                        "policy": "jcs",
                        "file": heap_name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "sizeBytes": len(content),
                        "jcmdOutput": command_name,
                    }
                runs.append({
                    "processRunId": run_id,
                    "scenario": "default",
                    "provider": provider,
                    "fork": block,
                    "block": block,
                    "williamsRow": block,
                    "orderPosition": position,
                    "environment": self._environment(hashlib.sha256(run_id.encode()).hexdigest()),
                    "cycles": cycles,
                    "finalHeapDump": heap_dump,
                })
        source_files = [
            {"path": validator.PROTOCOL_PATH,
             "sha256": validator.EXPECTED_PROTOCOL_SHA256, "sizeBytes": 1},
            {"path": "scripts/run_benchmark.py", "sha256": "e" * 64,
             "sizeBytes": 1},
        ]
        source_sha = hashlib.sha256(
            "\n".join(
                f"{item['sha256']}  {item['path']}" for item in source_files
            ).encode()
        ).hexdigest()
        preflight = self._environment("f" * 64)
        preflight["nativeMemoryTrackingSummaryAvailable"] = True
        return {
            "schemaVersion": 4,
            "protocolVersion": validator.PROTOCOL_VERSION,
            "campaignStartedAt": "2026-09-02T00:00:00Z",
            "campaignFinishedAt": "2026-09-02T12:00:00Z",
            "configuration": {"seed": base_seed},
            "matrix": {"threads": [8], "hitPercent": [95], "workloads": ["uniform"],
                       "jcsMemoryModes": ["strict"]},
            "providers": list(validator.PROVIDERS),
            "forks": 6,
            "cyclesPerProcessRun": 5,
            "schedule": {
                "design": "frozen canonical Williams 6x6",
                "canonicalRows": [list(row) for row in validator.WILLIAMS_ROWS],
                "selectedProviders": list(validator.PROVIDERS),
                "rowsAreShuffled": False,
                "scheduleSeed": schedule_seed,
                "forkRows": [
                    {"fork": block, "block": block, "williamsRow": block,
                     "order": list(row)}
                    for block, row in enumerate(validator.WILLIAMS_ROWS, 1)
                ],
            },
            "executionPlan": plan,
            "lifecycleProtocol": {
                "freshContainerPerProcessRun": True,
                "earlyThreadObservationSeconds": 2.0,
                "finalObservationAndFindleaksSeconds": 10.0,
                "findleaksOccurrencesPreserved": True,
                "finalHeapDumpPolicy": "jcs",
            },
            "campaignPreflight": preflight,
            "sourceProvenance": {"files": source_files, "manifestSha256": source_sha},
            "processRuns": runs,
            "infrastructureFailures": [],
            "invalidBlocks": [],
            "analysisFile": f"{self.prefix}-analysis.json",
        }

    def _analysis(self) -> dict:
        # Filled from the same deterministic identities used by _raw().
        observations = []
        forks = []
        lifecycle_forks = []
        summaries = []
        lifecycle_summaries = []
        paired = []
        for block, row in enumerate(validator.WILLIAMS_ROWS, 1):
            for position, provider in enumerate(row, 1):
                run_id = f"run-f{block:02d}-p{position}-{provider}"
                corroborated_intervals = []
                if provider == "jcs321":
                    for cycle in range(1, 6):
                        for phase in ("first-undeploy", "final-undeploy"):
                            corroborated_intervals.append({
                                "cycle": cycle,
                                "phase": phase,
                                "signatureObservationCount": 1,
                                "threadLeakWarningCount": 1,
                            })
                lifecycle_forks.append({
                    "processRunId": run_id,
                    "provider": provider,
                    "block": block,
                    "blockValid": True,
                    "jcs248CorroboratedUndeployCount": len(corroborated_intervals),
                    "jcs248CorroboratedIntervals": corroborated_intervals,
                    "jcs248CorroboratedSignalObserved": bool(corroborated_intervals),
                })
                for analysis_set in ("primary-all-cycles", "sensitivity-without-cycle-1"):
                    for phase in ("initial", "redeploy"):
                        eligible = provider in validator.PRIMARY_PERFORMANCE_PROVIDERS
                        selected_cycles = (
                            range(1, 6)
                            if analysis_set == "primary-all-cycles"
                            else range(2, 6)
                        )
                        observed_median = statistics.median([
                            1000.0 + block * 10 + cycle
                            + (phase == "redeploy")
                            for cycle in selected_cycles
                        ])
                        forks.append({
                            "processRunId": run_id,
                            "scenario": "default",
                            "provider": provider,
                            "fork": block,
                            "block": block,
                            "orderPosition": position,
                            "phase": phase,
                            "analysisSet": analysis_set,
                            "cycleObservationCount": (
                                5 if analysis_set == "primary-all-cycles" else 4
                            ),
                            "blockValid": True,
                            "semanticGatePassed": True,
                            "performanceComparisonEligible": eligible,
                            "includedInPerformanceSummary": eligible,
                            "observedMedian_operationsPerSecond": observed_median,
                            "comparisonMedian_operationsPerSecond": (
                                observed_median if eligible else None
                            ),
                        })
                for cycle in range(1, 6):
                    seed = validator.paired_request_seed(24301, 2482026, block, cycle)
                    for phase in ("initial", "redeploy"):
                        operations = 1000.0 + block * 10 + cycle + (phase == "redeploy")
                        observations.append({
                            "processRunId": run_id,
                            "scenario": "default",
                            "provider": provider,
                            "fork": block,
                            "block": block,
                            "orderPosition": position,
                            "cycle": cycle,
                            "phase": phase,
                            "requestSeed": seed,
                            "semanticGatePassed": True,
                            "performanceComparisonEligible": (
                                provider in validator.PRIMARY_PERFORMANCE_PROVIDERS
                            ),
                            "observedHitRate": 0.0 if provider == "nostore" else 0.95,
                            "observedEntries": 0 if provider == "nostore" else 10000,
                            "observedEntriesAfterWorkload": (
                                0 if provider == "nostore" else 10000
                            ),
                            "observedEntriesAfterWriteProbe": (
                                0 if provider == "nostore" else 10000
                            ),
                            "earlyThreadTargetSecondsAfterUndeploy": 2.0,
                            "finalDiagnosticTargetSecondsAfterUndeploy": 10.0,
                            "earlyThreadStartedSecondsAfterUndeploy": 2.01,
                            "earlyThreadCompletedSecondsAfterUndeploy": 2.10,
                            "finalDiagnosticStartedSecondsAfterUndeploy": 10.25,
                            "findLeaksCompletedSecondsAfterUndeploy": 12.0,
                            "finalSnapshotCompletedSecondsAfterUndeploy": 15.0,
                            "operationsPerSecond": operations,
                            "blockValid": True,
                        })
        for provider in validator.PROVIDERS:
            eligible = provider in validator.PRIMARY_PERFORMANCE_PROVIDERS
            lifecycle_summaries.append({"provider": provider, "forkCount": 6})
            for analysis_set in ("primary-all-cycles", "sensitivity-without-cycle-1"):
                for phase in ("initial", "redeploy"):
                    cycle_median = 3.0 if analysis_set == "primary-all-cycles" else 3.5
                    included_throughputs = (
                        [
                            1000.0 + block * 10 + cycle_median
                            + (phase == "redeploy")
                            for block in range(1, 7)
                        ]
                        if eligible else []
                    )
                    summaries.append({
                        "scenario": "default",
                        "provider": provider,
                        "phase": phase,
                        "analysisSet": analysis_set,
                        "forkCount": 6,
                        "observedForkCount": 6,
                        "invalidBlockForkCount": 0,
                        "semanticGatePassForkCount": 6,
                        "performanceComparisonEligible": eligible,
                        "performanceIncludedForkCount": 6 if eligible else 0,
                        **self._descriptive(
                            included_throughputs, "operationsPerSecond"
                        ),
                    })
        for provider in ("caffeine", "ehcache", "cache2k"):
            for analysis_set in ("primary-all-cycles", "sensitivity-without-cycle-1"):
                for phase in ("initial", "redeploy"):
                    paired.append({
                        "scenario": "default",
                        "provider": provider,
                        "referenceProvider": "jcs4",
                        "phase": phase,
                        "analysisSet": analysis_set,
                        "valuesByBlock": [
                            {"block": block, "ratioToJcs4": 1.5}
                            for block in range(1, 7)
                        ],
                    })
        return {
            "schemaVersion": 4,
            "protocolVersion": validator.PROTOCOL_VERSION,
            "invalidBlocks": [],
            "rankingProduced": False,
            "performanceExclusions": {"jcs321": "positive control", "nostore": "control"},
            "summaries": summaries,
            "forks": forks,
            "lifecycleSummaries": lifecycle_summaries,
            "lifecycleForks": lifecycle_forks,
            "observations": observations,
            "pairedRatios": paired,
        }

    def _write_csv(self, suffix: str, rows: list[dict]) -> None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with (self.directory / f"{self.prefix}-{suffix}.csv").open(
                "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _write_all(self) -> None:
        analysis_path = self.directory / f"{self.prefix}-analysis.json"
        analysis_path.write_text(json.dumps(self.analysis, indent=2), encoding="utf-8")
        self.raw["analysisSha256"] = validator.sha256_file(analysis_path)
        mapping = {
            "summary": "summaries",
            "forks": "forks",
            "observations": "observations",
            "lifecycle-summary": "lifecycleSummaries",
            "lifecycle-forks": "lifecycleForks",
        }
        for suffix, key in mapping.items():
            self._write_csv(suffix, self.analysis[key])
        archive_path = self.directory / f"{self.prefix}-diagnostics.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, content in self.members.items():
                archive.writestr(filename, content)
        self.raw["diagnosticArchive"] = {
            "file": archive_path.name,
            "sha256": validator.sha256_file(archive_path),
            "sizeBytes": archive_path.stat().st_size,
        }
        self.results_path.write_text(json.dumps(self.raw, indent=2), encoding="utf-8")

    def rewrite_raw(self) -> None:
        self.results_path.write_text(json.dumps(self.raw, indent=2), encoding="utf-8")

    def rewrite_analysis_and_raw(self) -> None:
        analysis_path = self.directory / f"{self.prefix}-analysis.json"
        analysis_path.write_text(json.dumps(self.analysis, indent=2), encoding="utf-8")
        self.raw["analysisSha256"] = validator.sha256_file(analysis_path)
        mapping = {
            "summary": "summaries",
            "forks": "forks",
            "observations": "observations",
            "lifecycle-summary": "lifecycleSummaries",
            "lifecycle-forks": "lifecycleForks",
        }
        for suffix, key in mapping.items():
            self._write_csv(suffix, self.analysis[key])
        self.rewrite_raw()


class CampaignV4ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.campaign = SyntheticCampaign(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def _set_cycle_one_hit_rate_failure(self, exclude_from_analysis: bool) -> None:
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "caffeine" and row["block"] == 1
        )
        cycle = run["cycles"][0]
        for metrics_key in (
            "providerMetricsAfterWorkload",
            "providerMetricsAfterWriteProbe",
            "providerMetrics",
        ):
            cycle["workload"][metrics_key]["hitRate"] = 0.80
        validation = cycle["protocolValidation"]
        validation["observedHitRate"] = 0.80
        validation["hitRateWithinHalfPercentagePoint"] = False
        validation["passed"] = False

        observation = next(
            row for row in self.campaign.analysis["observations"]
            if row["processRunId"] == run["processRunId"]
            and row["cycle"] == 1 and row["phase"] == "initial"
        )
        observation["observedHitRate"] = 0.80
        observation["semanticGatePassed"] = False

        fork = next(
            row for row in self.campaign.analysis["forks"]
            if row["processRunId"] == run["processRunId"]
            and row["phase"] == "initial"
            and row["analysisSet"] == "primary-all-cycles"
        )
        fork["semanticGatePassed"] = False
        if exclude_from_analysis:
            fork["includedInPerformanceSummary"] = False
            fork["comparisonMedian_operationsPerSecond"] = None
            summary = next(
                row for row in self.campaign.analysis["summaries"]
                if row["provider"] == "caffeine"
                and row["phase"] == "initial"
                and row["analysisSet"] == "primary-all-cycles"
            )
            summary["semanticGatePassForkCount"] = 5
            summary["performanceIncludedForkCount"] = 5
            admitted_values = [
                row["comparisonMedian_operationsPerSecond"]
                for row in self.campaign.analysis["forks"]
                if row["provider"] == "caffeine"
                and row["phase"] == "initial"
                and row["analysisSet"] == "primary-all-cycles"
                and row["includedInPerformanceSummary"] is True
            ]
            summary.update(SyntheticCampaign._descriptive(
                admitted_values, "operationsPerSecond"
            ))
            paired = next(
                row for row in self.campaign.analysis["pairedRatios"]
                if row["provider"] == "caffeine"
                and row["phase"] == "initial"
                and row["analysisSet"] == "primary-all-cycles"
            )
            paired["valuesByBlock"] = [
                value for value in paired["valuesByBlock"]
                if value["block"] != 1
            ]
        self.campaign.rewrite_analysis_and_raw()

    def test_complete_synthetic_campaign_passes(self):
        report = validator.validate_campaign(self.campaign.results_path)

        self.assertTrue(report.passed, "\n".join(report.errors))
        self.assertGreater(report.checks, 1000)

    def test_semantic_failure_passes_when_analysis_excludes_primary_pair(self):
        self._set_cycle_one_hit_rate_failure(exclude_from_analysis=True)

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertTrue(report.passed, "\n".join(report.errors))

    def test_semantic_failure_fails_when_primary_pair_remains_included(self):
        self._set_cycle_one_hit_rate_failure(exclude_from_analysis=False)

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "analysis-fork-inclusion" in error for error in report.errors
        ))

    def test_cross_provider_access_plan_mismatch_fails(self):
        cycle = self.campaign.raw["processRuns"][0]["cycles"][0]
        cycle["workload"]["accessPlanSha256"] = "9" * 64
        cycle["redeployWorkload"]["accessPlanSha256"] = "9" * 64
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("paired-access-plan-set" in error for error in report.errors))

    def test_reused_container_identity_fails(self):
        first = self.campaign.raw["processRuns"][0]["environment"]["containerId"]
        self.campaign.raw["processRuns"][1]["environment"]["containerId"] = first
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("container-identity" in error for error in report.errors))

    def test_unpinned_runtime_base_image_fails(self):
        environment = self.campaign.raw["processRuns"][0]["environment"]
        environment["runtimeBaseImage"]["pinnedDigest"] = None
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("base-image-digest" in error for error in report.errors))

    def test_docker_kernel_incoherence_fails(self):
        environment = self.campaign.raw["processRuns"][0]["environment"]
        environment["dockerServerKernelVersion"] = "different-kernel"
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("environment-coherence" in error for error in report.errors))

    def test_container_kernel_hostname_difference_passes(self):
        environment = self.campaign.raw["processRuns"][0]["environment"]
        environment["containerKernel"] = (
            "Linux run-specific-container-id 6.6.0 #1 SMP x86_64 GNU/Linux"
        )
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertTrue(report.passed, "\n".join(report.errors))

    def test_container_kernel_release_difference_fails(self):
        environment = self.campaign.raw["processRuns"][0]["environment"]
        environment["containerKernel"] = (
            "Linux run-specific-container-id 6.7.0 #1 SMP x86_64 GNU/Linux"
        )
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "container-kernel-coherence" in error for error in report.errors
        ))

    def test_control_in_paired_ratios_fails(self):
        self.campaign.analysis["pairedRatios"][0]["provider"] = "jcs321"
        analysis_path = self.campaign.directory / f"{self.campaign.prefix}-analysis.json"
        analysis_path.write_text(json.dumps(self.campaign.analysis, indent=2), encoding="utf-8")
        self.campaign.raw["analysisSha256"] = validator.sha256_file(analysis_path)
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("paired-ratio-providers" in error for error in report.errors))

    def test_corroborated_interval_details_must_match_raw_evidence(self):
        lifecycle_row = next(
            row for row in self.campaign.analysis["lifecycleForks"]
            if row["provider"] == "jcs321"
        )
        lifecycle_row["jcs248CorroboratedIntervals"][0]["threadLeakWarningCount"] = 99
        analysis_path = self.campaign.directory / f"{self.campaign.prefix}-analysis.json"
        analysis_path.write_text(json.dumps(self.campaign.analysis, indent=2), encoding="utf-8")
        self.campaign.raw["analysisSha256"] = validator.sha256_file(analysis_path)
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("jcs248-interval-details" in error for error in report.errors))

    def test_protocol_version_4_1_is_rejected(self):
        self.campaign.raw["protocolVersion"] = "4.1"
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("protocol-version" in error for error in report.errors))

    def test_analysis_protocol_version_must_match_v4_2(self):
        self.campaign.analysis["protocolVersion"] = "4.1"
        self.campaign.rewrite_analysis_and_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "analysis-protocol-version" in error for error in report.errors
        ))

    def test_protocol_manifest_requires_frozen_v4_2_checksum(self):
        files = self.campaign.raw["sourceProvenance"]["files"]
        protocol = next(
            item for item in files if item["path"] == validator.PROTOCOL_PATH
        )
        protocol["sha256"] = "0" * 64
        self.campaign.raw["sourceProvenance"]["manifestSha256"] = hashlib.sha256(
            "\n".join(
                f"{item['sha256']}  {item['path']}" for item in files
            ).encode()
        ).hexdigest()
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("protocol-sha" in error for error in report.errors))

    def test_legacy_provider_metrics_must_equal_post_write_checkpoint(self):
        workload = self.campaign.raw["processRuns"][0]["cycles"][0]["workload"]
        workload["providerMetrics"] = dict(workload["providerMetricsAfterWriteProbe"])
        workload["providerMetrics"]["currentEntries"] = 9999
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("provider-metrics-alias" in error for error in report.errors))

    def test_cache_capacity_gate_is_and_of_both_checkpoints(self):
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "caffeine" and row["block"] == 1
        )
        cycle = run["cycles"][0]
        cycle["workload"]["providerMetricsAfterWorkload"]["currentEntries"] = 9800
        validation = cycle["protocolValidation"]
        validation["observedEntriesAfterWorkload"] = 9800
        validation["capacityAfterWorkloadPassed"] = False
        observation = next(
            row for row in self.campaign.analysis["observations"]
            if row["processRunId"] == run["processRunId"]
            and row["cycle"] == 1 and row["phase"] == "initial"
        )
        observation["observedEntriesAfterWorkload"] = 9800
        self.campaign.rewrite_analysis_and_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("cache-validation-coherence" in error for error in report.errors))
        self.assertTrue(any("semantic-gate-coherence" in error for error in report.errors))

    def test_minimum_expected_entries_after_workload_is_checked(self):
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "caffeine" and row["block"] == 1
        )
        run["cycles"][0]["protocolValidation"][
            "minimumExpectedEntriesAfterWorkload"
        ] = 9899
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any("cache-validation-coherence" in error for error in report.errors))

    def test_completed_operations_requires_the_requested_count(self):
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "caffeine" and row["block"] == 1
        )
        cycle = run["cycles"][0]
        cycle["workload"]["measuredOperations"] = 999
        validation = cycle["protocolValidation"]
        validation["measuredOperations"] = 999
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "completed-operations-flag" in error for error in report.errors
        ))

    def test_analysis_gate_must_reflect_incomplete_operation_count(self):
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "caffeine" and row["block"] == 1
        )
        cycle = run["cycles"][0]
        cycle["workload"]["measuredOperations"] = 999
        validation = cycle["protocolValidation"]
        validation["measuredOperations"] = 999
        validation["completedOperations"] = False
        validation["passed"] = False
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "analysis-observation-coherence" in error for error in report.errors
        ))

    def test_nostore_must_be_empty_at_both_checkpoints(self):
        run = next(
            row for row in self.campaign.raw["processRuns"]
            if row["provider"] == "nostore" and row["block"] == 1
        )
        cycle = run["cycles"][0]
        cycle["workload"]["providerMetricsAfterWorkload"]["currentEntries"] = 1
        cycle["protocolValidation"]["observedEntriesAfterWorkload"] = 1
        observation = next(
            row for row in self.campaign.analysis["observations"]
            if row["processRunId"] == run["processRunId"]
            and row["cycle"] == 1 and row["phase"] == "initial"
        )
        observation["observedEntriesAfterWorkload"] = 1
        self.campaign.rewrite_analysis_and_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "nostore-validation-coherence" in error for error in report.errors
        ))

    def test_delayed_final_diagnostics_after_target_are_accepted(self):
        run = self.campaign.raw["processRuns"][0]
        timing = run["cycles"][0][
            "firstUndeployTiming"
        ]
        timing["finalDiagnosticStartedSecondsAfterUndeploy"] = 25.0
        timing["findLeaksCompletedSecondsAfterUndeploy"] = 28.0
        timing["finalSnapshotCompletedSecondsAfterUndeploy"] = 30.0
        observation = next(
            row for row in self.campaign.analysis["observations"]
            if row["processRunId"] == run["processRunId"]
            and row["cycle"] == 1 and row["phase"] == "initial"
        )
        observation["finalDiagnosticStartedSecondsAfterUndeploy"] = 25.0
        observation["findLeaksCompletedSecondsAfterUndeploy"] = 28.0
        observation["finalSnapshotCompletedSecondsAfterUndeploy"] = 30.0
        self.campaign.rewrite_analysis_and_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertTrue(report.passed, "\n".join(report.errors))

    def test_post_undeploy_timing_order_is_checked(self):
        timing = self.campaign.raw["processRuns"][0]["cycles"][0][
            "firstUndeployTiming"
        ]
        baseline = dict(timing)
        cases = (
            ("earlyThreadStartedSecondsAfterUndeploy", 1.99,
             "early-diagnostic-start"),
            ("earlyThreadCompletedSecondsAfterUndeploy", 2.00,
             "early-diagnostic-completion"),
            ("finalDiagnosticStartedSecondsAfterUndeploy", 9.99,
             "final-diagnostic-start"),
            ("findLeaksCompletedSecondsAfterUndeploy", 10.20,
             "findleaks-completion"),
            ("finalSnapshotCompletedSecondsAfterUndeploy", 11.0,
             "final-snapshot-completion"),
        )
        for field, invalid_value, expected_code in cases:
            with self.subTest(field=field):
                timing.clear()
                timing.update(baseline)
                timing[field] = invalid_value
                self.campaign.rewrite_raw()

                report = validator.validate_campaign(self.campaign.results_path)

                self.assertFalse(report.passed)
                self.assertTrue(any(
                    expected_code in error for error in report.errors
                ), "\n".join(report.errors))

    def test_post_undeploy_timing_fields_are_mandatory(self):
        timing = self.campaign.raw["processRuns"][0]["cycles"][0][
            "finalUndeployTiming"
        ]
        del timing["findLeaksCompletedSecondsAfterUndeploy"]
        self.campaign.rewrite_raw()

        report = validator.validate_campaign(self.campaign.results_path)

        self.assertFalse(report.passed)
        self.assertTrue(any(
            "post-undeploy-timing-fields" in error for error in report.errors
        ))


if __name__ == "__main__":
    unittest.main()

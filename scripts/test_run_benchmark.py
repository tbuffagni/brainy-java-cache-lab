import unittest
from unittest import mock

import run_benchmark as benchmark


class DiagnosticParsingTest(unittest.TestCase):
    def test_cpu_info_prefers_model_name_over_numeric_processor_index(self):
        cpu_info = """processor : 0
vendor_id : GenuineIntel
model name : 13th Gen Intel(R) Core(TM) i7-13700H

processor : 1
vendor_id : GenuineIntel
model name : 13th Gen Intel(R) Core(TM) i7-13700H
"""

        model, visible = benchmark.parse_cpu_info(cpu_info)

        self.assertEqual("13th Gen Intel(R) Core(TM) i7-13700H", model)
        self.assertEqual(2, visible)

    def test_cpu_info_uses_arm_processor_description_as_fallback(self):
        cpu_info = """processor : ARMv8 Processor rev 1 (v8l)
processor : ARMv8 Processor rev 1 (v8l)
"""

        model, visible = benchmark.parse_cpu_info(cpu_info)

        self.assertEqual("ARMv8 Processor rev 1 (v8l)", model)
        self.assertEqual(2, visible)

    def test_thread_records_preserve_java_id_and_name(self):
        dump = """1:\n\"main\" #1 [9] prio=5 os_prio=0 tid=0x1 nid=0x1 runnable\n\"JCS-ElementEventQueue-Thread-1\" daemon #42 [50] prio=5 tid=0x2 nid=0x2 waiting\n"""

        self.assertEqual(
            [
                {"id": 1, "name": "main"},
                {"id": 42, "name": "JCS-ElementEventQueue-Thread-1"},
            ],
            benchmark.thread_records(dump),
        )

    def test_find_leak_contexts_returns_only_webapp_paths(self):
        report = "OK - Potential memory leaks found\n/caffeine\n/jcs\n/caffeine\n"

        self.assertEqual(
            ["/caffeine", "/jcs"], benchmark.find_leak_contexts(report)
        )
        self.assertEqual(
            ["/caffeine", "/jcs", "/caffeine"],
            benchmark.find_leak_occurrences(report),
        )

    def test_appended_log_lines_extracts_new_tail(self):
        previous = "old one\nold two\n"
        current = previous + "new one\nnew two\n"

        self.assertEqual(
            ["new one", "new two"],
            benchmark.appended_log_lines(previous, current),
        )

    def test_thread_leak_warning_is_classified_separately(self):
        lines = [
            "WARNING The web application [jcs] appears to have started a thread named [worker]",
            "WARNING unrelated warning",
        ]

        warnings, leaks, thread_leaks = benchmark.classified_warnings(lines)

        self.assertEqual(2, len(warnings))
        self.assertEqual(1, len(leaks))
        self.assertEqual(1, len(thread_leaks))

    def test_shared_forkjoin_thread_is_retained_as_unattributed_evidence(self):
        records = [
            {"id": 50, "name": "http-nio-8080-exec-11"},
            {"id": 51, "name": "ForkJoinPool.commonPool-worker-1"},
            {"id": 52, "name": "C2 CompilerThread1"},
            {"id": 53, "name": "JCS-ElementEventQueue-Thread-1"},
        ]

        self.assertEqual(
            [
                {"id": 51, "name": "ForkJoinPool.commonPool-worker-1"},
                {"id": 53, "name": "JCS-ElementEventQueue-Thread-1"},
            ],
            benchmark.candidate_application_threads(records),
        )

    def test_jcs_thread_signatures_distinguish_release_lines(self):
        records = [
            {"id": 1, "name": "JCS-ElementEventQueue-Thread-1"},
            {"id": 2, "name": "JCS-ThreadPoolManager-ElementEventQueue-Thread-1"},
            {"id": 3, "name": "http-nio-8080-exec-1"},
        ]

        self.assertEqual(
            ["jcs3-element-event-queue", "jcs4-thread-pool-event-queue"],
            [item["signature"] for item in benchmark.jcs_thread_signatures(records)],
        )

    def test_gc_is_forced_only_when_snapshot_requests_it(self):
        def fake_jcmd(command):
            return {
                "GC.run": "Command executed successfully",
                "GC.heap_info": "garbage-first heap used 100K, committed 200K",
                "VM.classloader_stats": "",
                "Thread.print": '"main" #1 prio=5 tid=0x1 nid=0x1 runnable',
                "VM.native_memory summary": "Total: reserved=300KB, committed=250KB",
                "GC.class_histogram": " num     #instances         #bytes  class name",
            }[command]

        with mock.patch.object(benchmark, "jcmd", side_effect=fake_jcmd) as jcmd_mock, \
                mock.patch.object(benchmark.time, "sleep"), \
                mock.patch.object(benchmark, "diagnostic_file", return_value="diagnostic.txt"):
            ordinary = benchmark.snapshot("ordinary")
            final = benchmark.snapshot(
                "final", archive_details=True, force_gc=True, include_histogram=True
            )

        self.assertEqual(0, ordinary["forcedGcCount"])
        self.assertEqual(2, final["forcedGcCount"])
        self.assertEqual(2, [call.args[0] for call in jcmd_mock.call_args_list].count("GC.run"))
        self.assertEqual(
            1,
            [call.args[0] for call in jcmd_mock.call_args_list].count("GC.class_histogram"),
        )
        self.assertEqual(
            [
                "GC.run", "GC.run", "GC.heap_info", "VM.classloader_stats",
                "Thread.print", "VM.native_memory summary", "GC.class_histogram",
            ],
            [call.args[0] for call in jcmd_mock.call_args_list][-7:],
        )


class FrozenDesignTest(unittest.TestCase):
    def test_williams_rows_are_frozen_in_canonical_order(self):
        schedule = benchmark.williams_schedule(benchmark.CANONICAL_PROVIDERS, 6)

        self.assertEqual(
            [
                ["caffeine", "ehcache", "nostore", "cache2k", "jcs321", "jcs4"],
                ["ehcache", "cache2k", "caffeine", "jcs4", "nostore", "jcs321"],
                ["cache2k", "jcs4", "ehcache", "jcs321", "caffeine", "nostore"],
                ["jcs4", "jcs321", "cache2k", "nostore", "ehcache", "caffeine"],
                ["jcs321", "nostore", "jcs4", "caffeine", "cache2k", "ehcache"],
                ["nostore", "caffeine", "jcs321", "ehcache", "jcs4", "cache2k"],
            ],
            [row["order"] for row in schedule],
        )

    def test_williams_design_balances_positions_and_ordered_predecessors(self):
        rows = [row["order"] for row in benchmark.williams_schedule(
            benchmark.CANONICAL_PROVIDERS, 6
        )]
        for provider in benchmark.CANONICAL_PROVIDERS:
            self.assertEqual([1] * 6, [
                sum(row[position] == provider for row in rows)
                for position in range(6)
            ])
        transitions = [(left, right) for row in rows for left, right in zip(row, row[1:])]
        self.assertEqual(30, len(set(transitions)))

    def test_request_seed_is_paired_but_changes_by_block_and_cycle(self):
        seed = benchmark.paired_request_seed(24301, 2482026, 2, 3)

        self.assertEqual(seed, benchmark.paired_request_seed(24301, 2482026, 2, 3))
        self.assertNotEqual(seed, benchmark.paired_request_seed(24301, 2482026, 2, 4))
        self.assertNotEqual(seed, benchmark.paired_request_seed(24301, 2482026, 3, 3))
        self.assertNotEqual(seed, benchmark.paired_request_seed(24302, 2482026, 2, 3))

    def test_single_provider_uses_diagnostic_cyclic_schedule(self):
        schedule = benchmark.williams_schedule(("jcs4",), 2)

        self.assertEqual([["jcs4"], ["jcs4"]], [row["order"] for row in schedule])
        self.assertEqual(["cyclic-subset", "cyclic-subset"], [row["design"] for row in schedule])
        self.assertEqual([None, None], [row["williamsRow"] for row in schedule])


class ProtocolV4AnalysisTest(unittest.TestCase):
    def test_no_store_uses_control_gate(self):
        request = {
            "hitPercent": 95, "workload": "uniform", "entries": 10000,
            "operations": 100,
        }
        workload = {
            "operationsPerSecond": 123.0,
            "measuredOperations": 100,
            "providerMetricsAfterWorkload": {"hitRate": 0.0, "currentEntries": 0},
            "providerMetricsAfterWriteProbe": {"hitRate": 0.0, "currentEntries": 0},
            "providerMetrics": {"hitRate": 0.0, "currentEntries": 0},
            "singleFlightPassed": False,
        }

        validation = benchmark.validate_protocol("nostore", request, workload, "redeploy")

        self.assertTrue(validation["passed"])
        self.assertFalse(validation["performanceComparisonEligible"])
        self.assertFalse(validation["hitRateGateApplicable"])
        self.assertTrue(validation["providerMetricCheckpointsValid"])

    def test_legacy_provider_metrics_alias_cannot_satisfy_v42_gate(self):
        request = {
            "hitPercent": 95, "workload": "uniform", "entries": 10000,
            "operations": 100,
        }
        workload = {
            "operationsPerSecond": 123.0,
            "measuredOperations": 100,
            "providerMetrics": {"hitRate": 0.0, "currentEntries": 0},
            "singleFlightPassed": False,
        }

        validation = benchmark.validate_protocol("nostore", request, workload, "initial")

        self.assertFalse(validation["providerMetricCheckpointsValid"])
        self.assertFalse(validation["capacityAfterWorkloadPassed"])
        self.assertFalse(validation["capacityAfterWriteProbePassed"])
        self.assertFalse(validation["passed"])

    def test_fewer_than_requested_operations_fails_gate(self):
        request = {
            "hitPercent": 95, "workload": "uniform", "entries": 10000,
            "operations": 100,
        }
        workload = {
            "operationsPerSecond": 123.0,
            "measuredOperations": 99,
            "providerMetricsAfterWorkload": {"hitRate": 0.95, "currentEntries": 10000},
            "providerMetricsAfterWriteProbe": {"hitRate": 0.95, "currentEntries": 10000},
            "providerMetrics": {"hitRate": 0.95, "currentEntries": 10000},
            "singleFlightPassed": True,
        }

        validation = benchmark.validate_protocol("caffeine", request, workload, "initial")

        self.assertFalse(validation["completedOperations"])
        self.assertFalse(validation["passed"])

    def test_semantic_failure_is_representable_without_exception(self):
        request = {
            "hitPercent": 95, "workload": "uniform", "entries": 10000,
            "operations": 100,
        }
        workload = {
            "operationsPerSecond": 123.0,
            "measuredOperations": 100,
            "providerMetricsAfterWorkload": {"hitRate": 0.50, "currentEntries": 5},
            "providerMetricsAfterWriteProbe": {"hitRate": 0.50, "currentEntries": 5},
            "providerMetrics": {"hitRate": 0.50, "currentEntries": 5},
            "singleFlightPassed": False,
        }

        validation = benchmark.validate_protocol("caffeine", request, workload, "initial")

        self.assertFalse(validation["passed"])
        self.assertTrue(validation["performanceComparisonEligible"])

    def test_jcs321_semantics_are_checked_but_performance_is_separate(self):
        request = {
            "hitPercent": 95, "workload": "uniform", "entries": 10000,
            "operations": 100,
        }
        workload = {
            "operationsPerSecond": 123.0,
            "measuredOperations": 100,
            "providerMetricsAfterWorkload": {"hitRate": 0.95, "currentEntries": 10000},
            "providerMetricsAfterWriteProbe": {"hitRate": 0.95, "currentEntries": 10000},
            "providerMetrics": {"hitRate": 0.95, "currentEntries": 10000},
            "singleFlightPassed": True,
        }

        validation = benchmark.validate_protocol("jcs321", request, workload, "initial")

        self.assertTrue(validation["passed"])
        self.assertFalse(validation["performanceComparisonEligible"])

    def test_absolute_slope_uses_absolute_final_values(self):
        self.assertEqual(100.0, benchmark.linear_slope([1000, 1100, 1200]))
        self.assertEqual(0.0, benchmark.linear_slope([42]))

    def test_analysis_has_fork_units_primary_and_sensitivity_without_ranking(self):
        def cycle(number, provider, operations, heap):
            eligible = provider != "nostore"
            validation = {
                "gateType": "cache-semantics" if eligible else "no-store-control",
                "passed": True,
                "performanceComparisonEligible": eligible,
            }
            workload = {
                "operationsPerSecond": operations,
                "readOperationsPerSecond": operations * 0.9,
                "writeOperationsPerSecond": operations * 0.1,
                "fillOperationsPerSecond": 1.0,
                "latencyP50Nanos": 10.0,
                "latencyP95Nanos": 20.0,
                "latencyP99Nanos": 30.0,
                "measuredLatencySamples": 100.0,
                "providerMetricsAfterWorkload": {
                    "hitRate": 0.95 if eligible else 0.0,
                    "currentEntries": 10000 if eligible else 0,
                },
                "providerMetricsAfterWriteProbe": {
                    "hitRate": 0.95 if eligible else 0.0,
                    "currentEntries": 10000 if eligible else 0,
                },
                "providerMetrics": {
                    "hitRate": 0.95 if eligible else 0.0,
                    "currentEntries": 10000 if eligible else 0,
                },
                "singleFlightPassed": eligible,
            }
            snapshot = {
                "heapUsedBytes": heap,
                "nativeCommittedBytes": heap * 2,
                "webappClassloaderCount": number,
                "liveThreadCount": 20 + number,
                "jcsThreadSignatures": [],
                "tomcatFindLeaksOccurrenceCount": 0,
                "tomcatFindLeaksOccurrenceCountsByContext": {},
            }
            early = {"jcsThreadSignatures": []}
            evidence = {"jcsThreadSignatures": []}
            return {
                "cycle": number,
                "requestSeed": 100 + number,
                "workload": workload,
                "redeployWorkload": dict(workload, operationsPerSecond=operations + 5),
                "protocolValidation": validation,
                "redeployProtocolValidation": validation,
                "afterUndeploy": snapshot,
                "afterFinalUndeploy": snapshot,
                "afterUndeployEarly": early,
                "afterFinalUndeployEarly": early,
                "firstUndeployThreadLeakWarnings": [],
                "secondUndeployThreadLeakWarnings": [],
                "firstUndeployThreadEvidenceEarly": evidence,
                "firstUndeployThreadEvidenceFinal": evidence,
                "finalUndeployThreadEvidenceEarly": evidence,
                "finalUndeployThreadEvidenceFinal": evidence,
                "redeployReady": True,
                "tomcatFindLeaksPassed": True,
            }

        def process_run(provider):
            return {
                "processRunId": f"run-{provider}",
                "provider": provider,
                "fork": 1,
                "block": 1,
                "orderPosition": 1,
                "cycles": [cycle(1, provider, 100.0, 1000),
                           cycle(2, provider, 200.0, 1200)],
                "threadLeakWarnings": [],
            }

        analysis = benchmark.analyse({
            "processRuns": [process_run("caffeine"), process_run("nostore")]
        })

        self.assertNotIn("winner", analysis)
        self.assertFalse(analysis["rankingProduced"])
        caffeine_primary = next(row for row in analysis["summaries"] if
            row["provider"] == "caffeine" and row["phase"] == "initial" and
            row["analysisSet"] == "primary-all-cycles")
        caffeine_sensitivity = next(row for row in analysis["summaries"] if
            row["provider"] == "caffeine" and row["phase"] == "initial" and
            row["analysisSet"] == "sensitivity-without-cycle-1")
        nostore_primary = next(row for row in analysis["summaries"] if
            row["provider"] == "nostore" and row["phase"] == "initial" and
            row["analysisSet"] == "primary-all-cycles")
        self.assertEqual(150.0, caffeine_primary["operationsPerSecondMedian"])
        self.assertEqual(200.0, caffeine_sensitivity["operationsPerSecondMedian"])
        self.assertEqual(0, nostore_primary["operationsPerSecondN"])
        self.assertFalse(nostore_primary["performanceComparisonEligible"])

    def test_infrastructure_failure_invalidates_whole_block(self):
        raw = {
            "executionPlan": [
                {"processRunId": "run-a", "scenario": "default", "block": 1},
                {"processRunId": "run-b", "scenario": "default", "block": 1},
            ],
            "processRuns": [
                {"processRunId": "run-a", "scenario": "default", "block": 1}
            ],
            "infrastructureFailures": [
                {
                    "processRunId": "run-b", "scenario": "default", "block": 1,
                    "message": "timeout",
                }
            ],
        }

        invalid = benchmark.detect_invalid_blocks(raw)

        self.assertEqual(1, len(invalid))
        self.assertEqual(("default", 1), (invalid[0]["scenario"], invalid[0]["block"]))
        self.assertEqual(
            {"infrastructure-failure", "missing-process-runs"},
            {reason["type"] for reason in invalid[0]["reasons"]},
        )


if __name__ == "__main__":
    unittest.main()

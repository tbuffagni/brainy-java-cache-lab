import unittest
from pathlib import Path
from unittest import mock

import extract_paper_v4_2 as extractor


def synthetic_runs(provider: str) -> list[dict]:
    runs = []
    observation = 0
    for fork in range(1, 7):
        cycles = []
        for cycle_number in range(1, 6):
            cycle = {
                "cycle": cycle_number,
                "redeployReady": not (fork == 6 and cycle_number == 5),
            }
            for phase, workload_key, validation_key in (
                ("initial", "workload", "protocolValidation"),
                ("redeploy", "redeployWorkload", "redeployProtocolValidation"),
            ):
                measurement_nanos = 5_000_000_000 + observation * 1_000_000
                operations = 400_000 + observation * 1_000
                hit_rate = 0.0 if provider == "nostore" else 0.949 + observation / 1_000_000
                population = 0 if provider == "nostore" else 9_900 + observation
                workload = {
                    "measurementNanos": measurement_nanos,
                    "measuredOperations": operations,
                    "providerMetricsAfterWorkload": {
                        "hitRate": hit_rate,
                        "currentEntries": population,
                    },
                    "providerMetricsAfterWriteProbe": {
                        "currentEntries": population + (0 if provider == "nostore" else 100),
                    },
                    "singleFlightPassed": provider != "nostore",
                }
                validation = {
                    "observedMeasurementNanos": measurement_nanos,
                    "passed": True,
                }
                if provider == "nostore":
                    validation["singleFlightGateApplicable"] = False
                else:
                    validation["singleFlightPassed"] = True
                cycle[workload_key] = workload
                cycle[validation_key] = validation
                observation += 1
            cycle["redeployPassed"] = (
                cycle["redeployReady"]
                and cycle["redeployProtocolValidation"]["passed"]
            )
            cycles.append(cycle)
        runs.append({"provider": provider, "fork": fork, "cycles": cycles})
    return runs


def cache_window_fixture() -> tuple[dict, dict, dict]:
    request = dict(extractor.EXPECTED_CONFIGURATION)
    after_workload = {"hitRate": 0.95, "currentEntries": 10_000}
    after_write = {"hitRate": 0.95, "currentEntries": 10_000}
    workload = {
        "configuration": request,
        "providerMetricsAfterWorkload": after_workload,
        "providerMetricsAfterWriteProbe": after_write,
        "providerMetrics": dict(after_write),
        "measuredOperations": 400_000,
        "operationsPerSecond": 80_000.0,
        "measurementNanos": 5_000_000_000,
        "measurementOvershootNanos": 0,
        "loaderInvocationsUnderContention": 1,
        "singleFlightPassed": True,
    }
    validation = {
        "gateType": "cache-semantics",
        "performanceComparisonEligible": True,
        "requiredOperations": 400_000,
        "measuredOperations": 400_000,
        "operationMeasurementsValid": True,
        "completedOperations": True,
        "providerMetricCheckpointsValid": True,
        "requestedMeasurementNanos": 5_000_000_000,
        "observedMeasurementNanos": 5_000_000_000,
        "measurementDurationPassed": True,
        "expectedHitRate": 0.95,
        "observedHitRate": 0.95,
        "hitRateWithinHalfPercentagePoint": True,
        "minimumExpectedEntriesAfterWorkload": 9_900,
        "observedEntriesAfterWorkload": 10_000,
        "capacityAfterWorkloadPassed": True,
        "minimumExpectedEntriesAfterWriteProbe": 9_900,
        "observedEntriesAfterWriteProbe": 10_000,
        "capacityAfterWriteProbePassed": True,
        "capacityCheckPassed": True,
        "singleFlightPassed": True,
        "passed": True,
    }
    return workload, validation, request


class ObservedSemanticEvidenceTest(unittest.TestCase):
    def test_cache_ranges_cover_all_raw_windows(self):
        evidence = extractor.extract_observed_semantic_evidence(
            synthetic_runs("caffeine"), "caffeine"
        )
        self.assertEqual(60, evidence["measurementDurationSeconds"]["n"])
        self.assertEqual(5.0, evidence["measurementDurationSeconds"]["minimum"])
        self.assertEqual(5.059, evidence["measurementDurationSeconds"]["maximum"])
        self.assertEqual(400_000, evidence["measuredOperations"]["minimum"])
        self.assertEqual(459_000, evidence["measuredOperations"]["maximum"])
        self.assertEqual(60, evidence["singleFlight"]["applicableWindows"])
        self.assertEqual(60, evidence["singleFlight"]["passedWindows"])
        self.assertEqual(30, evidence["redeployReady"]["applicableCycles"])
        self.assertEqual(29, evidence["redeployReady"]["passedCycles"])
        self.assertEqual("400.000–459.000",
                         evidence["formatted"]["measuredOperationsMinMax"])
        self.assertEqual("29/30",
                         evidence["formatted"]["redeployReadyPassedApplicable"])

    def test_no_store_single_flight_is_inapplicable_not_failed(self):
        evidence = extractor.extract_observed_semantic_evidence(
            synthetic_runs("nostore"), "nostore"
        )
        self.assertEqual(
            {
                "gateApplicable": False,
                "applicableWindows": 0,
                "passedWindows": None,
                "failedWindows": None,
                "allApplicableWindowsPassed": None,
            },
            evidence["singleFlight"],
        )
        self.assertEqual("non applicabile",
                         evidence["formatted"]["singleFlightPassedApplicable"])
        self.assertEqual("0,000–0,000",
                         evidence["formatted"]["hitRatePercentMinMax"])

    def test_raw_duration_must_match_validation_copy(self):
        runs = synthetic_runs("caffeine")
        runs[0]["cycles"][0]["protocolValidation"][
            "observedMeasurementNanos"
        ] += 1
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "duration differs from validation"):
            extractor.extract_observed_semantic_evidence(runs, "caffeine")


class WorkloadCheckpointValidationTest(unittest.TestCase):
    def test_duration_and_single_flight_raw_evidence_is_recomputed(self):
        workload, validation, request = cache_window_fixture()
        extractor.validate_workload_checkpoints(
            workload, validation, "caffeine", request, "fixture"
        )

        workload["measurementOvershootNanos"] = 1
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "measurement-duration evidence"):
            extractor.validate_workload_checkpoints(
                workload, validation, "caffeine", request, "fixture"
            )

        workload, validation, request = cache_window_fixture()
        workload["loaderInvocationsUnderContention"] = 2
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "single-flight result"):
            extractor.validate_workload_checkpoints(
                workload, validation, "caffeine", request, "fixture"
            )

    def test_exact_sixty_window_denominator_is_required(self):
        runs = synthetic_runs("caffeine")
        runs[0]["cycles"].pop()
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "expected 60 raw workload windows"):
            extractor.extract_observed_semantic_evidence(runs, "caffeine")


class OutputDestinationTest(unittest.TestCase):
    def test_output_must_differ_from_both_validated_inputs(self):
        results = Path("campaign-results.json").resolve()
        analysis = Path("campaign-analysis.json").resolve()
        output = Path("campaign-paper-values.json").resolve()

        extractor.validate_output_destination(results, analysis, output)
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "overwrite the definitive results"):
            extractor.validate_output_destination(results, analysis, results)
        with self.assertRaisesRegex(extractor.ExtractionError,
                                    "overwrite the definitive analysis"):
            extractor.validate_output_destination(results, analysis, analysis)

    def test_extract_still_assembles_the_complete_publication_document(self):
        raw = {"raw": True}
        analysis = {
            "lifecycleForks": [
                {"processRunId": "run-1", "blockValid": True},
                {"processRunId": "run-2", "blockValid": False},
            ]
        }
        campaign_id = "article1-unified-v4-2-fb3f101b-20260903-120000"
        quality = {"quality": True}
        with (
            mock.patch.object(extractor, "load_json_object",
                              side_effect=[raw, analysis]),
            mock.patch.object(extractor, "validate_inputs",
                              return_value=campaign_id),
            mock.patch.object(extractor, "extract_quality_control",
                              return_value=quality) as quality_call,
            mock.patch.object(extractor, "extract_primary_performance",
                              return_value={"primary": True}),
            mock.patch.object(extractor, "extract_paired_ratios",
                              return_value={"ratios": True}),
            mock.patch.object(extractor, "extract_sensitivity",
                              return_value=[{"sensitivity": True}]),
            mock.patch.object(extractor, "extract_lifecycle",
                              return_value={"lifecycle": True}),
            mock.patch.object(extractor, "extract_jcs248",
                              return_value={"jcs248": True}),
            mock.patch.object(
                extractor,
                "extract_environment_and_provenance",
                return_value={"environment": {}, "provenance": {}},
            ),
        ):
            document = extractor.extract(Path("results"), Path("analysis"))

        self.assertEqual(campaign_id, document["campaignId"])
        self.assertIs(quality, document["qualityControl"])
        self.assertIn("jcs248PositiveControl", document)
        quality_call.assert_called_once_with(raw, analysis, {"run-1"})


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from pathlib import Path

import fill_paper_v4_2 as filler


PROVIDERS = filler.PROVIDERS
PRIMARY_PROVIDERS = filler.PRIMARY_PROVIDERS
PHASES = filler.PHASES


def stats(base: float) -> dict:
    return {
        "n": 6,
        "median": base,
        "mean": base,
        "sampleStandardDeviation": 0.1,
        "firstQuartile": base - 0.25,
        "thirdQuartile": base + 0.25,
        "minimum": base - 0.5,
        "maximum": base + 0.5,
    }


def synthetic_paper_values() -> dict:
    quality_rows = []
    for position, provider in enumerate(PROVIDERS, start=1):
        duration_minimum = 5.0
        duration_maximum = 5.0 + position / 100.0
        operations_minimum = 400_000 + position * 1_000
        operations_maximum = 500_000 + position * 1_000
        hit_minimum = 0.0 if provider == "nostore" else 0.949 + position / 10_000.0
        hit_maximum = 0.0 if provider == "nostore" else 0.951 + position / 10_000.0
        population_minimum = 0 if provider == "nostore" else 9_900 + position
        population_maximum = 0 if provider == "nostore" else 10_000 + position
        single_flight_applicable = 0 if provider == "nostore" else 60
        single_flight_passed = 0 if provider == "nostore" else 60
        quality_rows.append({
            "provider": provider,
            "processesAcquired": 6,
            "validJvms": 6,
            "workloadWindowsAcquired": 60,
            "semanticGateWindowsPassed": 60,
            "performanceForkPhasePairsIncluded": 12 if provider in PRIMARY_PROVIDERS else 0,
            "observedSemanticEvidence": {
                "measurementDurationSeconds": {
                    "n": 60,
                    "minimum": duration_minimum,
                    "maximum": duration_maximum,
                },
                "measuredOperations": {
                    "n": 60,
                    "minimum": operations_minimum,
                    "maximum": operations_maximum,
                },
                "hitRate": {
                    "n": 60,
                    "minimum": hit_minimum,
                    "maximum": hit_maximum,
                },
                "entriesAfterWorkload": {
                    "n": 60,
                    "minimum": population_minimum,
                    "maximum": population_maximum,
                },
                "entriesAfterWriteProbe": {
                    "n": 60,
                    "minimum": population_minimum,
                    "maximum": population_maximum,
                },
                "singleFlight": {
                    "gateApplicable": provider != "nostore",
                    "applicableWindows": single_flight_applicable,
                    "passedWindows": (
                        single_flight_passed if provider != "nostore" else None
                    ),
                    "failedWindows": 0 if provider != "nostore" else None,
                    "allApplicableWindowsPassed": (
                        True if provider != "nostore" else None
                    ),
                },
                "redeployReady": {
                    "applicableCycles": 30,
                    "passedCycles": 30,
                },
                "formatted": {
                    "measurementDurationSecondsMinMax": filler.min_max_text(
                        duration_minimum, duration_maximum
                    ),
                    "measuredOperationsMinMax": filler.integer_min_max_text(
                        operations_minimum, operations_maximum
                    ),
                    "hitRatePercentMinMax": filler.min_max_text(
                        hit_minimum * 100.0, hit_maximum * 100.0
                    ),
                    "entriesAfterWorkloadMinMax": filler.integer_min_max_text(
                        population_minimum, population_maximum
                    ),
                    "entriesAfterWriteProbeMinMax": filler.integer_min_max_text(
                        population_minimum, population_maximum
                    ),
                    "singleFlightPassedApplicable": (
                        "non applicabile" if provider == "nostore" else "60/60"
                    ),
                    "redeployReadyPassedApplicable": "30/30",
                },
            },
        })

    throughput_rows = []
    latency_rows = []
    sensitivity_rows = []
    sequence = 0
    for provider in PRIMARY_PROVIDERS:
        for phase in PHASES:
            sequence += 1
            throughput_rows.append({
                "provider": provider,
                "phase": phase,
                "includedForks": 6,
                "formatted": {
                    "includedForks": "6/6",
                    "medianMops": f"{sequence},125",
                    "q1Q3Mops": f"{sequence},000–{sequence},250",
                    "minMaxMops": f"{sequence},000–{sequence},500",
                },
            })
            latency_rows.append({
                "provider": provider,
                "phase": phase,
                "includedForks": 6,
                "formatted": {
                    "includedForks": "6/6",
                    "p50MedianMicroseconds": f"{sequence},010",
                    "p95MedianMicroseconds": f"{sequence},020",
                    "p99MedianMicroseconds": f"{sequence},030",
                    "p99Q1Q3Microseconds": f"{sequence},025–{sequence},035",
                    "p99MinMaxMicroseconds": f"{sequence},020–{sequence},040",
                },
            })
            sensitivity_rows.append({
                "provider": provider,
                "phase": phase,
                "commonForkCount": 6,
                "formatted": {
                    "primaryMedianMops": f"{sequence},125",
                    "sensitivityMedianMops": f"{sequence},250",
                    "commonForkVariationPercent": "+1,25%",
                },
            })

    ratio_rows = []
    sequence = 0
    for provider in filler.RATIO_PROVIDERS:
        for phase in PHASES:
            sequence += 1
            ratio_rows.append({
                "provider": provider,
                "phase": phase,
                "ratio": stats(1.0 + sequence / 10.0),
                "formatted": {
                    "includedPairs": "6/6",
                    "median": f"{sequence},10×",
                    "q1Q3": f"{sequence},00–{sequence},20×",
                    "minMax": f"{sequence},00–{sequence},50×",
                },
            })

    lifecycle_rows = []
    lifecycle_stats = {}
    for position, provider in enumerate(PROVIDERS, start=1):
        if provider == "jcs321":
            warning_intervals, warning_jvms, warning_events = 42, 6, 42
        elif provider == "jcs4":
            warning_intervals, warning_jvms, warning_events = 0, 0, 0
        else:
            warning_intervals = position
            warning_jvms = min(position, 6)
            warning_events = position + 1
        provider_stats = {
            "thread": stats(position / 10.0),
            "classloader": stats(position / 20.0),
            "heap": stats(position / 30.0),
            "nmt": stats(position / 40.0),
        }
        lifecycle_stats[provider] = provider_stats
        lifecycle_rows.append({
            "provider": provider,
            "validLifecycleJvms": 6,
            "evaluableFindleaksIntervals": 60,
            "jvmsWithTargetContextInFindleaks": position % 3,
            "tomcatThreadLeak": {
                "evaluableIntervals": 60,
                "intervalsWithWarning": warning_intervals,
                "jvmsWithWarning": warning_jvms,
                "warningEvents": warning_events,
            },
            "formatted": {
                "cycle5ThreadDeltaMedianRange": f"+{position} [+{position - 1}–+{position + 1}]",
                "threadSlopeMedianRange": filler.median_range_text(provider_stats["thread"]),
                "classloaderSlopeMedianRange": filler.median_range_text(provider_stats["classloader"]),
                "heapSlopeMibMedianRange": filler.median_range_text(provider_stats["heap"]),
                "nmtSlopeMibMedianRange": filler.median_range_text(provider_stats["nmt"]),
            },
        })

    jcs_rows = []
    for provider, positive, corroborated in (("jcs321", 6, 42), ("jcs4", 0, 0)):
        provider_stats = lifecycle_stats[provider]
        jcs_rows.append({
            "provider": provider,
            "validJvms": 6,
            "evaluablePostUndeployIntervals": 60,
            "corroboratedIntervals": corroborated,
            "positiveJvms": positive,
            "threadLeakWarningIntervals": next(
                row["tomcatThreadLeak"]["intervalsWithWarning"]
                for row in lifecycle_rows if row["provider"] == provider
            ),
            "threadLeakWarningJvms": next(
                row["tomcatThreadLeak"]["jvmsWithWarning"]
                for row in lifecycle_rows if row["provider"] == provider
            ),
            "threadLeakWarningEvents": next(
                row["tomcatThreadLeak"]["warningEvents"]
                for row in lifecycle_rows if row["provider"] == provider
            ),
            "jvmsWithTargetContextInFindleaks": next(
                row["jvmsWithTargetContextInFindleaks"]
                for row in lifecycle_rows if row["provider"] == provider
            ),
            "prespecifiedPositiveControlCriterionApplies": provider == "jcs321",
            "prespecifiedPositiveControlCriterionMet": (
                positive >= 5 if provider == "jcs321" else None
            ),
            "sameThresholdMetObservationally": positive >= 5,
            "lifecycleSlopes": {
                "threadPerCycle": provider_stats["thread"],
                "classloaderPerCycle": provider_stats["classloader"],
                "heapMebibytesPerCycle": provider_stats["heap"],
                "nativeCommittedMebibytesPerCycle": provider_stats["nmt"],
            },
        })

    return {
        "schemaVersion": 1,
        "campaignId": "article1-unified-v4-2-fb3f101b-20260903-120000",
        "protocolVersion": "4.2",
        "datasetStatus": "complete-and-accepted",
        "qualityControl": {
            "protocolDeviationAssessment": {
                "allMachineVerifiableControlsPassed": True,
                "statement": filler.NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT,
            },
            "denominatorDefinition": {
                "processesPerProvider": 6,
                "workloadWindowsPerProvider": 60,
                "forkPhasePairsPerProvider": 12,
                "cyclesTotal": 180,
                "workloadWindowsTotal": 360,
                "processesTotal": 36,
            },
            "byProvider": quality_rows,
            "williamsBlocks": {
                "completeAtFirstAttemptWithinDataset": 6,
                "invalidated": 0,
                "repeatedWithinDataset": 0,
                "distinctContainerIds": 36,
            },
        },
        "primaryPerformance": {
            "throughput": throughput_rows,
            "sampledLatency": latency_rows,
        },
        "pairedThroughputRatios": {"primary": ratio_rows},
        "sensitivityWithoutCycle1": sensitivity_rows,
        "lifecycle": {
            "timingEvidence": {"intervals": 360},
            "byProvider": lifecycle_rows,
        },
        "jcs248PositiveControl": {"byJcsLine": jcs_rows},
        "provenance": {
            "protocol": {
                "path": filler.EXPECTED_PROTOCOL_PATH,
                "sha256": filler.EXPECTED_PROTOCOL_SHA256,
            },
        },
    }


class FormattingTest(unittest.TestCase):
    def test_italian_number_rounding_and_decimal_separator(self):
        self.assertEqual("12,346", filler.italian_number(12.3456))
        self.assertEqual("-0,50", filler.italian_number(-0.5, 2, signed=True))

    def test_smart_signed_number_removes_only_fractional_zeroes(self):
        self.assertEqual("+2", filler.italian_smart_number(2.0, signed=True))
        self.assertEqual("+0,125", filler.italian_smart_number(0.125, signed=True))

    def test_median_range_matches_paper_notation(self):
        value = {"median": 0.5, "minimum": -1.0, "maximum": 2.0}
        self.assertEqual("+0,5 [-1–+2]", filler.median_range_text(value))

    def test_integer_ranges_use_italian_grouping(self):
        self.assertEqual("400.000–12.345.678",
                         filler.integer_min_max_text(400_000, 12_345_678))

    def test_required_suffix_is_removed_once(self):
        self.assertEqual("1,25", filler.remove_required_suffix("1,25×", "×", "ratio"))
        with self.assertRaisesRegex(filler.FillError, "must end"):
            filler.remove_required_suffix("1,25", "×", "ratio")


class MappingTest(unittest.TestCase):
    def test_mapping_covers_every_current_paper_placeholder(self):
        replacements = filler.build_replacements(synthetic_paper_values())
        paper = (Path(__file__).resolve().parents[1] / "press" / "article"
                 / "beyond-throughput-tomcat-lifecycle.md").read_text(encoding="utf-8-sig")
        placeholders = set(filler.PLACEHOLDER_RE.findall(paper))

        self.assertEqual(filler.EXPECTED_PLACEHOLDER_COUNT, len(replacements))
        self.assertEqual(placeholders, set(replacements))
        self.assertIn("180/180 cicli",
                      replacements["V42_CONCLUSION_COMPLETION_AND_GATES"])
        self.assertEqual("1,10", replacements["V42_CAFFEINE_INITIAL_RATIO_MEDIAN"])
        self.assertEqual("+1,25", replacements["V42_CAFFEINE_INITIAL_SENSITIVITY_DELTA"])
        self.assertEqual(
            filler.NO_MACHINE_VERIFIABLE_DEVIATIONS_STATEMENT,
            replacements["V42_PROTOCOL_DEVIATIONS"],
        )
        self.assertEqual("401.000–501.000",
                         replacements["V42_CAFFEINE_RQ1_OPERATIONS_RANGE"])
        self.assertEqual("non applicabile",
                         replacements["V42_NOSTORE_RQ1_SINGLE_FLIGHT"])
        self.assertIn("300/300 finestre", replacements["V42_RQ1_ANSWER"])
        self.assertIn("non la latenza HTTP",
                      replacements["V42_RQ2_ANSWER"])
        self.assertIn("non dimostrano da soli un leak",
                      replacements["V42_RQ3_ANSWER"])
        self.assertIn("coerente con la risoluzione",
                      replacements["V42_JCS248_INTERPRETATION"])
        self.assertNotIn("×", replacements["V42_CAFFEINE_INITIAL_RATIO_MEDIAN"])
        self.assertNotIn("%", replacements["V42_CAFFEINE_INITIAL_SENSITIVITY_DELTA"])

        filled = filler.fill_template(paper, replacements)
        self.assertFalse(filler.PLACEHOLDER_RE.search(filled))
        self.assertIn("6/6 repliche", filled)

    def test_protocol_deviation_assessment_is_fail_closed(self):
        values = synthetic_paper_values()
        values["qualityControl"]["protocolDeviationAssessment"][
            "allMachineVerifiableControlsPassed"
        ] = False
        with self.assertRaisesRegex(filler.FillError,
                                    "machine-verifiable v4.2 controls"):
            filler.build_replacements(values)

        values = synthetic_paper_values()
        values["qualityControl"]["protocolDeviationAssessment"]["statement"] = (
            "Nessuna deviazione"
        )
        with self.assertRaisesRegex(filler.FillError, "prudent frozen wording"):
            filler.build_replacements(values)

    def test_rq1_evidence_must_be_complete_and_self_consistent(self):
        values = synthetic_paper_values()
        evidence = values["qualityControl"]["byProvider"][0][
            "observedSemanticEvidence"
        ]
        evidence["measurementDurationSeconds"]["n"] = 59
        with self.assertRaisesRegex(filler.FillError, "all 60 windows"):
            filler.build_replacements(values)

        values = synthetic_paper_values()
        evidence = values["qualityControl"]["byProvider"][0][
            "observedSemanticEvidence"
        ]
        evidence["formatted"]["measuredOperationsMinMax"] = "dato inventato"
        with self.assertRaisesRegex(filler.FillError, "disagrees with raw bounds"):
            filler.build_replacements(values)

    def test_jcs248_narrative_handles_inconsistent_jcs321_reproduction(self):
        values = synthetic_paper_values()
        jcs321 = next(row for row in values["jcs248PositiveControl"]["byJcsLine"]
                      if row["provider"] == "jcs321")
        jcs321["positiveJvms"] = 4
        jcs321["corroboratedIntervals"] = 12
        jcs321["prespecifiedPositiveControlCriterionMet"] = False
        jcs321["sameThresholdMetObservationally"] = False
        replacements = filler.build_replacements(values)
        self.assertIn("non è stato quindi riprodotto con sufficiente consistenza",
                      replacements["V42_JCS248_INTERPRETATION"])

    def test_jcs248_narrative_reports_residual_pattern_without_leak_claim(self):
        values = synthetic_paper_values()
        jcs4 = next(row for row in values["jcs248PositiveControl"]["byJcsLine"]
                    if row["provider"] == "jcs4")
        lifecycle_jcs4 = next(
            row for row in values["lifecycle"]["byProvider"]
            if row["provider"] == "jcs4"
        )
        jcs4["positiveJvms"] = 1
        jcs4["corroboratedIntervals"] = 2
        jcs4["threadLeakWarningIntervals"] = 2
        jcs4["threadLeakWarningJvms"] = 1
        jcs4["threadLeakWarningEvents"] = 2
        lifecycle_jcs4["tomcatThreadLeak"].update({
            "intervalsWithWarning": 2,
            "jvmsWithWarning": 1,
            "warningEvents": 2,
        })
        replacements = filler.build_replacements(values)
        text = replacements["V42_JCS248_INTERPRETATION"]
        self.assertIn("pattern resta osservabile", text)
        self.assertIn("non dimostra da solo un memory leak", text)

    def test_v4_1_metadata_is_rejected(self):
        values = synthetic_paper_values()
        values["protocolVersion"] = "4.1"
        values["campaignId"] = "article1-unified-v4-1-fb3f101b-20260903-120000"
        with self.assertRaisesRegex(filler.FillError, "v4.1 is not accepted"):
            filler.build_replacements(values)

    def test_missing_formatted_source_value_is_not_guessed(self):
        values = synthetic_paper_values()
        del values["primaryPerformance"]["throughput"][0]["formatted"]["medianMops"]
        with self.assertRaisesRegex(filler.FillError, "missing source value"):
            filler.build_replacements(values)

    def test_observed_cycle_derivation_must_match_declared_denominator(self):
        values = synthetic_paper_values()
        values["lifecycle"]["timingEvidence"]["intervals"] = 358
        with self.assertRaisesRegex(filler.FillError, "do not cover every declared"):
            filler.build_replacements(values)

    def test_jcs_slope_must_agree_with_lifecycle_table(self):
        values = synthetic_paper_values()
        row = next(item for item in values["lifecycle"]["byProvider"]
                   if item["provider"] == "jcs321")
        row["formatted"]["threadSlopeMedianRange"] = "+999 [+999–+999]"
        with self.assertRaisesRegex(filler.FillError, "formatting disagree"):
            filler.build_replacements(values)

    def test_incomplete_template_is_rejected(self):
        replacements = filler.build_replacements(synthetic_paper_values())
        one_marker = "{{V42_CONCLUSION_COMPLETION_AND_GATES}}"
        with self.assertRaisesRegex(filler.FillError, "paper contains 1 distinct"):
            filler.fill_template(one_marker, replacements)

    def test_fixture_is_not_mutated(self):
        values = synthetic_paper_values()
        before = copy.deepcopy(values)
        filler.build_replacements(values)
        self.assertEqual(before, values)


if __name__ == "__main__":
    unittest.main()

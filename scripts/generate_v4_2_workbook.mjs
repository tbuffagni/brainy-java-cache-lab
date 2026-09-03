#!/usr/bin/env node

/**
 * Generate the protocol-v4.2 scientific workbook (JSON schemaVersion 4) for the Tomcat cache benchmark.
 *
 * Usage:
 *   node scripts/generate_v4_2_workbook.mjs [--prefix <campaign-id>] \
 *     [--input-dir press/results/raw] [--render-dir <directory>]
 *
 * If --prefix is omitted, exactly one complete
 * article1-unified-v4-2-fb3f101b-<YYYYMMDD-HHMMSS> triple must exist in
 * the input directory: results, analysis, and paper-values JSON.
 *
 * The script intentionally does not invoke mark_artifact_operation_started.mjs.
 * The caller must run the required marker exactly once immediately before the
 * first workbook-authoring execution.
 */

import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "..");
const DEFAULT_INPUT_DIR = path.join(PROJECT_ROOT, "press", "results", "raw");
const OUTPUT_PATH = path.join(
  PROJECT_ROOT,
  "outputs",
  "01a020f0-ef86-7200-9deb-cc123c0bfab7",
  "Beyond_Throughput_Lifecycle_v4_2_Results.xlsx",
);
const DEFAULT_RENDER_DIR = path.join(
  PROJECT_ROOT,
  "outputs",
  "01a020f0-ef86-7200-9deb-cc123c0bfab7",
  "workbook-render-v4-2",
);
const CAMPAIGN_ID_PATTERN = /^article1-unified-v4-2-fb3f101b-\d{8}-\d{6}$/;
const EXPECTED_PROTOCOL_PATH = "press/article/protocollo-campagna-v4-2.md";
const EXPECTED_PROTOCOL_SHA256 = "4f364de62f696c687d3175931f29c69013f4ad9d96303558e2444bfc5c73596f";

const SHEET_NAMES = [
  "Readme-Protocol",
  "Runs",
  "Workloads Raw",
  "Snapshots Raw",
  "Thread Evidence",
  "Events-Warnings",
  "QC Gates",
  "Performance",
  "Lifecycle",
  "JCS-248",
  "Figures",
  "Dictionary",
];

const COLORS = {
  navy: "#17324D",
  teal: "#176B73",
  blue: "#2B6F9E",
  paleBlue: "#EAF1F5",
  paleTeal: "#E7F1F1",
  paper: "#FAFBFC",
  ink: "#24313D",
  muted: "#5C6B77",
  line: "#CCD6DE",
  amber: "#B7791F",
  paleAmber: "#FFF4D6",
  red: "#A63D40",
  paleRed: "#FBE9EA",
  green: "#2F6B4F",
  paleGreen: "#E7F3EC",
  white: "#FFFFFF",
};

const SOURCE_RESULTS = "results.json";
const SOURCE_ANALYSIS = "analysis.json";
const SOURCE_PAPER_VALUES = "paper-values.json";
const SOURCE_FORMULA = "Formula workbook";
const PROTOCOL_VERSION = "4.2 (JSON schemaVersion 4)";
const CANONICAL_PROVIDERS = ["caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore"];
const PRIMARY_PERFORMANCE_PROVIDERS = new Set(["caffeine", "ehcache", "cache2k", "jcs4"]);
const HEX40 = /^[0-9a-f]{40}$/i;
const HEX64 = /^[0-9a-f]{64}$/i;
const PINNED_DIGEST = /^sha256:[0-9a-f]{64}$/i;
const HIT_RATE_TOLERANCE = 0.005;
const CONFIGURED_OPERATIONS = 400_000;
const WILLIAMS_ROWS = Object.freeze([
  ["caffeine", "ehcache", "nostore", "cache2k", "jcs321", "jcs4"],
  ["ehcache", "cache2k", "caffeine", "jcs4", "nostore", "jcs321"],
  ["cache2k", "jcs4", "ehcache", "jcs321", "caffeine", "nostore"],
  ["jcs4", "jcs321", "cache2k", "nostore", "ehcache", "caffeine"],
  ["jcs321", "nostore", "jcs4", "caffeine", "cache2k", "ehcache"],
  ["nostore", "caffeine", "jcs321", "ehcache", "jcs4", "cache2k"],
]);
const EXPECTED_COUNTS = Object.freeze({
  processRuns: 36,
  cycles: 180,
  workloadWindows: 360,
  observations: 360,
  forks: 144,
  lifecycleForks: 36,
  summaries: 24,
  lifecycleSummaries: 6,
  pairedRatios: 12,
});

const PRESPECIFIED_PROVIDER_VERSIONS = Object.freeze({
  caffeine: { version: "3.2.4", evidence: "Protocollo v4.2; verificabile nell'effective POM quando presente nell'archivio" },
  ehcache: { version: "3.12.0", evidence: "Protocollo v4.2; verificabile nell'effective POM quando presente nell'archivio" },
  cache2k: { version: "2.6.1.Final", evidence: "Protocollo v4.2; verificabile nell'effective POM quando presente nell'archivio" },
  jcs4: { version: "4.0.0-SNAPSHOT", evidence: "Protocollo v4.2; valore runtime in environment.jcs4Version" },
  jcs321: { version: "3.2.1", evidence: "Protocollo v4.2; valore runtime in environment.jcs321Version" },
  nostore: { version: null, evidence: "Non applicabile: controllo senza motore di cache" },
});

function usage() {
  return [
    "Usage:",
    "  node scripts/generate_v4_2_workbook.mjs [--prefix <campaign-id>]",
    "       [--input-dir <directory>] [--render-dir <directory>]",
    "",
    "The campaign id may also be supplied as the sole positional argument.",
    `Output is fixed at: ${OUTPUT_PATH}`,
  ].join("\n");
}

function parseArgs(argv) {
  const values = {};
  const positional = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }
    const [rawKey, inlineValue] = arg.slice(2).split("=", 2);
    const key = rawKey === "render" ? "render-dir" : rawKey;
    if (!new Set(["prefix", "input-dir", "render-dir"]).has(key)) {
      throw new Error(`Unknown argument --${rawKey}\n${usage()}`);
    }
    const value = inlineValue ?? argv[++index];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${rawKey}\n${usage()}`);
    }
    values[key] = value;
  }
  if (positional.length > 1) throw new Error(`Only one positional campaign prefix is accepted\n${usage()}`);
  values.prefix ??= positional[0];
  return {
    prefix: values.prefix ?? null,
    inputDir: path.resolve(values["input-dir"] ?? DEFAULT_INPUT_DIR),
    outputPath: OUTPUT_PATH,
    renderDir: path.resolve(values["render-dir"] ?? DEFAULT_RENDER_DIR),
  };
}

function stripCampaignSuffix(value) {
  return value.replace(/-(?:results|analysis|paper-values)\.json$/i, "");
}

async function resolveCampaignFiles(options) {
  let inputDir = options.inputDir;
  let campaignId = null;
  if (options.prefix) {
    const stripped = stripCampaignSuffix(options.prefix);
    const hasDirectory = path.dirname(stripped) !== ".";
    if (hasDirectory) {
      const resolvedPrefix = path.resolve(stripped);
      inputDir = path.dirname(resolvedPrefix);
      campaignId = path.basename(resolvedPrefix);
    } else {
      campaignId = stripped;
    }
    assert(CAMPAIGN_ID_PATTERN.test(campaignId), `Invalid v4.2 campaign prefix: ${campaignId}`);
  } else {
    const entries = await fs.readdir(inputDir);
    const entrySet = new Set(entries);
    const candidates = entries
      .filter((name) => name.endsWith("-results.json"))
      .map((name) => stripCampaignSuffix(name))
      .filter((name) => CAMPAIGN_ID_PATTERN.test(name))
      .filter((name) => ["results", "analysis", "paper-values"]
        .every((kind) => entrySet.has(`${name}-${kind}.json`)));
    const uniqueCandidates = [...new Set(candidates)];
    assert(uniqueCandidates.length === 1,
      `Expected exactly one complete v4.2 campaign in ${inputDir}, found ${uniqueCandidates.length}: ${uniqueCandidates.join(", ") || "none"}`);
    [campaignId] = uniqueCandidates;
  }
  const files = {
    campaignId,
    rawPath: path.join(inputDir, `${campaignId}-results.json`),
    analysisPath: path.join(inputDir, `${campaignId}-analysis.json`),
    paperValuesPath: path.join(inputDir, `${campaignId}-paper-values.json`),
    outputPath: options.outputPath,
    renderDir: options.renderDir,
  };
  await Promise.all([
    fs.access(files.rawPath),
    fs.access(files.analysisPath),
    fs.access(files.paperValuesPath),
  ]);
  return files;
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function parseJson(buffer, label) {
  try {
    return JSON.parse(buffer.toString("utf8").replace(/^\uFEFF/, ""));
  } catch (error) {
    throw new Error(`Invalid JSON in ${label}: ${error.message}`);
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function isRecord(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function isNonnegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function requireText(value, label) {
  assert(typeof value === "string" && value.trim().length > 0, `${label} is required`);
  return value;
}

function assertSha256(value, label) {
  assert(typeof value === "string" && HEX64.test(value), `${label} must be a 64-character SHA-256`);
}

function sameNumber(left, right, tolerance = 1e-12) {
  return typeof left === "number"
    && Number.isFinite(left)
    && typeof right === "number"
    && Number.isFinite(right)
    && Math.abs(left - right) <= tolerance * Math.max(1, Math.abs(left), Math.abs(right));
}

function displayPath(filePath) {
  const relative = path.relative(process.cwd(), filePath);
  if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) {
    return relative.split(path.sep).join("/");
  }
  return path.basename(filePath);
}

function artifactFileName(value) {
  if (typeof value !== "string" || !value) return null;
  return value.replaceAll("\\", "/").split("/").at(-1) || null;
}

function artifactByName(environment, filename) {
  return asArray(environment?.archivedBuildFiles).find((item) => item?.file === filename) ?? null;
}

function validateArtifactMetadata(item, label) {
  assert(isRecord(item), `${label} metadata is required`);
  requireText(item.file, `${label}.file`);
  assertSha256(item.sha256, `${label}.sha256`);
  assert(Number.isInteger(item.sizeBytes) && item.sizeBytes >= 0, `${label}.sizeBytes must be a non-negative integer`);
}

function validateBaseImage(image, label) {
  assert(isRecord(image), `${label} metadata is required`);
  const digest = requireText(image.pinnedDigest, `${label}.pinnedDigest`);
  assert(PINNED_DIGEST.test(digest), `${label}.pinnedDigest must be immutable`);
  const reference = requireText(image.reference, `${label}.reference`);
  assert(reference.toLowerCase().endsWith(`@${digest.toLowerCase()}`), `${label}.reference must include pinnedDigest`);
  assert(image.inspectionAvailable === true, `${label}.inspectionAvailable must be true for the final campaign`);
}

function validateEnvironment(environment, runId) {
  const requiredFields = [
    "dockerImageId", "containerImageName", "containerOS", "javaOptions",
    "JVM Version", "JVM Vendor", "OS Name", "OS Version", "OS Architecture",
    "containerCpuModel", "containerKernel",
    "dockerServerVersion", "dockerServerOperatingSystem", "dockerServerKernelVersion",
    "dockerServerArchitecture", "dockerServerName", "jvmCommandLine", "jvmFlags",
  ];
  assert(isRecord(environment), `${runId}: environment is required`);
  for (const field of requiredFields) requireText(environment[field], `${runId}: environment.${field}`);
  assert(typeof environment.containerCpuLimit === "number" && environment.containerCpuLimit > 0, `${runId}: positive CPU limit is required`);
  assert(Number.isInteger(environment.containerMemoryLimitBytes) && environment.containerMemoryLimitBytes > 0, `${runId}: positive memory limit is required`);
  assert(Number(environment.containerVisibleProcessors) > 0, `${runId}: visible processor count must be positive`);
  assert(typeof environment.containerId === "string" && HEX64.test(environment.containerId), `${runId}: full containerId is required`);
  validateBaseImage(environment.runtimeBaseImage, `${runId}: runtimeBaseImage`);
  validateBaseImage(environment.buildBaseImage, `${runId}: buildBaseImage`);
  assert(typeof environment.jcs4SourceCommit === "string" && HEX40.test(environment.jcs4SourceCommit), `${runId}: exact JCS4 source commit is required`);
  assert(environment.imageJcs4RevisionLabel === environment.jcs4SourceCommit, `${runId}: JCS4 image revision label differs from source commit`);
  for (const field of ["warSha256", "jcs4ArtifactSha256", "jcs321ArtifactSha256"]) {
    assertSha256(environment[field], `${runId}: environment.${field}`);
  }
  requireText(environment.jcs4Version, `${runId}: environment.jcs4Version`);
  requireText(environment.jcs321Version, `${runId}: environment.jcs321Version`);
  assert(environment.jcs4Version === PRESPECIFIED_PROVIDER_VERSIONS.jcs4.version, `${runId}: JCS4 runtime version differs from the prespecified version`);
  assert(environment.jcs321Version === PRESPECIFIED_PROVIDER_VERSIONS.jcs321.version, `${runId}: JCS 3 runtime version differs from the prespecified version`);
  assert(environment.provenanceValidationPassed === true, `${runId}: provenance validation must pass`);
  assert(asArray(environment.provenanceValidationErrors).length === 0, `${runId}: provenance validation errors are present`);
  const manifest = asArray(environment.artifactManifest);
  assert(manifest.length >= 3, `${runId}: artifact manifest must include the WAR and both JCS JARs`);
  for (const [index, item] of manifest.entries()) {
    assert(isRecord(item), `${runId}: artifactManifest[${index}] must be an object`);
    requireText(item.containerPath, `${runId}: artifactManifest[${index}].containerPath`);
    assertSha256(item.sha256, `${runId}: artifactManifest[${index}].sha256`);
  }
  assert(manifest.some((item) => item.containerPath.endsWith(".war")), `${runId}: WAR missing from artifact manifest`);
  assert(manifest.filter((item) => item.containerPath.endsWith(".jar")).length >= 2, `${runId}: both JCS JARs must be in artifact manifest`);
  for (const [index, item] of asArray(environment.archivedBuildFiles).entries()) {
    validateArtifactMetadata(item, `${runId}: archivedBuildFiles[${index}]`);
  }
}

function validateDiagnosticSnapshots(run, cycle) {
  const label = `${run.processRunId} C${cycle.cycle}`;
  for (const key of ["baseline", "deployedIdle", "loaded", "afterUndeployEarly", "afterUndeploy", "redeployedLoaded", "afterFinalUndeployEarly", "afterFinalUndeploy"]) {
    requireText(cycle[key]?.label, `${label}: ${key}.label`);
  }
  for (const key of ["afterUndeployEarly", "afterFinalUndeployEarly"]) {
    const artifacts = cycle[key]?.diagnosticArtifacts;
    requireText(artifacts?.threadDump, `${label}: ${key}.diagnosticArtifacts.threadDump`);
    requireText(artifacts?.tomcatLog, `${label}: ${key}.diagnosticArtifacts.tomcatLog`);
  }
  for (const key of ["afterUndeploy", "afterFinalUndeploy"]) {
    const artifacts = cycle[key]?.diagnosticArtifacts;
    for (const artifact of ["heapInfo", "classloaderStats", "threadDump", "nativeMemory", "classHistogram", "tomcatFindLeaks"]) {
      requireText(artifacts?.[artifact], `${label}: ${key}.diagnosticArtifacts.${artifact}`);
    }
  }
}

const POST_UNDEPLOY_TIMING_FIELDS = Object.freeze([
  "earlyThreadSecondsAfterUndeploy",
  "finalMeasurementSecondsAfterUndeploy",
  "earlyThreadTargetSecondsAfterUndeploy",
  "finalDiagnosticTargetSecondsAfterUndeploy",
  "earlyThreadStartedSecondsAfterUndeploy",
  "earlyThreadCompletedSecondsAfterUndeploy",
  "finalDiagnosticStartedSecondsAfterUndeploy",
  "findLeaksCompletedSecondsAfterUndeploy",
  "finalSnapshotCompletedSecondsAfterUndeploy",
]);

const ANALYSIS_TIMING_FIELDS = Object.freeze(POST_UNDEPLOY_TIMING_FIELDS.slice(2));

function validatePostUndeployTiming(timing, protocol, label) {
  assert(isRecord(timing), `${label}: timing evidence is required`);
  for (const field of POST_UNDEPLOY_TIMING_FIELDS) {
    assert(isFiniteNumber(timing[field]) && timing[field] >= 0,
      `${label}.${field} must be a non-negative monotonic elapsed time`);
  }
  const earlyTarget = protocol.earlyThreadObservationSeconds;
  const finalTarget = protocol.finalObservationAndFindleaksSeconds;
  assert(sameNumber(timing.earlyThreadSecondsAfterUndeploy, earlyTarget)
    && sameNumber(timing.earlyThreadTargetSecondsAfterUndeploy, earlyTarget),
  `${label}: early timing targets differ from lifecycleProtocol`);
  assert(sameNumber(timing.finalMeasurementSecondsAfterUndeploy, finalTarget)
    && sameNumber(timing.finalDiagnosticTargetSecondsAfterUndeploy, finalTarget),
  `${label}: final timing targets differ from lifecycleProtocol`);
  assert(timing.earlyThreadStartedSecondsAfterUndeploy >= timing.earlyThreadTargetSecondsAfterUndeploy,
    `${label}: early diagnostic collection started before its target`);
  assert(timing.earlyThreadCompletedSecondsAfterUndeploy >= timing.earlyThreadStartedSecondsAfterUndeploy,
    `${label}: early diagnostic collection completed before it started`);
  assert(timing.finalDiagnosticStartedSecondsAfterUndeploy >= timing.finalDiagnosticTargetSecondsAfterUndeploy
    && timing.finalDiagnosticStartedSecondsAfterUndeploy >= timing.earlyThreadCompletedSecondsAfterUndeploy,
  `${label}: final diagnostics started before their lower bounds`);
  assert(timing.findLeaksCompletedSecondsAfterUndeploy >= timing.finalDiagnosticStartedSecondsAfterUndeploy,
    `${label}: findleaks completed before final diagnostics started`);
  assert(timing.finalSnapshotCompletedSecondsAfterUndeploy >= timing.findLeaksCompletedSecondsAfterUndeploy,
    `${label}: final snapshot completed before findleaks`);
}

function assertGateEquality(errors, actual, expected, label) {
  if (actual !== expected) errors.push(`${label}: runner=${String(actual)}, recomputed=${String(expected)}`);
}

function validateNumericalQualityGates(raw) {
  const errors = [];
  for (const run of asArray(raw.processRuns)) {
    for (const cycle of asArray(run.cycles)) {
      for (const [phase, workloadKey, gateKey] of [
        ["initial", "workload", "protocolValidation"],
        ["redeploy", "redeployWorkload", "redeployProtocolValidation"],
      ]) {
        const workload = cycle[workloadKey] ?? {};
        const gate = cycle[gateKey] ?? {};
        const configuration = workload.configuration ?? cycle.request ?? run.configuration ?? raw.configuration ?? {};
        const metricsAfterWorkload = workload.providerMetricsAfterWorkload;
        const metricsAfterWriteProbe = workload.providerMetricsAfterWriteProbe;
        const legacyMetrics = workload.providerMetrics;
        const prefix = `${run.processRunId} C${cycle.cycle} ${phase}`;
        const checkpointAfterWorkloadValid = isRecord(metricsAfterWorkload)
          && isNonnegativeInteger(metricsAfterWorkload.currentEntries)
          && isFiniteNumber(metricsAfterWorkload.hitRate)
          && metricsAfterWorkload.hitRate >= 0
          && metricsAfterWorkload.hitRate <= 1;
        const checkpointAfterWriteProbeValid = isRecord(metricsAfterWriteProbe)
          && isNonnegativeInteger(metricsAfterWriteProbe.currentEntries);
        const metricCheckpointsValid = checkpointAfterWorkloadValid && checkpointAfterWriteProbeValid;
        if (JSON.stringify(legacyMetrics) !== JSON.stringify(metricsAfterWriteProbe)) {
          errors.push(`${prefix}: providerMetrics is not the post-write compatibility alias`);
        }
        const requestedOperations = configuration.operations;
        const measuredOperations = workload.measuredOperations;
        const operationsPerSecond = workload.operationsPerSecond;
        const operationMeasurementsValid = isNonnegativeInteger(requestedOperations)
          && requestedOperations > 0
          && isNonnegativeInteger(measuredOperations)
          && isFiniteNumber(operationsPerSecond)
          && operationsPerSecond > 0;
        const requestedNanos = Number(configuration.measurementSeconds) * 1_000_000_000;
        const observedNanos = Number(workload.measurementNanos);
        const completed = operationMeasurementsValid && measuredOperations >= requestedOperations;
        const durationPassed = requestedNanos === 0 || observedNanos >= requestedNanos;

        if (gate.requiredOperations !== requestedOperations) errors.push(`${prefix}: requiredOperations differs between request and gate`);
        if (gate.measuredOperations !== measuredOperations) errors.push(`${prefix}: measuredOperations differs between workload and gate`);
        assertGateEquality(errors, gate.operationMeasurementsValid, operationMeasurementsValid, `${prefix} operation-measurement validity`);
        assertGateEquality(errors, gate.providerMetricCheckpointsValid, metricCheckpointsValid, `${prefix} metric-checkpoint validity`);
        if (!sameNumber(Number(gate.requestedMeasurementNanos), requestedNanos)) errors.push(`${prefix}: requested duration differs between configuration and gate`);
        if (!sameNumber(Number(gate.observedMeasurementNanos), observedNanos)) errors.push(`${prefix}: observed duration differs between workload and gate`);
        assertGateEquality(errors, gate.completedOperations, completed, `${prefix} completed-operations gate`);
        assertGateEquality(errors, gate.measurementDurationPassed, durationPassed, `${prefix} duration gate`);

        let recomputedPassed;
        if (run.provider === "nostore") {
          const emptyAfterWorkload = checkpointAfterWorkloadValid && metricsAfterWorkload.currentEntries === 0;
          const emptyAfterWriteProbe = checkpointAfterWriteProbeValid && metricsAfterWriteProbe.currentEntries === 0;
          const noEntries = emptyAfterWorkload && emptyAfterWriteProbe;
          const zeroHits = checkpointAfterWorkloadValid && metricsAfterWorkload.hitRate === 0;
          if (gate.observedEntriesAfterWorkload !== (checkpointAfterWorkloadValid ? metricsAfterWorkload.currentEntries : 0)) errors.push(`${prefix}: no-store post-workload capacity differs`);
          if (gate.observedEntriesAfterWriteProbe !== (checkpointAfterWriteProbeValid ? metricsAfterWriteProbe.currentEntries : 0)) errors.push(`${prefix}: no-store post-write capacity differs`);
          assertGateEquality(errors, gate.capacityAfterWorkloadPassed, emptyAfterWorkload, `${prefix} no-store post-workload capacity gate`);
          assertGateEquality(errors, gate.capacityAfterWriteProbePassed, emptyAfterWriteProbe, `${prefix} no-store post-write capacity gate`);
          assertGateEquality(errors, gate.capacityCheckPassed, noEntries, `${prefix} no-store aggregate capacity gate`);
          assertGateEquality(errors, gate.noEntriesRetained, noEntries, `${prefix} no-store capacity gate`);
          assertGateEquality(errors, gate.zeroHits, zeroHits, `${prefix} no-store hit gate`);
          recomputedPassed = completed && durationPassed && metricCheckpointsValid && noEntries && zeroHits;
        } else {
          const expectedHitRate = Number(configuration.hitPercent) / 100;
          const observedHitRate = checkpointAfterWorkloadValid ? metricsAfterWorkload.hitRate : 0;
          const hitRatePassed = configuration.workload !== "uniform"
            || Math.abs(observedHitRate - expectedHitRate) <= HIT_RATE_TOLERANCE;
          const minimumEntries = Math.floor(Number(configuration.entries) * 0.99);
          const capacityAfterWorkloadPassed = checkpointAfterWorkloadValid
            && metricsAfterWorkload.currentEntries >= minimumEntries;
          const capacityAfterWriteProbePassed = checkpointAfterWriteProbeValid
            && metricsAfterWriteProbe.currentEntries >= minimumEntries;
          const capacityPassed = capacityAfterWorkloadPassed && capacityAfterWriteProbePassed;
          const singleFlightFromLoaderCount = Number(workload.loaderInvocationsUnderContention) === 1;
          if (workload.singleFlightPassed !== singleFlightFromLoaderCount) errors.push(`${prefix}: workload single-flight flag differs from loader count`);
          const singleFlightPassed = workload.singleFlightPassed === true;
          if (!sameNumber(Number(gate.expectedHitRate), expectedHitRate)) errors.push(`${prefix}: expected hit rate differs from the configured target`);
          if (!sameNumber(Number(gate.observedHitRate), observedHitRate)) errors.push(`${prefix}: observed hit rate differs between metrics and gate`);
          if (Number(gate.minimumExpectedEntriesAfterWorkload) !== minimumEntries) errors.push(`${prefix}: post-workload minimum capacity threshold differs from floor(entries * 0.99)`);
          if (Number(gate.minimumExpectedEntriesAfterWriteProbe) !== minimumEntries) errors.push(`${prefix}: minimum capacity threshold differs from floor(entries * 0.99)`);
          if (gate.observedEntriesAfterWorkload !== metricsAfterWorkload?.currentEntries) errors.push(`${prefix}: post-workload capacity differs between metrics and gate`);
          if (gate.observedEntriesAfterWriteProbe !== metricsAfterWriteProbe?.currentEntries) errors.push(`${prefix}: post-write capacity differs between metrics and gate`);
          assertGateEquality(errors, gate.hitRateWithinHalfPercentagePoint, hitRatePassed, `${prefix} hit-rate gate`);
          assertGateEquality(errors, gate.capacityAfterWorkloadPassed, capacityAfterWorkloadPassed, `${prefix} post-workload capacity gate`);
          assertGateEquality(errors, gate.capacityAfterWriteProbePassed, capacityAfterWriteProbePassed, `${prefix} post-write capacity gate`);
          assertGateEquality(errors, gate.capacityCheckPassed, capacityPassed, `${prefix} capacity gate`);
          assertGateEquality(errors, gate.singleFlightPassed, singleFlightPassed, `${prefix} single-flight gate`);
          recomputedPassed = completed && durationPassed && metricCheckpointsValid
            && hitRatePassed && capacityPassed && singleFlightPassed;
        }
        assertGateEquality(errors, gate.passed, recomputedPassed, `${prefix} overall semantic gate`);
      }
    }
  }
  assert(errors.length === 0, `Numerical QC differs from runner output:\n${errors.slice(0, 30).join("\n")}${errors.length > 30 ? `\n... ${errors.length - 30} more` : ""}`);
}

function validateFinalInputs(raw, analysis, paperValues, files) {
  assert(raw.schemaVersion === 4, `Expected results schemaVersion 4, found ${raw.schemaVersion}`);
  assert(analysis.schemaVersion === 4, `Expected analysis schemaVersion 4, found ${analysis.schemaVersion}`);
  assert(raw.protocolVersion === "4.2", `Expected results protocolVersion 4.2, found ${raw.protocolVersion}`);
  assert(analysis.protocolVersion === "4.2", `Expected analysis protocolVersion 4.2, found ${analysis.protocolVersion}`);
  assert(paperValues.schemaVersion === 1, `Expected paper-values schemaVersion 1, found ${paperValues.schemaVersion}`);
  assert(paperValues.protocolVersion === "4.2", `Expected paper-values protocolVersion 4.2, found ${paperValues.protocolVersion}`);
  assert(paperValues.campaignId === files.campaignId, "paper-values campaignId differs from the selected campaign prefix");
  assert(paperValues.datasetStatus === "complete-and-accepted", "paper-values does not identify a complete accepted dataset");
  assert(path.basename(files.rawPath) === `${files.campaignId}-results.json`, "results filename differs from the selected campaign prefix");
  assert(path.basename(files.analysisPath) === `${files.campaignId}-analysis.json`, "analysis filename differs from the selected campaign prefix");
  assert(path.basename(files.paperValuesPath) === `${files.campaignId}-paper-values.json`, "paper-values filename differs from the selected campaign prefix");
  assert(JSON.stringify(raw.providers) === JSON.stringify(CANONICAL_PROVIDERS), "Provider order does not match the prespecified v4.2 protocol");
  assert(raw.forks === 6, "Final campaign must declare exactly six forks");
  assert(raw.cyclesPerProcessRun === 5, "Final campaign must declare exactly five cycles per process run");
  const expectedConfiguration = {
    entries: 10_000,
    operations: CONFIGURED_OPERATIONS,
    threads: 8,
    hitPercent: 95,
    payloadBytes: 512,
    warmupOperations: 50_000,
    warmupSeconds: 3,
    measurementSeconds: 5,
    ttlSeconds: 300,
    workload: "uniform",
    writePercent: 10,
    jcsMemoryMode: "strict",
    seed: 24_301,
    latencySampleRate: 64,
  };
  for (const [key, value] of Object.entries(expectedConfiguration)) {
    assert(raw.configuration?.[key] === value, `Final configuration.${key} must equal the v4.2 prespecified value ${value}`);
  }
  for (const key of ["threads", "hitPercent", "workloads", "jcsMemoryModes"]) {
    assert(asArray(raw.matrix?.[key]).length === 1, `Final v4.2 campaign must contain one ${key} scenario`);
  }
  assert(raw.matrix.threads[0] === 8 && raw.matrix.hitPercent[0] === 95 && raw.matrix.workloads[0] === "uniform" && raw.matrix.jcsMemoryModes[0] === "strict", "Final matrix differs from the single v4.2 prespecified scenario");
  assert(raw.schedule?.design === "frozen canonical Williams 6x6", "Final campaign must declare the frozen canonical Williams 6x6 design");
  assert(raw.schedule?.scheduleSeed === 2_482_026, "Final campaign scheduleSeed differs from the v4.2 prespecified value");
  assert(raw.schedule?.rowsAreShuffled === false, "Williams rows must not be shuffled");
  assert(JSON.stringify(raw.schedule?.canonicalRows) === JSON.stringify(WILLIAMS_ROWS), "Williams canonical rows differ from the prespecified protocol");
  assert(JSON.stringify(raw.schedule?.selectedProviders) === JSON.stringify(CANONICAL_PROVIDERS), "Williams provider list differs from the prespecified protocol");
  assert(asArray(raw.executionPlan).length === EXPECTED_COUNTS.processRuns, "Execution plan must contain exactly 36 process runs");
  requireText(raw.campaignStartedAt, "campaignStartedAt");
  requireText(raw.campaignFinishedAt, "campaignFinishedAt");
  assert(Date.parse(raw.campaignFinishedAt) >= Date.parse(raw.campaignStartedAt), "Campaign finish timestamp precedes its start");
  assert(Array.isArray(raw.infrastructureFailures) && raw.infrastructureFailures.length === 0, "Final results must declare zero infrastructureFailures");
  assert(Array.isArray(raw.invalidBlocks) && raw.invalidBlocks.length === 0, "Final results must declare zero invalid Williams blocks");
  assert(Array.isArray(analysis.invalidBlocks) && analysis.invalidBlocks.length === 0, "Final analysis must declare zero invalid Williams blocks");
  assert(analysis.rankingProduced === false && !("winner" in analysis), "Protocol v4.2 must not emit a winner or ranking");
  requireText(analysis.generatedAt, "analysis.generatedAt");
  requireText(analysis.statisticalUnit, "analysis.statisticalUnit");
  requireText(analysis.primaryAnalysis, "analysis.primaryAnalysis");
  requireText(analysis.sensitivityAnalysis, "analysis.sensitivityAnalysis");
  assertSha256(raw.analysisSha256, "results.analysisSha256");
  assert(raw.analysisSha256.toLowerCase() === files.analysisSha.toLowerCase(), "analysis.json SHA-256 does not match results.analysisSha256");
  requireText(raw.analysisFile, "results.analysisFile");
  assert(path.basename(raw.analysisFile) === path.basename(files.analysisPath), "The supplied analysis filename differs from results.analysisFile");

  const paperProvenance = paperValues.provenance ?? {};
  assert(paperProvenance.resultsFile === path.basename(files.rawPath), "paper-values provenance points to a different results file");
  assert(paperProvenance.analysisFile === path.basename(files.analysisPath), "paper-values provenance points to a different analysis file");
  assert(paperProvenance.resultsSha256 === files.rawSha, "paper-values results SHA-256 differs from the selected results JSON");
  assert(paperProvenance.analysisSha256 === files.analysisSha, "paper-values analysis SHA-256 differs from the selected analysis JSON");
  assert(paperProvenance.analysisSha256DeclaredInResults === raw.analysisSha256, "paper-values does not preserve the analysis checksum declared in results");
  assert(paperProvenance.protocol?.path === EXPECTED_PROTOCOL_PATH, "paper-values protocol path differs from the frozen v4.2 protocol");
  assert(paperProvenance.protocol?.sha256 === EXPECTED_PROTOCOL_SHA256, "paper-values protocol SHA-256 differs from the frozen v4.2 protocol");
  assert(paperValues.qualityControl?.denominatorDefinition?.processesTotal === EXPECTED_COUNTS.processRuns, "paper-values process denominator is inconsistent");
  assert(paperValues.qualityControl?.denominatorDefinition?.cyclesTotal === EXPECTED_COUNTS.cycles, "paper-values cycle denominator is inconsistent");
  assert(paperValues.qualityControl?.denominatorDefinition?.workloadWindowsTotal === EXPECTED_COUNTS.workloadWindows, "paper-values workload-window denominator is inconsistent");
  assert(paperValues.lifecycle?.timingEvidence?.intervals === EXPECTED_COUNTS.cycles * 2, "paper-values timing evidence must cover both undeploy intervals of every cycle");

  const protocol = raw.lifecycleProtocol ?? {};
  assert(protocol.freshContainerPerProcessRun === true, "v4.2 requires a fresh container per process run");
  assert(protocol.earlyThreadObservationSeconds === 2, "v4.2 early diagnostic checkpoint must be 2 seconds");
  assert(protocol.finalObservationAndFindleaksSeconds === 10, "v4.2 final diagnostic checkpoint must be 10 seconds");
  assert(protocol.forcedGcCountPerFinalSnapshot === 2, "v4.2 final snapshots must follow two forced-GC requests");
  assert(protocol.findleaksOccurrencesPreserved === true, "v4.2 must preserve every findleaks occurrence");
  assert(protocol.finalHeapDumpPolicy === "jcs", "v4.2 final heap-dump policy must be jcs");

  const preflight = raw.campaignPreflight ?? {};
  assert(preflight.provenanceValidationPassed === true, "Campaign preflight provenance must pass");
  assert(preflight.nativeMemoryTrackingSummaryAvailable === true, "Campaign preflight must verify Native Memory Tracking");
  validateEnvironment(preflight, "campaignPreflight");

  const source = raw.sourceProvenance ?? {};
  assertSha256(source.manifestSha256, "sourceProvenance.manifestSha256");
  assert(asArray(source.files).length > 0, "sourceProvenance.files must not be empty");
  const sourceLines = asArray(source.files).map((item, index) => {
    requireText(item?.path, `sourceProvenance.files[${index}].path`);
    assertSha256(item?.sha256, `sourceProvenance.files[${index}].sha256`);
    assert(Number.isInteger(item?.sizeBytes) && item.sizeBytes >= 0, `sourceProvenance.files[${index}].sizeBytes is invalid`);
    return `${item.sha256}  ${item.path}`;
  });
  assert(sha256(Buffer.from(sourceLines.join("\n"), "utf8")) === source.manifestSha256.toLowerCase(), "sourceProvenance manifest SHA-256 is inconsistent");
  const protocolRows = asArray(source.files).filter((item) => item.path === EXPECTED_PROTOCOL_PATH);
  assert(protocolRows.length === 1, `sourceProvenance must contain ${EXPECTED_PROTOCOL_PATH} exactly once`);
  assert(protocolRows[0].sha256.toLowerCase() === EXPECTED_PROTOCOL_SHA256, "sourceProvenance protocol SHA-256 differs from the frozen v4.2 protocol");
  assert(paperProvenance.sourceManifestSha256 === source.manifestSha256, "paper-values source manifest SHA-256 differs from results");
  validateArtifactMetadata(raw.diagnosticArchive, "diagnosticArchive");
  assert(raw.diagnosticArchive.sizeBytes > 0, "diagnosticArchive.sizeBytes must be positive");

  const runs = asArray(raw.processRuns);
  assert(runs.length === EXPECTED_COUNTS.processRuns, `Final campaign must contain exactly ${EXPECTED_COUNTS.processRuns} process runs`);
  const runIds = new Set();
  const containerIds = new Set();
  const dockerHosts = new Set();
  let cycleCount = 0;
  let workloadWindowCount = 0;
  for (const run of runs) {
    const runId = requireText(run.processRunId, "processRunId");
    assert(runId.startsWith(`${files.campaignId}-default-f`), `${runId}: processRunId differs from the selected campaign prefix`);
    assert(!runIds.has(runId), `Duplicate processRunId ${runId}`);
    runIds.add(runId);
    assert(run.fork === run.block && Number.isInteger(run.fork) && run.fork >= 1 && run.fork <= 6, `${runId}: fork/block must be identical integers in 1..6`);
    assert(CANONICAL_PROVIDERS.includes(run.provider), `${runId}: unknown provider ${run.provider}`);
    requireText(run.startedAt, `${runId}: startedAt`);
    requireText(run.finishedAt, `${runId}: finishedAt`);
    assert(Date.parse(run.finishedAt) >= Date.parse(run.startedAt), `${runId}: finish timestamp precedes start`);
    assert(asArray(run.cycles).length === 5, `${runId}: exactly five cycles are required`);
    requireText(run.processBaseline?.label, `${runId}: processBaseline.label`);
    validateEnvironment(run.environment, runId);
    assert(run.environment.containerCpuLimit === preflight.containerCpuLimit, `${runId}: CPU limit differs from campaign preflight`);
    assert(run.environment.containerMemoryLimitBytes === preflight.containerMemoryLimitBytes, `${runId}: memory limit differs from campaign preflight`);
    assert(run.environment.runtimeBaseImage.pinnedDigest === preflight.runtimeBaseImage.pinnedDigest, `${runId}: runtime base-image digest differs from campaign preflight`);
    assert(run.environment.buildBaseImage.pinnedDigest === preflight.buildBaseImage.pinnedDigest, `${runId}: build base-image digest differs from campaign preflight`);
    if (["jcs321", "jcs4"].includes(run.provider)) {
      assert(run.finalHeapDump?.policy === "jcs", `${runId}: JCS final heap-dump policy differs from the v4.2 protocol`);
      requireText(run.finalHeapDump.file, `${runId}: finalHeapDump.file`);
      assertSha256(run.finalHeapDump.sha256, `${runId}: finalHeapDump.sha256`);
      assert(Number.isInteger(run.finalHeapDump.sizeBytes) && run.finalHeapDump.sizeBytes > 0, `${runId}: finalHeapDump.sizeBytes must be positive`);
    } else {
      assert(run.finalHeapDump == null, `${runId}: non-JCS provider unexpectedly has a final heap dump under policy=jcs`);
    }
    containerIds.add(run.environment.containerId);
    dockerHosts.add(run.environment.dockerServerName);
    asArray(run.cycles).forEach((cycle, index) => {
      assert(cycle.cycle === index + 1, `${runId}: cycle sequence must be 1..5`);
      cycleCount += 1;
      validateDiagnosticSnapshots(run, cycle);
      validatePostUndeployTiming(cycle.firstUndeployTiming, protocol, `${runId} C${cycle.cycle} firstUndeployTiming`);
      validatePostUndeployTiming(cycle.finalUndeployTiming, protocol, `${runId} C${cycle.cycle} finalUndeployTiming`);
      assert(cycle.request?.operations === CONFIGURED_OPERATIONS, `${runId} C${cycle.cycle}: request.operations must be ${CONFIGURED_OPERATIONS}`);
      assert(cycle.request?.workload === "uniform", `${runId} C${cycle.cycle}: request.workload must be uniform`);
      assert(cycle.request?.writePercent === 10, `${runId} C${cycle.cycle}: request.writePercent must remain 10%`);
      for (const [workloadKey, gateKey] of [["workload", "protocolValidation"], ["redeployWorkload", "redeployProtocolValidation"]]) {
        const workload = cycle[workloadKey];
        const gate = cycle[gateKey];
        assert(isRecord(workload) && isRecord(gate), `${runId} C${cycle.cycle}: both workload windows and gates are required`);
        workloadWindowCount += 1;
        assertSha256(workload.accessPlanSha256, `${runId} C${cycle.cycle}: ${workloadKey}.accessPlanSha256`);
        const configuration = workload.configuration ?? cycle.request ?? run.configuration ?? raw.configuration;
        assert(configuration.operations === CONFIGURED_OPERATIONS, `${runId} C${cycle.cycle}: workload operation-plan size must be ${CONFIGURED_OPERATIONS}`);
        assert(configuration.workload === "uniform", `${runId} C${cycle.cycle}: workload must be uniform`);
        assert(configuration.writePercent === 10, `${runId} C${cycle.cycle}: configured writePercent must remain 10%`);
        assert(workload.concurrentWriteOperations === 0, `${runId} C${cycle.cycle}: uniform workload unexpectedly executed timed concurrent writes`);
        assert(gate.gateType === (run.provider === "nostore" ? "no-store-control" : "cache-semantics"), `${runId} C${cycle.cycle}: semantic gate type is inconsistent with the provider`);
        assert(gate.performanceComparisonEligible === PRIMARY_PERFORMANCE_PROVIDERS.has(run.provider), `${runId} C${cycle.cycle}: performance eligibility is inconsistent with the prespecified provider role`);
        assert(gate.passed === true, `${runId} C${cycle.cycle}: semantic gate did not pass`);
      }
      assert(cycle.workload.accessPlanSha256 === cycle.redeployWorkload.accessPlanSha256, `${runId} C${cycle.cycle}: initial and redeploy access-plan hashes differ`);
    });
  }
  assert(containerIds.size === EXPECTED_COUNTS.processRuns, "All 36 process runs must have distinct full container IDs");
  assert(dockerHosts.size === 1, "Process runs are not recorded on one Docker host as prespecified");
  const plannedRunIds = new Set(asArray(raw.executionPlan).map((item) => item?.processRunId));
  assert(plannedRunIds.size === EXPECTED_COUNTS.processRuns && [...runIds].every((runId) => plannedRunIds.has(runId)), "Completed process runs do not match the 36-entry execution plan");
  assert(cycleCount === EXPECTED_COUNTS.cycles, `Expected ${EXPECTED_COUNTS.cycles} cycles, found ${cycleCount}`);
  assert(workloadWindowCount === EXPECTED_COUNTS.workloadWindows, `Expected ${EXPECTED_COUNTS.workloadWindows} workload windows, found ${workloadWindowCount}`);

  for (const [key, count] of Object.entries(EXPECTED_COUNTS)) {
    if (["processRuns", "cycles", "workloadWindows"].includes(key)) continue;
    assert(asArray(analysis[key]).length === count, `analysis.${key} must contain exactly ${count} rows`);
  }
  for (const key of ["observations", "forks", "lifecycleForks"]) {
    assert(asArray(analysis[key]).every((row) => row.blockValid === true), `analysis.${key} contains an invalid block`);
  }
  const rawObservationMap = new Map();
  for (const run of runs) {
    for (const cycle of asArray(run.cycles)) {
      for (const [phase, workloadKey, gateKey] of [["initial", "workload", "protocolValidation"], ["redeploy", "redeployWorkload", "redeployProtocolValidation"]]) {
        const timing = phase === "redeploy" ? cycle.finalUndeployTiming : cycle.firstUndeployTiming;
        const metricsAfterWorkload = cycle[workloadKey].providerMetricsAfterWorkload;
        const metricsAfterWriteProbe = cycle[workloadKey].providerMetricsAfterWriteProbe;
        rawObservationMap.set(`${run.processRunId}|${cycle.cycle}|${phase}`, {
          requestSeed: cycle.requestSeed,
          operationsPerSecond: cycle[workloadKey].operationsPerSecond,
          observedHitRate: metricsAfterWorkload?.hitRate,
          observedEntries: metricsAfterWriteProbe?.currentEntries,
          observedEntriesAfterWorkload: metricsAfterWorkload?.currentEntries,
          observedEntriesAfterWriteProbe: metricsAfterWriteProbe?.currentEntries,
          semanticGatePassed: cycle[gateKey].passed,
          performanceComparisonEligible: cycle[gateKey].performanceComparisonEligible,
          timing,
        });
      }
    }
  }
  const seenObservationKeys = new Set();
  for (const observation of asArray(analysis.observations)) {
    const key = `${observation.processRunId}|${observation.cycle}|${observation.phase}`;
    assert(!seenObservationKeys.has(key), `Duplicate analysis observation ${key}`);
    seenObservationKeys.add(key);
    const expected = rawObservationMap.get(key);
    assert(expected, `Analysis observation ${key} has no matching raw workload`);
    assert(observation.requestSeed === expected.requestSeed, `${key}: analysis requestSeed differs from raw`);
    assert(sameNumber(observation.operationsPerSecond, expected.operationsPerSecond), `${key}: analysis throughput differs from raw`);
    assert(sameNumber(observation.observedHitRate, expected.observedHitRate), `${key}: analysis hit rate differs from raw`);
    assert(observation.observedEntries === expected.observedEntries, `${key}: analysis entry count differs from raw`);
    assert(observation.observedEntriesAfterWorkload === expected.observedEntriesAfterWorkload, `${key}: analysis post-workload entry count differs from raw`);
    assert(observation.observedEntriesAfterWriteProbe === expected.observedEntriesAfterWriteProbe, `${key}: analysis post-write entry count differs from raw`);
    assert(observation.semanticGatePassed === expected.semanticGatePassed, `${key}: analysis semantic gate differs from raw`);
    assert(observation.performanceComparisonEligible === expected.performanceComparisonEligible, `${key}: analysis eligibility differs from raw`);
    for (const field of ANALYSIS_TIMING_FIELDS) {
      assert(sameNumber(observation[field], expected.timing[field]), `${key}: analysis ${field} differs from raw timing evidence`);
    }
  }
  assert(seenObservationKeys.size === rawObservationMap.size, "Analysis observations do not cover all 360 raw workload windows exactly once");
  const analysisSets = new Set([
    ...asArray(analysis.summaries).map((row) => row.analysisSet),
    ...asArray(analysis.forks).map((row) => row.analysisSet),
    ...asArray(analysis.pairedRatios).map((row) => row.analysisSet),
  ]);
  assert(JSON.stringify([...analysisSets].sort()) === JSON.stringify(["primary-all-cycles", "sensitivity-without-cycle-1"]), "Analysis sets must be exactly primary-all-cycles and sensitivity-without-cycle-1");
  const runsById = new Map(runs.map((run) => [run.processRunId, run]));
  for (const row of asArray(analysis.lifecycleForks)) {
    assert(Number.isInteger(row.jcs248CorroboratedUndeployCount) && row.jcs248CorroboratedUndeployCount >= 0, `${row.processRunId}: jcs248CorroboratedUndeployCount is required`);
    assert(Array.isArray(row.jcs248CorroboratedIntervals), `${row.processRunId}: jcs248CorroboratedIntervals[] is required`);
    assert(row.jcs248CorroboratedIntervals.length === row.jcs248CorroboratedUndeployCount, `${row.processRunId}: JCS-248 interval count is inconsistent`);
    assert(row.jcs248CorroboratedSignalObserved === (row.jcs248CorroboratedUndeployCount > 0), `${row.processRunId}: JCS-248 corroborated boolean is inconsistent`);
    const rawRun = runsById.get(row.processRunId);
    assert(rawRun, `${row.processRunId}: lifecycleFork has no matching raw process run`);
    const corroboratedIntervals = [];
    for (const cycle of asArray(rawRun.cycles)) {
      for (const [phase, earlyKey, finalKey, warningKey] of [
        ["first-undeploy", "firstUndeployThreadEvidenceEarly", "firstUndeployThreadEvidenceFinal", "firstUndeployThreadLeakWarnings"],
        ["final-undeploy", "finalUndeployThreadEvidenceEarly", "finalUndeployThreadEvidenceFinal", "secondUndeployThreadLeakWarnings"],
      ]) {
        const signatures = [
          ...asArray(cycle[earlyKey]?.jcsThreadSignatures),
          ...asArray(cycle[finalKey]?.jcsThreadSignatures),
        ];
        const warnings = asArray(cycle[warningKey]);
        if (signatures.length && warnings.length) {
          corroboratedIntervals.push({
            cycle: cycle.cycle,
            phase,
            signatureObservationCount: signatures.length,
            threadLeakWarningCount: warnings.length,
          });
        }
      }
    }
    assert(JSON.stringify(row.jcs248CorroboratedIntervals) === JSON.stringify(corroboratedIntervals), `${row.processRunId}: JCS-248 corroborated intervals differ from raw evidence`);
  }
  for (const summary of asArray(analysis.lifecycleSummaries).filter((row) => ["jcs321", "jcs4"].includes(row.provider))) {
    const recomputedCriterion = summary.provider === "jcs321"
      && summary.forkCount === 6
      && summary.forksWithJcs248CorroboratedSignal >= 5;
    assert(summary.jcs248PositiveControlCriterionMet === recomputedCriterion, `${summary.provider}: JCS-248 positive-control criterion is inconsistent`);
  }
  assert(asArray(analysis.pairedRatios).every((row) => row.referenceProvider === "jcs4"), "Every paired ratio must use JCS4 as reference");
  assert(JSON.stringify([...new Set(asArray(analysis.pairedRatios).map((row) => row.provider))].sort()) === JSON.stringify(["cache2k", "caffeine", "ehcache"]), "Paired ratios must cover caffeine, ehcache, and cache2k only");
  assert(asArray(analysis.pairedRatios).every((row) => asArray(row.valuesByBlock).length === 6), "Each paired provider/JCS4 ratio must retain all six Williams blocks");
  assert(asArray(analysis.summaries).filter((row) => ["jcs321", "nostore"].includes(row.provider)).every((row) => row.performanceIncludedForkCount === 0), "Lifecycle controls must remain excluded from performance summaries");
  assert(typeof analysis.performanceExclusions?.jcs321 === "string" && typeof analysis.performanceExclusions?.nostore === "string", "Analysis performance exclusions must document both lifecycle controls");
  validateNumericalQualityGates(raw);
}

function asArray(value) {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

function finiteOrNull(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanOrNull(value) {
  return typeof value === "boolean" ? value : null;
}

function dateOrNull(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function clippedJson(value) {
  if (value == null) return null;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length <= 30000 ? text : `${text.slice(0, 29970)}… [truncated]`;
}

function joined(items, mapper = (item) => item) {
  const values = asArray(items).map(mapper).filter((item) => item != null && item !== "");
  return values.length ? values.join(" | ") : null;
}

function safeCellValue(value) {
  if (value == null) return null;
  if (value instanceof Date) return value;
  if (["number", "boolean"].includes(typeof value)) return value;
  if (typeof value === "object") return clippedJson(value);
  const text = String(value);
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

function excelColumn(columnNumber) {
  let number = columnNumber;
  let result = "";
  while (number > 0) {
    number -= 1;
    result = String.fromCharCode(65 + (number % 26)) + result;
    number = Math.floor(number / 26);
  }
  return result;
}

function cellRef(sheetName, column, row, absolute = true) {
  const dollar = absolute ? "$" : "";
  return `'${sheetName}'!${dollar}${column}${dollar}${row}`;
}

function descriptor(key, label, options = {}) {
  return {
    key,
    label,
    unit: options.unit ?? "",
    type: options.type ?? "text",
    source: options.source ?? SOURCE_RESULTS,
    definition: options.definition ?? `Valore ${key} come registrato dalla campagna v4.2 (JSON schemaVersion 4).`,
    width: options.width ?? 16,
    format: options.format ?? null,
    wrap: options.wrap ?? false,
  };
}

function keyIndex(columns, key) {
  const index = columns.findIndex((column) => column.key === key);
  if (index < 0) throw new Error(`Column key not found: ${key}`);
  return index;
}

function keyColumn(columns, key) {
  return excelColumn(keyIndex(columns, key) + 1);
}

function styleHeader(range, fill = COLORS.navy) {
  range.format = {
    fill,
    font: { name: "Aptos", size: 9, bold: true, color: COLORS.white },
    wrapText: true,
    verticalAlignment: "center",
    borders: { bottom: { style: "medium", color: COLORS.line } },
  };
  range.format.rowHeight = 31;
}

function styleBody(range) {
  range.format = {
    font: { name: "Aptos", size: 9, color: COLORS.ink },
    verticalAlignment: "top",
  };
}

function styleTitle(sheet, title, subtitle, lastColumn) {
  const titleRange = sheet.getRange(`A1:${lastColumn}1`);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: COLORS.navy,
    font: { name: "Aptos Display", size: 16, bold: true, color: COLORS.white },
    verticalAlignment: "center",
  };
  titleRange.format.rowHeight = 30;
  const subtitleRange = sheet.getRange(`A2:${lastColumn}2`);
  subtitleRange.merge();
  subtitleRange.values = [[subtitle]];
  subtitleRange.format = {
    fill: COLORS.paleBlue,
    font: { name: "Aptos", size: 9, italic: true, color: COLORS.muted },
    wrapText: true,
    verticalAlignment: "center",
  };
  subtitleRange.format.rowHeight = 28;
}

function styleSection(sheet, row, startColumn, endColumn, title) {
  const range = sheet.getRange(`${startColumn}${row}:${endColumn}${row}`);
  range.merge();
  range.values = [[title]];
  range.format = {
    fill: COLORS.teal,
    font: { name: "Aptos", size: 10, bold: true, color: COLORS.white },
    verticalAlignment: "center",
  };
  range.format.rowHeight = 23;
}

function applyColumnFormats(sheet, columns, firstDataRow, lastDataRow, totalRows) {
  for (let index = 0; index < columns.length; index += 1) {
    const column = columns[index];
    const letter = excelColumn(index + 1);
    sheet.getRange(`${letter}1:${letter}${Math.max(totalRows, 1)}`).format.columnWidth = column.width;
    if (lastDataRow < firstDataRow) continue;
    const range = sheet.getRange(`${letter}${firstDataRow}:${letter}${lastDataRow}`);
    if (column.format) range.setNumberFormat(column.format);
    if (column.wrap) range.format.wrapText = true;
    if (["number", "integer", "percent", "bytes", "duration"].includes(column.type)) {
      range.format.horizontalAlignment = "right";
    } else if (column.type === "boolean") {
      range.format.horizontalAlignment = "center";
    } else {
      range.format.horizontalAlignment = "left";
    }
  }
}

function addExcelTable(sheet, rangeAddress, name) {
  const table = sheet.tables.add(rangeAddress, true, name);
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  table.showBandedColumns = false;
  return table;
}

function writeFlatSheet(sheet, columns, rows, options) {
  const matrix = [
    columns.map((column) => column.label),
    ...rows.map((row) => columns.map((column) => safeCellValue(row[column.key]))),
  ];
  const rowCount = matrix.length;
  const columnCount = columns.length;
  sheet.getRangeByIndexes(0, 0, rowCount, columnCount).values = matrix;
  styleBody(sheet.getRangeByIndexes(0, 0, rowCount, columnCount));
  styleHeader(sheet.getRangeByIndexes(0, 0, 1, columnCount));
  if (rows.length) {
    addExcelTable(sheet, `A1:${excelColumn(columnCount)}${rowCount}`, options.tableName);
  }
  applyColumnFormats(sheet, columns, 2, rowCount, rowCount);
  sheet.freezePanes.freezeRows(1);
  if (options.freezeColumns) sheet.freezePanes.freezeColumns(options.freezeColumns);
  sheet.showGridLines = false;
  return {
    headerRow: 1,
    firstDataRow: 2,
    lastDataRow: rowCount,
    lastColumn: excelColumn(columnCount),
    rowCount: rows.length,
    columnCount,
  };
}

function writeSectionTable(sheet, startRow, startColumnIndex, columns, rows, tableName) {
  const matrix = [
    columns.map((column) => column.label),
    ...rows.map((row) => columns.map((column) => safeCellValue(row[column.key]))),
  ];
  const startColumn = excelColumn(startColumnIndex);
  const endColumn = excelColumn(startColumnIndex + columns.length - 1);
  const endRow = startRow + matrix.length - 1;
  const range = sheet.getRange(`${startColumn}${startRow}:${endColumn}${endRow}`);
  range.values = matrix;
  styleBody(range);
  styleHeader(sheet.getRange(`${startColumn}${startRow}:${endColumn}${startRow}`));
  if (rows.length) addExcelTable(sheet, `${startColumn}${startRow}:${endColumn}${endRow}`, tableName);
  for (let index = 0; index < columns.length; index += 1) {
    const column = columns[index];
    const letter = excelColumn(startColumnIndex + index);
    sheet.getRange(`${letter}${startRow}:${letter}${endRow}`).format.columnWidth = column.width;
    if (rows.length) {
      const dataRange = sheet.getRange(`${letter}${startRow + 1}:${letter}${endRow}`);
      if (column.format) dataRange.setNumberFormat(column.format);
      if (column.wrap) dataRange.format.wrapText = true;
      if (["number", "integer", "percent", "bytes", "duration"].includes(column.type)) {
        dataRange.format.horizontalAlignment = "right";
      } else if (column.type === "boolean") {
        dataRange.format.horizontalAlignment = "center";
      }
    }
  }
  return {
    headerRow: startRow,
    firstDataRow: startRow + 1,
    lastDataRow: endRow,
    firstColumn: startColumn,
    lastColumn: endColumn,
  };
}

function providerOrder(raw) {
  const providers = asArray(raw.providers);
  const order = new Map(providers.map((provider, index) => [provider, index]));
  return (provider) => order.get(provider) ?? 999;
}

function sortByStudyOrder(records, raw, extras = []) {
  const order = providerOrder(raw);
  const phaseOrder = { initial: 0, redeploy: 1 };
  const analysisOrder = { "primary-all-cycles": 0, "sensitivity-without-cycle-1": 1 };
  return [...records].sort((left, right) => {
    const comparisons = [
      order(left.provider) - order(right.provider),
      (left.fork ?? 0) - (right.fork ?? 0),
      (left.cycle ?? 0) - (right.cycle ?? 0),
      (phaseOrder[left.phase] ?? 99) - (phaseOrder[right.phase] ?? 99),
      (analysisOrder[left.analysisSet] ?? 99) - (analysisOrder[right.analysisSet] ?? 99),
      ...extras.map((key) => String(left[key] ?? "").localeCompare(String(right[key] ?? ""))),
    ];
    return comparisons.find((value) => value !== 0) ?? 0;
  });
}

function roleMaps(analysis) {
  const byScenarioProvider = new Map();
  for (const row of asArray(analysis.lifecycleSummaries)) {
    byScenarioProvider.set(`${row.scenario}|${row.provider}`, row.studyRole);
  }
  for (const row of asArray(analysis.summaries)) {
    byScenarioProvider.set(`${row.scenario}|${row.provider}`, row.studyRole);
  }
  return {
    get(scenario, provider) {
      return byScenarioProvider.get(`${scenario ?? "default"}|${provider}`)
        ?? (provider === "jcs321"
          ? "JCS-248-positive-control"
          : provider === "nostore"
            ? "lifecycle-negative-control"
            : "current-provider-primary-comparison");
    },
  };
}

function flattenRuns(raw, roles) {
  return asArray(raw.processRuns).map((run) => {
    const environment = run.environment ?? {};
    const heapDump = run.finalHeapDump ?? {};
    const effectivePom = artifactByName(environment, "effective-pom.xml");
    const dependencyTree = artifactByName(environment, "dependency-tree.txt");
    const buildProvenance = artifactByName(environment, "build-provenance.properties");
    const providerVersion = run.provider === "jcs4"
      ? environment.jcs4Version
      : run.provider === "jcs321"
        ? environment.jcs321Version
        : null;
    const prespecifiedVersion = PRESPECIFIED_PROVIDER_VERSIONS[run.provider] ?? {};
    return {
      processRunId: run.processRunId,
      scenario: run.scenario ?? "default",
      provider: run.provider,
      engineProvider: run.engineProvider,
      studyRole: roles.get(run.scenario ?? "default", run.provider),
      fork: run.fork,
      block: run.block,
      orderPosition: run.orderPosition,
      williamsRow: run.williamsRow,
      startedAt: dateOrNull(run.startedAt),
      finishedAt: dateOrNull(run.finishedAt),
      durationSecondsFormula: null,
      containerId: environment.containerId,
      dockerImageId: environment.dockerImageId,
      containerImageName: environment.containerImageName,
      containerStartedAt: dateOrNull(environment.containerStartedAt),
      containerCpuLimit: finiteOrNull(environment.containerCpuLimit),
      containerCpuModel: environment.containerCpuModel,
      containerVisibleProcessors: finiteOrNull(environment.containerVisibleProcessors),
      containerMemoryLimitBytes: finiteOrNull(environment.containerMemoryLimitBytes),
      containerMemoryLimitMiBFormula: null,
      containerOS: environment.containerOS,
      containerKernel: environment.containerKernel,
      dockerServerVersion: environment.dockerServerVersion,
      dockerServerOperatingSystem: environment.dockerServerOperatingSystem,
      dockerServerKernelVersion: environment.dockerServerKernelVersion,
      dockerServerArchitecture: environment.dockerServerArchitecture,
      dockerServerName: environment.dockerServerName,
      tomcatVersion: environment["Tomcat Version"],
      osName: environment["OS Name"],
      osVersion: environment["OS Version"],
      osArchitecture: environment["OS Architecture"],
      jvmVersion: environment["JVM Version"],
      jvmVendor: environment["JVM Vendor"],
      javaOptions: environment.javaOptions,
      jvmCommandLine: environment.jvmCommandLine,
      jvmFlags: environment.jvmFlags,
      providerVersionRuntime: providerVersion,
      providerVersionPrespecified: prespecifiedVersion.version,
      providerVersionEvidence: prespecifiedVersion.evidence,
      imageJcs4RevisionLabel: environment.imageJcs4RevisionLabel,
      requestedRuntimeImage: environment.requestedRuntimeImage,
      runtimeBaseImageReference: environment.runtimeBaseImage?.reference,
      runtimeBaseImagePinnedDigest: environment.runtimeBaseImage?.pinnedDigest,
      runtimeBaseImageInspectionAvailable: booleanOrNull(environment.runtimeBaseImage?.inspectionAvailable),
      runtimeBaseImageId: environment.runtimeBaseImage?.id,
      requestedBuildImage: environment.requestedBuildImage,
      buildBaseImageReference: environment.buildBaseImage?.reference,
      buildBaseImagePinnedDigest: environment.buildBaseImage?.pinnedDigest,
      buildBaseImageInspectionAvailable: booleanOrNull(environment.buildBaseImage?.inspectionAvailable),
      buildBaseImageId: environment.buildBaseImage?.id,
      jcs4Version: environment.jcs4Version,
      jcs4SourceCommit: environment.jcs4SourceCommit,
      jcs4ArtifactSha256: environment.jcs4ArtifactSha256,
      jcs321Version: environment.jcs321Version,
      jcs321ArtifactSha256: environment.jcs321ArtifactSha256,
      warSha256: environment.warSha256,
      artifactManifestJson: clippedJson(asArray(environment.artifactManifest).map((item) => ({
        file: artifactFileName(item?.containerPath),
        sha256: item?.sha256,
      }))),
      effectivePomFile: artifactFileName(effectivePom?.file),
      effectivePomSha256: effectivePom?.sha256,
      effectivePomSizeBytes: finiteOrNull(effectivePom?.sizeBytes),
      dependencyTreeFile: artifactFileName(dependencyTree?.file),
      dependencyTreeSha256: dependencyTree?.sha256,
      dependencyTreeSizeBytes: finiteOrNull(dependencyTree?.sizeBytes),
      buildProvenanceFile: artifactFileName(buildProvenance?.file),
      buildProvenanceSha256: buildProvenance?.sha256,
      buildProvenanceSizeBytes: finiteOrNull(buildProvenance?.sizeBytes),
      provenanceValidationPassed: booleanOrNull(environment.provenanceValidationPassed),
      provenanceValidationErrors: joined(environment.provenanceValidationErrors),
      cycleCount: asArray(run.cycles).length,
      warningCount: asArray(run.warnings).length,
      leakWarningCount: asArray(run.leakWarnings).length,
      threadLeakWarningCount: asArray(run.threadLeakWarnings).length,
      finalHeapDumpPolicy: heapDump.policy,
      finalHeapDumpFile: artifactFileName(heapDump.file),
      finalHeapDumpSha256: heapDump.sha256,
      finalHeapDumpSizeBytes: finiteOrNull(heapDump.sizeBytes),
    };
  });
}

function flattenWorkloads(raw, roles) {
  const rows = [];
  for (const run of asArray(raw.processRuns)) {
    for (const cycle of asArray(run.cycles)) {
      const phases = [
        ["initial", cycle.workload, cycle.protocolValidation],
        ["redeploy", cycle.redeployWorkload, cycle.redeployProtocolValidation],
      ];
      for (const [phase, workload, gate] of phases) {
        if (!workload) continue;
        const configuration = workload.configuration ?? cycle.request ?? run.configuration ?? raw.configuration ?? {};
        const metrics = workload.providerMetrics ?? {};
        const metricsAfterWorkload = workload.providerMetricsAfterWorkload ?? {};
        const metricsAfterWriteProbe = workload.providerMetricsAfterWriteProbe ?? {};
        rows.push({
          processRunId: run.processRunId,
          scenario: run.scenario ?? "default",
          provider: run.provider,
          engineProvider: run.engineProvider,
          studyRole: roles.get(run.scenario ?? "default", run.provider),
          fork: run.fork,
          block: run.block,
          orderPosition: run.orderPosition,
          cycle: cycle.cycle,
          phase,
          gateType: gate?.gateType,
          performanceComparisonEligible: booleanOrNull(gate?.performanceComparisonEligible),
          requestSeed: cycle.requestSeed,
          accessPlanSha256: workload.accessPlanSha256,
          entries: configuration.entries,
          operationsRequested: configuration.operations,
          threads: configuration.threads,
          hitPercent: configuration.hitPercent,
          payloadBytes: configuration.payloadBytes,
          warmupOperationsRequested: configuration.warmupOperations,
          warmupSecondsRequested: configuration.warmupSeconds,
          measurementSecondsRequested: configuration.measurementSeconds,
          ttlSeconds: configuration.ttlSeconds,
          workloadType: configuration.workload,
          writePercent: configuration.writePercent,
          jcsMemoryMode: configuration.jcsMemoryMode,
          latencySampleRate: configuration.latencySampleRate,
          warmupOperationsExecuted: workload.warmupOperationsExecuted,
          warmupNanos: workload.warmupNanos,
          warmupOvershootNanos: workload.warmupOvershootNanos,
          fillOperationsPerSecond: workload.fillOperationsPerSecond,
          operationsPerSecond: workload.operationsPerSecond,
          measuredOperations: workload.measuredOperations,
          measurementNanos: workload.measurementNanos,
          measurementOvershootNanos: workload.measurementOvershootNanos,
          readOperationsPerSecond: workload.readOperationsPerSecond,
          readOperations: workload.readOperations,
          concurrentWriteOperations: workload.concurrentWriteOperations,
          writeProbeOperationsPerSecond: workload.writeProbeOperationsPerSecond,
          latencyP50Nanos: workload.latencyP50Nanos,
          latencyP95Nanos: workload.latencyP95Nanos,
          latencyP99Nanos: workload.latencyP99Nanos,
          measuredLatencySamples: workload.measuredLatencySamples,
          loaderInvocationsUnderContention: workload.loaderInvocationsUnderContention,
          singleFlightPassed: booleanOrNull(workload.singleFlightPassed),
          observedEntriesAfterWorkload: metricsAfterWorkload.currentEntries,
          observedHitRateAfterWorkload: metricsAfterWorkload.hitRate,
          observedEntriesAfterWriteProbe: metricsAfterWriteProbe.currentEntries,
          observedHitRateAfterWriteProbe: metricsAfterWriteProbe.hitRate,
          providerMetricsAliasMatchesPostWrite: JSON.stringify(metrics) === JSON.stringify(metricsAfterWriteProbe),
          providerMetricsAfterWorkloadJson: clippedJson(metricsAfterWorkload),
          providerMetricsAfterWriteProbeJson: clippedJson(metricsAfterWriteProbe),
          currentEntries: metrics.currentEntries,
          requestCount: metrics.requestCount,
          hitCount: metrics.hitCount,
          missCount: metrics.missCount,
          hitRate: metrics.hitRate,
          loadSuccessCount: metrics.loadSuccessCount,
          loadFailureCount: metrics.loadFailureCount,
          totalLoadTimeNanos: metrics.totalLoadTimeNanos,
          evictionCount: metrics.evictionCount,
          expirationCount: metrics.expirationCount,
          putCount: metrics.putCount,
          removeCount: metrics.removeCount,
          nativeMetricsJson: clippedJson(metrics.nativeMetrics),
        });
      }
    }
  }
  return rows;
}

const SNAPSHOT_SPECS = [
  ["baseline", "cycle-baseline", 0, "baseline"],
  ["deployedIdle", "deployed-idle", 0, "initial"],
  ["loaded", "loaded", 0, "initial"],
  ["afterUndeployEarly", "after-undeploy-early", 1, "early"],
  ["afterUndeploy", "after-undeploy-final", 1, "final"],
  ["redeployedLoaded", "redeployed-loaded", 0, "redeploy"],
  ["afterFinalUndeployEarly", "after-final-undeploy-early", 2, "early"],
  ["afterFinalUndeploy", "after-final-undeploy-final", 2, "final"],
];

function snapshotRow(run, cycle, snapshotName, stage, undeployOrdinal, timing, snapshot) {
  const artifacts = snapshot?.diagnosticArtifacts ?? {};
  const targetContext = `/${run.provider}`;
  return {
    processRunId: run.processRunId,
    scenario: run.scenario ?? "default",
    provider: run.provider,
    engineProvider: run.engineProvider,
    fork: run.fork,
    block: run.block,
    orderPosition: run.orderPosition,
    cycle,
    snapshotName,
    lifecycleStage: stage,
    undeployOrdinal,
    observationTiming: timing,
    label: snapshot?.label,
    capturedAt: dateOrNull(snapshot?.capturedAt),
    forcedGcCount: finiteOrNull(snapshot?.forcedGcCount),
    heapUsedBytes: finiteOrNull(snapshot?.heapUsedBytes),
    heapCommittedBytes: finiteOrNull(snapshot?.heapCommittedBytes),
    nativeCommittedBytes: finiteOrNull(snapshot?.nativeCommittedBytes),
    webappClassloaderCount: finiteOrNull(snapshot?.webappClassloaderCount),
    webappClassloaderRows: joined(snapshot?.webappClassloaderRows),
    liveThreadCount: finiteOrNull(snapshot?.liveThreadCount),
    jcsThreadSignatureCount: asArray(snapshot?.jcsThreadSignatures).length,
    jcsThreadSignatures: joined(snapshot?.jcsThreadSignatures, (thread) => `${thread.signature ?? "jcs"}:${thread.name ?? "?"}#${thread.id ?? "?"}`),
    tomcatFindLeaksOccurrenceCount: finiteOrNull(snapshot?.tomcatFindLeaksOccurrenceCount),
    tomcatFindLeaksTargetContextCount: finiteOrNull(snapshot?.tomcatFindLeaksOccurrenceCountsByContext?.[targetContext]),
    tomcatFindLeaksContexts: joined(snapshot?.tomcatFindLeaksContexts),
    tomcatFindLeaksDetected: booleanOrNull(snapshot?.tomcatFindLeaksDetected),
    tomcatLogLineCountSinceUndeploy: finiteOrNull(snapshot?.tomcatLogLineCountSinceUndeploy),
    heapInfoArtifact: artifactFileName(artifacts.heapInfo),
    classloaderStatsArtifact: artifactFileName(artifacts.classloaderStats),
    threadDumpArtifact: artifactFileName(artifacts.threadDump),
    tomcatLogArtifact: artifactFileName(artifacts.tomcatLog),
    nativeMemoryArtifact: artifactFileName(artifacts.nativeMemory),
    classHistogramArtifact: artifactFileName(artifacts.classHistogram),
    tomcatFindLeaksArtifact: artifactFileName(artifacts.tomcatFindLeaks),
  };
}

function flattenSnapshots(raw) {
  const rows = [];
  for (const run of asArray(raw.processRuns)) {
    if (run.processBaseline) {
      rows.push(snapshotRow(run, 0, "processBaseline", "process-baseline", 0, "baseline", run.processBaseline));
    }
    for (const cycle of asArray(run.cycles)) {
      for (const [key, stage, undeployOrdinal, timing] of SNAPSHOT_SPECS) {
        if (cycle[key]) rows.push(snapshotRow(run, cycle.cycle, key, stage, undeployOrdinal, timing, cycle[key]));
      }
    }
  }
  return rows;
}

const THREAD_EVIDENCE_SPECS = [
  ["firstUndeployThreadEvidenceEarly", 1, "early"],
  ["firstUndeployThreadEvidenceFinal", 1, "final"],
  ["finalUndeployThreadEvidenceEarly", 2, "early"],
  ["finalUndeployThreadEvidenceFinal", 2, "final"],
];

function threadList(items) {
  return joined(items, (thread) => `${thread.name ?? "?"}#${thread.id ?? "?"}`);
}

function flattenThreadEvidence(raw) {
  const rows = [];
  for (const run of asArray(raw.processRuns)) {
    for (const cycle of asArray(run.cycles)) {
      for (const [sourceField, undeployOrdinal, observationTiming] of THREAD_EVIDENCE_SPECS) {
        const evidence = cycle[sourceField];
        if (!evidence) continue;
        rows.push({
          processRunId: run.processRunId,
          scenario: run.scenario ?? "default",
          provider: run.provider,
          fork: run.fork,
          block: run.block,
          orderPosition: run.orderPosition,
          cycle: cycle.cycle,
          sourceField,
          undeployOrdinal,
          observationTiming,
          threadStock: evidence.threadStock,
          threadStockDeltaVsProcessBaseline: evidence.threadStockDeltaVsProcessBaseline,
          threadStockDeltaVsCycleBaseline: evidence.threadStockDeltaVsCycleBaseline,
          threadsNotPresentAtProcessBaselineCount: asArray(evidence.threadsNotPresentAtProcessBaseline).length,
          threadsNotPresentAtProcessBaseline: threadList(evidence.threadsNotPresentAtProcessBaseline),
          threadsNotPresentAtCycleBaselineCount: asArray(evidence.threadsNotPresentAtCycleBaseline).length,
          threadsNotPresentAtCycleBaseline: threadList(evidence.threadsNotPresentAtCycleBaseline),
          candidateApplicationThreadsVsProcessBaselineCount: asArray(evidence.candidateApplicationThreadsVsProcessBaseline).length,
          candidateApplicationThreadsVsProcessBaseline: threadList(evidence.candidateApplicationThreadsVsProcessBaseline),
          candidateApplicationThreadsVsCycleBaselineCount: asArray(evidence.candidateApplicationThreadsVsCycleBaseline).length,
          candidateApplicationThreadsVsCycleBaseline: threadList(evidence.candidateApplicationThreadsVsCycleBaseline),
          jcsThreadSignatureCount: asArray(evidence.jcsThreadSignatures).length,
          jcsThreadSignatures: joined(evidence.jcsThreadSignatures, (thread) => `${thread.signature ?? "jcs"}:${thread.name ?? "?"}#${thread.id ?? "?"}`),
          classification: evidence.classification,
          classificationBasis: evidence.classificationBasis,
        });
      }
    }
  }
  return rows;
}

function flattenEvents(raw) {
  const rows = [];
  let eventId = 0;
  const push = (base) => rows.push({ eventId: ++eventId, ...base });
  const pushMessages = (run, cycle, aggregationLevel, undeployOrdinal, category, sourceField, messages) => {
    asArray(messages).forEach((message, index) => push({
      processRunId: run?.processRunId ?? null,
      scenario: run?.scenario ?? "default",
      provider: run?.provider ?? null,
      fork: run?.fork ?? null,
      block: run?.block ?? null,
      cycle: cycle?.cycle ?? null,
      aggregationLevel,
      undeployOrdinal,
      category,
      sourceField,
      occurrenceIndex: index + 1,
      context: null,
      message: clippedJson(message),
    }));
  };

  asArray(raw.infrastructureFailures).forEach((failure, index) => push({
    processRunId: failure.processRunId ?? null,
    scenario: failure.scenario ?? "default",
    provider: failure.provider ?? null,
    fork: failure.fork ?? null,
    block: failure.block ?? null,
    cycle: failure.cycle ?? null,
    aggregationLevel: "campaign",
    undeployOrdinal: null,
    category: "infrastructure-failure",
    sourceField: "infrastructureFailures",
    occurrenceIndex: index + 1,
    context: failure.stage ?? null,
    message: clippedJson(failure),
  }));

  for (const run of asArray(raw.processRuns)) {
    pushMessages(run, null, "process-run-aggregate", null, "warning", "warnings", run.warnings);
    pushMessages(run, null, "process-run-aggregate", null, "leak-warning", "leakWarnings", run.leakWarnings);
    pushMessages(run, null, "process-run-aggregate", null, "thread-leak-warning", "threadLeakWarnings", run.threadLeakWarnings);
    for (const cycle of asArray(run.cycles)) {
      const warningSets = [
        [1, "warning", "firstUndeployWarnings"],
        [1, "leak-warning", "firstUndeployLeakWarnings"],
        [1, "thread-leak-warning", "firstUndeployThreadLeakWarnings"],
        [2, "warning", "secondUndeployWarnings"],
        [2, "leak-warning", "secondUndeployLeakWarnings"],
        [2, "thread-leak-warning", "secondUndeployThreadLeakWarnings"],
      ];
      for (const [undeployOrdinal, category, sourceField] of warningSets) {
        pushMessages(run, cycle, "cycle-window", undeployOrdinal, category, sourceField, cycle[sourceField]);
      }
      for (const [undeployOrdinal, snapshotName] of [[1, "afterUndeploy"], [2, "afterFinalUndeploy"]]) {
        const snapshot = cycle[snapshotName] ?? {};
        asArray(snapshot.tomcatFindLeaksOccurrences).forEach((context, index) => push({
          processRunId: run.processRunId,
          scenario: run.scenario ?? "default",
          provider: run.provider,
          fork: run.fork,
          block: run.block,
          cycle: cycle.cycle,
          aggregationLevel: "cycle-observation",
          undeployOrdinal,
          category: "tomcat-findleaks-occurrence",
          sourceField: `${snapshotName}.tomcatFindLeaksOccurrences`,
          occurrenceIndex: index + 1,
          context,
          message: context,
        }));
      }
    }
  }
  return rows;
}

function observationMap(analysis) {
  return new Map(asArray(analysis.observations).map((row) => [
    `${row.processRunId}|${row.cycle}|${row.phase}`,
    row,
  ]));
}

function flattenQualityGates(raw, analysis) {
  const observations = observationMap(analysis);
  const rows = [];
  for (const run of asArray(raw.processRuns)) {
    for (const cycle of asArray(run.cycles)) {
      for (const [phase, gate, workload] of [
        ["initial", cycle.protocolValidation, cycle.workload],
        ["redeploy", cycle.redeployProtocolValidation, cycle.redeployWorkload],
      ]) {
        if (!gate) continue;
        const observation = observations.get(`${run.processRunId}|${cycle.cycle}|${phase}`) ?? {};
        const configuration = workload?.configuration ?? cycle.request ?? run.configuration ?? raw.configuration ?? {};
        const metrics = workload?.providerMetrics ?? {};
        const metricsAfterWorkload = workload?.providerMetricsAfterWorkload ?? {};
        const metricsAfterWriteProbe = workload?.providerMetricsAfterWriteProbe ?? {};
        rows.push({
          processRunId: run.processRunId,
          scenario: run.scenario ?? "default",
          provider: run.provider,
          fork: run.fork,
          block: run.block,
          orderPosition: run.orderPosition,
          cycle: cycle.cycle,
          phase,
          gateType: gate.gateType,
          blockValid: booleanOrNull(observation.blockValid),
          performanceComparisonEligible: booleanOrNull(gate.performanceComparisonEligible),
          completedOperations: booleanOrNull(gate.completedOperations),
          requiredOperations: gate.requiredOperations,
          measuredOperations: gate.measuredOperations,
          operationsPerSecond: workload?.operationsPerSecond,
          operationMeasurementsValid: booleanOrNull(gate.operationMeasurementsValid),
          providerMetricCheckpointsValid: booleanOrNull(gate.providerMetricCheckpointsValid),
          providerMetricsAliasMatchesPostWrite: JSON.stringify(metrics) === JSON.stringify(metricsAfterWriteProbe),
          requestedMeasurementNanos: gate.requestedMeasurementNanos,
          observedMeasurementNanos: gate.observedMeasurementNanos,
          measurementDurationPassed: booleanOrNull(gate.measurementDurationPassed),
          workloadType: configuration.workload,
          configuredHitPercent: configuration.hitPercent,
          expectedHitRate: gate.expectedHitRate,
          observedHitRate: gate.observedHitRate,
          hitRateWithinHalfPercentagePoint: booleanOrNull(gate.hitRateWithinHalfPercentagePoint),
          configuredEntries: configuration.entries,
          minimumExpectedEntriesAfterWorkload: gate.minimumExpectedEntriesAfterWorkload,
          observedEntriesAfterWorkload: gate.observedEntriesAfterWorkload ?? metricsAfterWorkload.currentEntries,
          capacityAfterWorkloadPassed: booleanOrNull(gate.capacityAfterWorkloadPassed),
          minimumExpectedEntriesAfterWriteProbe: gate.minimumExpectedEntriesAfterWriteProbe,
          expectedStoredEntries: gate.expectedStoredEntries,
          observedEntriesAfterWriteProbe: gate.observedEntriesAfterWriteProbe ?? metricsAfterWriteProbe.currentEntries,
          capacityAfterWriteProbePassed: booleanOrNull(gate.capacityAfterWriteProbePassed),
          capacityCheckPassed: booleanOrNull(gate.capacityCheckPassed),
          noEntriesRetained: booleanOrNull(gate.noEntriesRetained),
          noStoreHitRate: gate.hitRate ?? metrics.hitRate,
          zeroHits: booleanOrNull(gate.zeroHits),
          singleFlightGateApplicable: booleanOrNull(gate.singleFlightGateApplicable),
          loaderInvocationsUnderContention: workload?.loaderInvocationsUnderContention,
          singleFlightPassed: booleanOrNull(gate.singleFlightPassed),
          runnerPassed: booleanOrNull(gate.passed),
          observedMeasurementSecondsFormula: null,
          durationRatioFormula: null,
          absoluteHitRateDeltaPpFormula: null,
          operationMeasurementsValidRecomputedFormula: null,
          completedOperationsRecomputedFormula: null,
          durationGateRecomputedFormula: null,
          hitRateGateRecomputedFormula: null,
          minimumEntriesRecomputedFormula: null,
          minimumEntriesAfterWorkloadMatchesRunnerFormula: null,
          minimumEntriesAfterWriteProbeMatchesRunnerFormula: null,
          capacityAfterWorkloadRecomputedFormula: null,
          capacityAfterWriteProbeRecomputedFormula: null,
          capacityGateRecomputedFormula: null,
          noEntriesRecomputedFormula: null,
          zeroHitsRecomputedFormula: null,
          singleFlightRecomputedFormula: null,
          recomputedPassFormula: null,
          formulaMatchesRunner: null,
          expectedPerformanceInclusionFormula: null,
        });
      }
    }
  }
  return rows;
}

function flattenLifecycleCycles(raw) {
  const rows = [];
  for (const run of asArray(raw.processRuns)) {
    for (const cycle of asArray(run.cycles)) {
      const firstTiming = cycle.firstUndeployTiming ?? {};
      const finalTiming = cycle.finalUndeployTiming ?? {};
      rows.push({
        processRunId: run.processRunId,
        scenario: run.scenario ?? "default",
        provider: run.provider,
        fork: run.fork,
        block: run.block,
        orderPosition: run.orderPosition,
        cycle: cycle.cycle,
        deployMs: cycle.deployMs,
        undeployMs: cycle.undeployMs,
        redeployMs: cycle.redeployMs,
        secondUndeployMs: cycle.secondUndeployMs,
        redeployReady: booleanOrNull(cycle.redeployReady),
        redeployWorkloadPassed: booleanOrNull(cycle.redeployWorkloadPassed),
        redeployPassed: booleanOrNull(cycle.redeployPassed),
        firstEarlyTargetSeconds: firstTiming.earlyThreadTargetSecondsAfterUndeploy,
        firstEarlyStartedSeconds: firstTiming.earlyThreadStartedSecondsAfterUndeploy,
        firstEarlyCompletedSeconds: firstTiming.earlyThreadCompletedSecondsAfterUndeploy,
        firstFinalTargetSeconds: firstTiming.finalDiagnosticTargetSecondsAfterUndeploy,
        firstFinalStartedSeconds: firstTiming.finalDiagnosticStartedSecondsAfterUndeploy,
        firstFindLeaksCompletedSeconds: firstTiming.findLeaksCompletedSecondsAfterUndeploy,
        firstSnapshotCompletedSeconds: firstTiming.finalSnapshotCompletedSecondsAfterUndeploy,
        finalEarlyTargetSeconds: finalTiming.earlyThreadTargetSecondsAfterUndeploy,
        finalEarlyStartedSeconds: finalTiming.earlyThreadStartedSecondsAfterUndeploy,
        finalEarlyCompletedSeconds: finalTiming.earlyThreadCompletedSecondsAfterUndeploy,
        finalFinalTargetSeconds: finalTiming.finalDiagnosticTargetSecondsAfterUndeploy,
        finalFinalStartedSeconds: finalTiming.finalDiagnosticStartedSecondsAfterUndeploy,
        finalFindLeaksCompletedSeconds: finalTiming.findLeaksCompletedSecondsAfterUndeploy,
        finalSnapshotCompletedSeconds: finalTiming.finalSnapshotCompletedSecondsAfterUndeploy,
        cacheHeapDeltaBytes: cycle.cacheHeapDeltaBytes,
        retainedHeapBytes: cycle.retainedHeapBytes,
        finalClassloaderCountAtOrBelowCycleBaseline: booleanOrNull(cycle.finalClassloaderCountAtOrBelowCycleBaseline),
        firstUndeployTargetFindleaksObserved: booleanOrNull(cycle.tomcatFindLeaksTargetContextObservedAfterFirstUndeploy),
        finalUndeployTargetFindleaksObserved: booleanOrNull(cycle.tomcatFindLeaksTargetContextObservedAfterFinalUndeploy),
        finalThreadCountAtOrBelowCycleBaseline: booleanOrNull(cycle.finalThreadCountAtOrBelowCycleBaseline),
        candidateApplicationThreadCountAfterFinalUndeploy: asArray(cycle.candidateApplicationThreadsAfterFinalUndeploy).length,
        candidateApplicationThreadsAfterFinalUndeploy: threadList(cycle.candidateApplicationThreadsAfterFinalUndeploy),
        noCandidateApplicationThreadSignalAfterFinalUndeploy: booleanOrNull(cycle.noCandidateApplicationThreadSignalAfterFinalUndeploy),
      });
    }
  }
  return rows;
}

const RUN_COLUMNS = [
  descriptor("processRunId", "processRunId", { definition: "Identificativo univoco della JVM/container indipendente.", width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { definition: "Condizione sperimentale richiesta.", width: 13 }),
  descriptor("engineProvider", "engineProvider", { definition: "Adapter/motore attivato nella web application.", width: 14 }),
  descriptor("studyRole", "studyRole", { definition: "Ruolo prespecificato della condizione nello studio.", width: 34 }),
  descriptor("fork", "fork", { type: "integer", definition: "Indice della JVM indipendente.", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", definition: "Blocco appaiato del disegno Williams.", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", definition: "Posizione del provider nel blocco.", width: 12, format: "0" }),
  descriptor("williamsRow", "Williams row", { type: "integer", width: 12, format: "0" }),
  descriptor("startedAt", "startedAt (UTC)", { type: "date", width: 22, format: "yyyy-mm-dd hh:mm:ss" }),
  descriptor("finishedAt", "finishedAt (UTC)", { type: "date", width: 22, format: "yyyy-mm-dd hh:mm:ss" }),
  descriptor("durationSecondsFormula", "duration (s, formula)", { type: "duration", source: SOURCE_FORMULA, definition: "Durata della process run calcolata da finishedAt - startedAt.", width: 15, format: "#,##0.0" }),
  descriptor("containerId", "containerId", { width: 38 }),
  descriptor("dockerImageId", "dockerImageId", { width: 38 }),
  descriptor("containerImageName", "container image", { width: 24 }),
  descriptor("containerStartedAt", "containerStartedAt (UTC)", { type: "date", width: 22, format: "yyyy-mm-dd hh:mm:ss" }),
  descriptor("containerCpuLimit", "CPU limit (cores)", { type: "number", unit: "core", width: 13, format: "0.0" }),
  descriptor("containerCpuModel", "CPU model", { definition: "Modello CPU visibile all'interno del container.", width: 38 }),
  descriptor("containerVisibleProcessors", "visible processors", { type: "integer", unit: "logical processor", width: 16, format: "0" }),
  descriptor("containerMemoryLimitBytes", "memory limit (bytes)", { type: "bytes", unit: "byte", width: 18, format: "#,##0" }),
  descriptor("containerMemoryLimitMiBFormula", "memory limit (MiB, formula)", { type: "number", unit: "MiB", source: SOURCE_FORMULA, definition: "Limite memoria convertito da byte a MiB.", width: 18, format: "#,##0.0" }),
  descriptor("containerOS", "container OS", { width: 24 }),
  descriptor("containerKernel", "container kernel (uname -a)", { width: 52, wrap: true }),
  descriptor("dockerServerVersion", "Docker server version", { width: 19 }),
  descriptor("dockerServerOperatingSystem", "Docker server OS", { width: 30 }),
  descriptor("dockerServerKernelVersion", "Docker server kernel", { width: 30 }),
  descriptor("dockerServerArchitecture", "Docker server architecture", { width: 18 }),
  descriptor("dockerServerName", "Docker server name", { width: 22 }),
  descriptor("tomcatVersion", "Tomcat version", { width: 24 }),
  descriptor("osName", "kernel OS", { width: 14 }),
  descriptor("osVersion", "kernel version", { width: 32 }),
  descriptor("osArchitecture", "architecture", { width: 12 }),
  descriptor("jvmVersion", "JVM version", { width: 20 }),
  descriptor("jvmVendor", "JVM vendor", { width: 20 }),
  descriptor("javaOptions", "Java options", { width: 46, wrap: true }),
  descriptor("jvmCommandLine", "JVM command line", { definition: "Output JVM archiviato; testo integrale registrato dalla process run.", width: 72, wrap: true }),
  descriptor("jvmFlags", "JVM flags", { definition: "Flag effettivi della JVM registrati dalla process run.", width: 72, wrap: true }),
  descriptor("providerVersionRuntime", "provider version (runtime field)", { definition: "Valore runtime disponibile nel JSON solo per JCS4/JCS 3.2.1; vuoto per gli altri provider.", width: 24 }),
  descriptor("providerVersionPrespecified", "provider version (prespecificata)", { source: "Protocollo v4.2", definition: "Versione dichiarata prima della campagna; non viene presentata come rilevazione runtime quando il JSON non la espone.", width: 25 }),
  descriptor("providerVersionEvidence", "provider-version evidence", { source: "Protocollo v4.2", definition: "Origine e limite dell'informazione di versione.", width: 48, wrap: true }),
  descriptor("imageJcs4RevisionLabel", "image JCS4 revision label", { width: 40 }),
  descriptor("requestedRuntimeImage", "requested runtime image", { width: 34 }),
  descriptor("runtimeBaseImageReference", "runtime image immutable reference", { width: 58 }),
  descriptor("runtimeBaseImagePinnedDigest", "runtime image pinned digest", { width: 48 }),
  descriptor("runtimeBaseImageInspectionAvailable", "runtime image inspected", { type: "boolean", width: 18 }),
  descriptor("runtimeBaseImageId", "runtime base image ID", { width: 42 }),
  descriptor("requestedBuildImage", "requested build image", { width: 34 }),
  descriptor("buildBaseImageReference", "build image immutable reference", { width: 58 }),
  descriptor("buildBaseImagePinnedDigest", "build image pinned digest", { width: 48 }),
  descriptor("buildBaseImageInspectionAvailable", "build image inspected", { type: "boolean", width: 18 }),
  descriptor("buildBaseImageId", "build base image ID", { width: 42 }),
  descriptor("jcs4Version", "JCS4 version", { width: 18 }),
  descriptor("jcs4SourceCommit", "JCS4 source commit", { width: 40 }),
  descriptor("jcs4ArtifactSha256", "JCS4 artifact SHA-256", { width: 40 }),
  descriptor("jcs321Version", "JCS 3 version", { width: 14 }),
  descriptor("jcs321ArtifactSha256", "JCS 3 artifact SHA-256", { width: 40 }),
  descriptor("warSha256", "WAR SHA-256", { width: 40 }),
  descriptor("artifactManifestJson", "artifact manifest: basename + SHA-256 (JSON)", { definition: "Manifest appiattito a basename e checksum; i containerPath completi restano nel JSON autorevole.", width: 72, wrap: true }),
  descriptor("effectivePomFile", "effective POM file", { width: 22 }),
  descriptor("effectivePomSha256", "effective POM SHA-256", { width: 40 }),
  descriptor("effectivePomSizeBytes", "effective POM size (bytes)", { type: "bytes", unit: "byte", width: 19, format: "#,##0" }),
  descriptor("dependencyTreeFile", "dependency tree file", { width: 22 }),
  descriptor("dependencyTreeSha256", "dependency tree SHA-256", { width: 40 }),
  descriptor("dependencyTreeSizeBytes", "dependency tree size (bytes)", { type: "bytes", unit: "byte", width: 20, format: "#,##0" }),
  descriptor("buildProvenanceFile", "build provenance file", { width: 25 }),
  descriptor("buildProvenanceSha256", "build provenance SHA-256", { width: 40 }),
  descriptor("buildProvenanceSizeBytes", "build provenance size (bytes)", { type: "bytes", unit: "byte", width: 21, format: "#,##0" }),
  descriptor("provenanceValidationPassed", "provenance valid", { type: "boolean", definition: "Esito dei controlli su immagine, commit e artefatti incorporati.", width: 14 }),
  descriptor("provenanceValidationErrors", "provenance errors", { width: 42, wrap: true }),
  descriptor("cycleCount", "cycles", { type: "integer", width: 9, format: "0" }),
  descriptor("warningCount", "warnings", { type: "integer", width: 10, format: "0" }),
  descriptor("leakWarningCount", "leak warnings", { type: "integer", width: 12, format: "0" }),
  descriptor("threadLeakWarningCount", "thread-leak warnings", { type: "integer", width: 15, format: "0" }),
  descriptor("finalHeapDumpPolicy", "heap-dump policy", { width: 14 }),
  descriptor("finalHeapDumpFile", "final heap dump", { width: 46 }),
  descriptor("finalHeapDumpSha256", "heap dump SHA-256", { width: 40 }),
  descriptor("finalHeapDumpSizeBytes", "heap dump size (bytes)", { type: "bytes", unit: "byte", width: 18, format: "#,##0" }),
];

const WORKLOAD_COLUMNS = [
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("engineProvider", "engineProvider", { width: 14 }),
  descriptor("studyRole", "studyRole", { width: 34 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("phase", "phase", { definition: "Finestra iniziale o successiva al redeploy.", width: 11 }),
  descriptor("gateType", "gateType", { width: 20 }),
  descriptor("performanceComparisonEligible", "performance eligible", { type: "boolean", width: 16 }),
  descriptor("requestSeed", "requestSeed", { type: "integer", definition: "Seed appaiato per blocco e ciclo.", width: 14, format: "0" }),
  descriptor("accessPlanSha256", "access-plan SHA-256", { definition: "Hash del piano di accesso deterministico.", width: 40 }),
  descriptor("entries", "cache size (entries)", { type: "integer", unit: "entry", width: 15, format: "#,##0" }),
  descriptor("operationsRequested", "operation-plan size (configured)", { type: "integer", unit: "operation", definition: "Dimensione prespecificata del piano (400000). Il runner a durata ripete il piano, quindi measuredOperations può essere maggiore.", width: 23, format: "#,##0" }),
  descriptor("threads", "client workers", { type: "integer", unit: "thread", width: 13, format: "0" }),
  descriptor("hitPercent", "target hit rate (%)", { type: "number", unit: "%", width: 15, format: "0.0" }),
  descriptor("payloadBytes", "payload (bytes)", { type: "bytes", unit: "byte", width: 14, format: "#,##0" }),
  descriptor("warmupOperationsRequested", "warmup operations requested", { type: "integer", unit: "operation", width: 19, format: "#,##0" }),
  descriptor("warmupSecondsRequested", "warmup requested (s)", { type: "duration", unit: "s", width: 16, format: "0.000" }),
  descriptor("measurementSecondsRequested", "measurement requested (s)", { type: "duration", unit: "s", width: 18, format: "0.000" }),
  descriptor("ttlSeconds", "TTL (s)", { type: "duration", unit: "s", width: 10, format: "#,##0" }),
  descriptor("workloadType", "workload", { width: 12 }),
  descriptor("writePercent", "writePercent configured (%)", { type: "number", unit: "%", definition: "Parametro conservato nella richiesta; con workload=uniform non viene applicato alla finestra cronometrata.", width: 21, format: "0.0" }),
  descriptor("jcsMemoryMode", "JCS memory mode", { width: 16 }),
  descriptor("latencySampleRate", "latency sample 1/N", { type: "integer", width: 15, format: "0" }),
  descriptor("warmupOperationsExecuted", "warmup operations executed", { type: "integer", unit: "operation", width: 20, format: "#,##0" }),
  descriptor("warmupNanos", "warmup (ns)", { type: "duration", unit: "ns", width: 16, format: "#,##0" }),
  descriptor("warmupOvershootNanos", "warmup overshoot (ns)", { type: "duration", unit: "ns", width: 18, format: "#,##0" }),
  descriptor("fillOperationsPerSecond", "fill throughput (ops/s)", { type: "number", unit: "operation/s", width: 18, format: "#,##0" }),
  descriptor("operationsPerSecond", "throughput (ops/s)", { type: "number", unit: "operation/s", definition: "Throughput totale osservato nella finestra cronometrata.", width: 18, format: "#,##0" }),
  descriptor("measuredOperations", "measured operations", { type: "integer", unit: "operation", width: 18, format: "#,##0" }),
  descriptor("measurementNanos", "measurement (ns)", { type: "duration", unit: "ns", width: 18, format: "#,##0" }),
  descriptor("measurementOvershootNanos", "measurement overshoot (ns)", { type: "duration", unit: "ns", width: 21, format: "#,##0" }),
  descriptor("readOperationsPerSecond", "read throughput (ops/s)", { type: "number", unit: "operation/s", width: 19, format: "#,##0" }),
  descriptor("readOperations", "read operations", { type: "integer", unit: "operation", width: 16, format: "#,##0" }),
  descriptor("concurrentWriteOperations", "timed concurrent writes (uniform=0)", { type: "integer", unit: "operation", definition: "Deve essere zero nella campagna uniforme; le scritture della sonda semantica sono separate.", width: 24, format: "#,##0" }),
  descriptor("writeProbeOperationsPerSecond", "write-probe throughput (ops/s)", { type: "number", unit: "operation/s", definition: "Sonda separata; non entra nel confronto prestazionale primario.", width: 21, format: "#,##0" }),
  descriptor("latencyP50Nanos", "latency p50 (ns)", { type: "duration", unit: "ns", width: 15, format: "#,##0" }),
  descriptor("latencyP95Nanos", "latency p95 (ns)", { type: "duration", unit: "ns", width: 15, format: "#,##0" }),
  descriptor("latencyP99Nanos", "latency p99 (ns)", { type: "duration", unit: "ns", width: 15, format: "#,##0" }),
  descriptor("measuredLatencySamples", "latency samples", { type: "integer", unit: "sample", width: 15, format: "#,##0" }),
  descriptor("loaderInvocationsUnderContention", "loader calls under contention", { type: "integer", unit: "call", width: 20, format: "#,##0" }),
  descriptor("singleFlightPassed", "single-flight passed", { type: "boolean", width: 16 }),
  descriptor("observedEntriesAfterWorkload", "entries after workload", { type: "integer", unit: "entry", definition: "Primo checkpoint v4.2, acquisito prima della write probe.", width: 18, format: "#,##0" }),
  descriptor("observedHitRateAfterWorkload", "hit rate after workload", { type: "percent", unit: "fraction", definition: "Hit rate usato dal gate semantico v4.2, prima della write probe.", width: 18, format: "0.000%" }),
  descriptor("observedEntriesAfterWriteProbe", "entries after write probe", { type: "integer", unit: "entry", definition: "Secondo checkpoint v4.2, acquisito dopo la sonda di scrittura separata.", width: 19, format: "#,##0" }),
  descriptor("observedHitRateAfterWriteProbe", "hit rate after write probe", { type: "percent", unit: "fraction", width: 19, format: "0.000%" }),
  descriptor("providerMetricsAliasMatchesPostWrite", "legacy metrics = post-write", { type: "boolean", definition: "Verifica che providerMetrics conservi il significato storico di alias del checkpoint post-write.", width: 19 }),
  descriptor("providerMetricsAfterWorkloadJson", "metrics after workload (JSON)", { definition: "Checkpoint completo prima della write probe.", width: 54, wrap: true }),
  descriptor("providerMetricsAfterWriteProbeJson", "metrics after write probe (JSON)", { definition: "Checkpoint completo dopo la write probe.", width: 54, wrap: true }),
  descriptor("currentEntries", "legacy alias entries (post-write)", { type: "integer", unit: "entry", width: 20, format: "#,##0" }),
  descriptor("requestCount", "provider requests", { type: "integer", unit: "request", width: 16, format: "#,##0" }),
  descriptor("hitCount", "hits", { type: "integer", unit: "request", width: 13, format: "#,##0" }),
  descriptor("missCount", "misses", { type: "integer", unit: "request", width: 13, format: "#,##0" }),
  descriptor("hitRate", "legacy alias hit rate (post-write)", { type: "percent", unit: "fraction", width: 20, format: "0.000%" }),
  descriptor("loadSuccessCount", "load successes", { type: "integer", unit: "event", width: 15, format: "#,##0" }),
  descriptor("loadFailureCount", "load failures", { type: "integer", unit: "event", width: 14, format: "#,##0" }),
  descriptor("totalLoadTimeNanos", "total load time (ns)", { type: "duration", unit: "ns", width: 17, format: "#,##0" }),
  descriptor("evictionCount", "evictions", { type: "integer", unit: "event", width: 13, format: "#,##0" }),
  descriptor("expirationCount", "expirations", { type: "integer", unit: "event", width: 13, format: "#,##0" }),
  descriptor("putCount", "puts", { type: "integer", unit: "event", width: 13, format: "#,##0" }),
  descriptor("removeCount", "removes", { type: "integer", unit: "event", width: 13, format: "#,##0" }),
  descriptor("nativeMetricsJson", "native provider metrics (JSON)", { width: 54, wrap: true }),
];

const SNAPSHOT_COLUMNS = [
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("engineProvider", "engineProvider", { width: 14 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("snapshotName", "snapshot JSON key", { definition: "Nome strutturale del campo nel JSON; non è il nome completo della cattura.", width: 27 }),
  descriptor("lifecycleStage", "lifecycle stage", { width: 27 }),
  descriptor("undeployOrdinal", "undeploy ordinal", { type: "integer", width: 14, format: "0" }),
  descriptor("observationTiming", "observation timing", { width: 16 }),
  descriptor("label", "full snapshot label", { definition: "Identificativo completo emesso dal runner, comprendente campagna, process run, ciclo e checkpoint.", width: 72 }),
  descriptor("capturedAt", "capturedAt (UTC)", { type: "date", width: 22, format: "yyyy-mm-dd hh:mm:ss" }),
  descriptor("forcedGcCount", "forced GC count", { type: "integer", unit: "event", width: 14, format: "0" }),
  descriptor("heapUsedBytes", "heap used (bytes)", { type: "bytes", unit: "byte", width: 17, format: "#,##0" }),
  descriptor("heapCommittedBytes", "heap committed (bytes)", { type: "bytes", unit: "byte", width: 20, format: "#,##0" }),
  descriptor("nativeCommittedBytes", "NMT committed (bytes)", { type: "bytes", unit: "byte", definition: "Committed totale da VM.native_memory summary.", width: 19, format: "#,##0" }),
  descriptor("webappClassloaderCount", "webapp classloader rows", { type: "integer", unit: "row", definition: "Conteggio testuale delle righe ParallelWebappClassLoader, non conteggio diretto degli oggetti trattenuti.", width: 18, format: "0" }),
  descriptor("webappClassloaderRows", "classloader rows (text)", { width: 60, wrap: true }),
  descriptor("liveThreadCount", "live threads", { type: "integer", unit: "thread", width: 13, format: "0" }),
  descriptor("jcsThreadSignatureCount", "JCS thread signatures", { type: "integer", unit: "thread", width: 17, format: "0" }),
  descriptor("jcsThreadSignatures", "JCS thread evidence", { width: 54, wrap: true }),
  descriptor("tomcatFindLeaksOccurrenceCount", "findleaks checkpoint occurrences", { type: "integer", unit: "occurrence", width: 21, format: "0" }),
  descriptor("tomcatFindLeaksTargetContextCount", "positive target-context occurrences", { type: "integer", unit: "occurrence", width: 23, format: "0" }),
  descriptor("tomcatFindLeaksContexts", "positive findleaks contexts", { width: 32, wrap: true }),
  descriptor("tomcatFindLeaksDetected", "findleaks checkpoint positive", { type: "boolean", definition: "TRUE indica che il checkpoint diagnostico ha restituito almeno un'occorrenza; non è da solo un verdetto causale di leak.", width: 21 }),
  descriptor("tomcatLogLineCountSinceUndeploy", "Tomcat log lines since undeploy", { type: "integer", unit: "line", width: 21, format: "#,##0" }),
  descriptor("heapInfoArtifact", "heap-info artifact", { width: 54 }),
  descriptor("classloaderStatsArtifact", "classloader artifact", { width: 54 }),
  descriptor("threadDumpArtifact", "thread-dump artifact", { width: 54 }),
  descriptor("tomcatLogArtifact", "Tomcat log artifact", { definition: "Basename del log Tomcat archiviato per il checkpoint precoce; il JSON autorevole conserva il riferimento originale.", width: 54 }),
  descriptor("nativeMemoryArtifact", "NMT artifact", { width: 54 }),
  descriptor("classHistogramArtifact", "class-histogram artifact", { width: 54 }),
  descriptor("tomcatFindLeaksArtifact", "findleaks artifact", { width: 54 }),
];

const THREAD_COLUMNS = [
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("sourceField", "evidence source", { width: 34 }),
  descriptor("undeployOrdinal", "undeploy ordinal", { type: "integer", width: 14, format: "0" }),
  descriptor("observationTiming", "timing", { width: 11 }),
  descriptor("threadStock", "thread stock", { type: "integer", unit: "thread", width: 12, format: "0" }),
  descriptor("threadStockDeltaVsProcessBaseline", "Δ threads vs process baseline", { type: "integer", unit: "thread", width: 20, format: "+0;-0;0" }),
  descriptor("threadStockDeltaVsCycleBaseline", "Δ threads vs cycle baseline", { type: "integer", unit: "thread", width: 19, format: "+0;-0;0" }),
  descriptor("threadsNotPresentAtProcessBaselineCount", "new vs process count", { type: "integer", unit: "thread", width: 17, format: "0" }),
  descriptor("threadsNotPresentAtProcessBaseline", "new vs process threads", { width: 56, wrap: true }),
  descriptor("threadsNotPresentAtCycleBaselineCount", "new vs cycle count", { type: "integer", unit: "thread", width: 16, format: "0" }),
  descriptor("threadsNotPresentAtCycleBaseline", "new vs cycle threads", { width: 56, wrap: true }),
  descriptor("candidateApplicationThreadsVsProcessBaselineCount", "candidate app threads vs process", { type: "integer", unit: "thread", width: 22, format: "0" }),
  descriptor("candidateApplicationThreadsVsProcessBaseline", "candidate app thread names vs process", { width: 58, wrap: true }),
  descriptor("candidateApplicationThreadsVsCycleBaselineCount", "candidate app threads vs cycle", { type: "integer", unit: "thread", width: 21, format: "0" }),
  descriptor("candidateApplicationThreadsVsCycleBaseline", "candidate app thread names vs cycle", { width: 58, wrap: true }),
  descriptor("jcsThreadSignatureCount", "JCS signature count", { type: "integer", unit: "thread", width: 16, format: "0" }),
  descriptor("jcsThreadSignatures", "JCS signatures", { width: 54, wrap: true }),
  descriptor("classification", "classification", { width: 24 }),
  descriptor("classificationBasis", "classification basis", { width: 62, wrap: true }),
];

const EVENT_COLUMNS = [
  descriptor("eventId", "eventId", { type: "integer", width: 10, format: "0" }),
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("aggregationLevel", "aggregation level", { definition: "Distingue occorrenze di finestra, aggregati di process run e fallimenti di campagna.", width: 20 }),
  descriptor("undeployOrdinal", "undeploy ordinal", { type: "integer", width: 14, format: "0" }),
  descriptor("category", "event category", { width: 25 }),
  descriptor("sourceField", "source field", { width: 43 }),
  descriptor("occurrenceIndex", "occurrence index", { type: "integer", width: 14, format: "0" }),
  descriptor("context", "context", { width: 22 }),
  descriptor("message", "raw message / payload", { definition: "Testo preservato; categorie aggregate possono ripetere la stessa riga intenzionalmente.", width: 92, wrap: true }),
];

const QC_COLUMNS = [
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("phase", "phase", { width: 11 }),
  descriptor("gateType", "gateType", { width: 20 }),
  descriptor("blockValid", "block valid", { type: "boolean", source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("performanceComparisonEligible", "performance eligible", { type: "boolean", width: 16 }),
  descriptor("completedOperations", "operations completed (runner)", { type: "boolean", width: 19 }),
  descriptor("requiredOperations", "required operations (runner)", { type: "integer", unit: "operation", width: 19, format: "#,##0" }),
  descriptor("measuredOperations", "measured operations", { type: "integer", unit: "operation", width: 18, format: "#,##0" }),
  descriptor("operationsPerSecond", "throughput (ops/s)", { type: "number", unit: "operation/s", width: 17, format: "#,##0" }),
  descriptor("operationMeasurementsValid", "operation measurements valid (runner)", { type: "boolean", width: 22 }),
  descriptor("providerMetricCheckpointsValid", "metric checkpoints valid (runner)", { type: "boolean", width: 21 }),
  descriptor("providerMetricsAliasMatchesPostWrite", "legacy metrics = post-write", { type: "boolean", definition: "Controllo strutturale del builder sull'alias providerMetrics.", width: 19 }),
  descriptor("requestedMeasurementNanos", "requested duration (ns)", { type: "duration", unit: "ns", width: 19, format: "#,##0" }),
  descriptor("observedMeasurementNanos", "observed duration (ns)", { type: "duration", unit: "ns", width: 19, format: "#,##0" }),
  descriptor("measurementDurationPassed", "duration gate (runner)", { type: "boolean", width: 17 }),
  descriptor("workloadType", "workload", { width: 12 }),
  descriptor("configuredHitPercent", "target hit rate (%)", { type: "number", unit: "%", width: 15, format: "0.0" }),
  descriptor("expectedHitRate", "expected hit rate", { type: "percent", unit: "fraction", width: 15, format: "0.000%" }),
  descriptor("observedHitRate", "observed hit rate", { type: "percent", unit: "fraction", width: 15, format: "0.000%" }),
  descriptor("hitRateWithinHalfPercentagePoint", "hit-rate gate (runner)", { type: "boolean", width: 17 }),
  descriptor("configuredEntries", "configured entries", { type: "integer", unit: "entry", width: 16, format: "#,##0" }),
  descriptor("minimumExpectedEntriesAfterWorkload", "minimum entries after workload", { type: "integer", unit: "entry", width: 20, format: "#,##0" }),
  descriptor("observedEntriesAfterWorkload", "entries after workload", { type: "integer", unit: "entry", width: 18, format: "#,##0" }),
  descriptor("capacityAfterWorkloadPassed", "post-workload capacity (runner)", { type: "boolean", width: 21 }),
  descriptor("minimumExpectedEntriesAfterWriteProbe", "minimum entries after write probe", { type: "integer", unit: "entry", width: 21, format: "#,##0" }),
  descriptor("expectedStoredEntries", "expected stored entries", { type: "integer", unit: "entry", width: 17, format: "#,##0" }),
  descriptor("observedEntriesAfterWriteProbe", "entries after write probe", { type: "integer", unit: "entry", width: 19, format: "#,##0" }),
  descriptor("capacityAfterWriteProbePassed", "post-write capacity (runner)", { type: "boolean", width: 20 }),
  descriptor("capacityCheckPassed", "both capacity gates (runner)", { type: "boolean", definition: "AND dei checkpoint post-workload e post-write.", width: 19 }),
  descriptor("noEntriesRetained", "no entries retained (runner)", { type: "boolean", width: 20 }),
  descriptor("noStoreHitRate", "no-store hit rate", { type: "percent", unit: "fraction", width: 15, format: "0.000%" }),
  descriptor("zeroHits", "zero-hits gate (runner)", { type: "boolean", width: 17 }),
  descriptor("singleFlightGateApplicable", "single-flight applicable", { type: "boolean", width: 18 }),
  descriptor("loaderInvocationsUnderContention", "loader calls under contention", { type: "integer", unit: "call", width: 21, format: "0" }),
  descriptor("singleFlightPassed", "single-flight gate (runner)", { type: "boolean", width: 20 }),
  descriptor("runnerPassed", "runner gate result", { type: "boolean", width: 15 }),
  descriptor("observedMeasurementSecondsFormula", "observed duration (s, formula)", { type: "duration", unit: "s", source: SOURCE_FORMULA, width: 19, format: "0.000" }),
  descriptor("durationRatioFormula", "observed/requested (formula)", { type: "number", source: SOURCE_FORMULA, width: 19, format: "0.000" }),
  descriptor("absoluteHitRateDeltaPpFormula", "|hit-rate Δ| (pp, formula)", { type: "number", unit: "percentage point", source: SOURCE_FORMULA, width: 18, format: "0.000" }),
  descriptor("operationMeasurementsValidRecomputedFormula", "operation measurements valid (formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "Richieste > 0, misurate >= 0 e throughput finito positivo.", width: 23 }),
  descriptor("completedOperationsRecomputedFormula", "operations completed (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "Misurazioni valide e measuredOperations >= requiredOperations.", width: 24 }),
  descriptor("durationGateRecomputedFormula", "duration gate (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "requested=0 oppure observed>=requested.", width: 21 }),
  descriptor("hitRateGateRecomputedFormula", "hit-rate gate (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "Per uniform: scarto assoluto dal target <= 0,005; per altri workload il controllo è non applicabile e restituisce TRUE.", width: 22 }),
  descriptor("minimumEntriesRecomputedFormula", "minimum entries (numeric formula)", { type: "integer", unit: "entry", source: SOURCE_FORMULA, definition: "INT(configuredEntries*0,99).", width: 22, format: "#,##0" }),
  descriptor("minimumEntriesAfterWorkloadMatchesRunnerFormula", "post-workload minimum = runner", { type: "boolean", source: SOURCE_FORMULA, width: 22 }),
  descriptor("minimumEntriesAfterWriteProbeMatchesRunnerFormula", "post-write minimum = runner", { type: "boolean", source: SOURCE_FORMULA, width: 21 }),
  descriptor("capacityAfterWorkloadRecomputedFormula", "post-workload capacity (formula)", { type: "boolean", source: SOURCE_FORMULA, width: 22 }),
  descriptor("capacityAfterWriteProbeRecomputedFormula", "post-write capacity (formula)", { type: "boolean", source: SOURCE_FORMULA, width: 21 }),
  descriptor("capacityGateRecomputedFormula", "both capacity gates (formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "AND dei due checkpoint di capacità.", width: 22 }),
  descriptor("noEntriesRecomputedFormula", "no-store empty at both checkpoints (formula)", { type: "boolean", source: SOURCE_FORMULA, width: 24 }),
  descriptor("zeroHitsRecomputedFormula", "no-store zero hits (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, width: 21 }),
  descriptor("singleFlightRecomputedFormula", "single-flight (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "loaderInvocationsUnderContention = 1.", width: 22 }),
  descriptor("recomputedPassFormula", "recomputed gate (numeric formula)", { type: "boolean", source: SOURCE_FORMULA, definition: "Ricostruzione esclusivamente numerica dell'esito complessivo.", width: 21 }),
  descriptor("formulaMatchesRunner", "all numeric gates = runner", { type: "boolean", source: SOURCE_FORMULA, definition: "Confronta ogni sotto-gate ricalcolato e il risultato complessivo con i flag del runner; ogni riga deve essere TRUE prima dell'export.", width: 22 }),
  descriptor("expectedPerformanceInclusionFormula", "expected performance inclusion", { type: "boolean", source: SOURCE_FORMULA, definition: "TRUE solo se blocco valido, provider eleggibile e gate superato.", width: 21 }),
];

const PERFORMANCE_SUMMARY_COLUMNS = [
  descriptor("scenario", "scenario", { source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("phase", "phase", { source: SOURCE_ANALYSIS, width: 11 }),
  descriptor("analysisSet", "analysis set", { source: SOURCE_ANALYSIS, width: 28 }),
  descriptor("statisticalUnit", "statistical unit", { source: SOURCE_ANALYSIS, width: 31 }),
  descriptor("studyRole", "study role", { source: SOURCE_ANALYSIS, width: 34 }),
  descriptor("forkCount", "valid forks", { type: "integer", source: SOURCE_ANALYSIS, width: 11, format: "0" }),
  descriptor("observedForkCount", "observed forks", { type: "integer", source: SOURCE_ANALYSIS, width: 13, format: "0" }),
  descriptor("invalidBlockForkCount", "invalid-block forks", { type: "integer", source: SOURCE_ANALYSIS, width: 15, format: "0" }),
  descriptor("semanticGatePassForkCount", "semantic-gate forks", { type: "integer", source: SOURCE_ANALYSIS, width: 16, format: "0" }),
  descriptor("performanceComparisonEligible", "performance eligible", { type: "boolean", source: SOURCE_ANALYSIS, width: 16 }),
  descriptor("performanceIncludedForkCount", "included forks", { type: "integer", source: SOURCE_ANALYSIS, width: 13, format: "0" }),
  descriptor("operationsPerSecondN", "throughput N", { type: "integer", unit: "fork", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("operationsPerSecondMedian", "throughput median (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("operationsPerSecondMean", "throughput mean (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("operationsPerSecondSampleStandardDeviation", "throughput sample SD", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("operationsPerSecondFirstQuartile", "throughput Q1 (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("operationsPerSecondThirdQuartile", "throughput Q3 (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("operationsPerSecondMinimum", "throughput min (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("operationsPerSecondMaximum", "throughput max (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
  descriptor("fillOperationsPerSecondMedian", "fill median (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("latencyP50NanosMedian", "p50 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 15, format: "#,##0" }),
  descriptor("latencyP95NanosMedian", "p95 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 15, format: "#,##0" }),
  descriptor("latencyP99NanosN", "p99 N", { type: "integer", unit: "fork", source: SOURCE_ANALYSIS, width: 10, format: "0" }),
  descriptor("latencyP99NanosMedian", "p99 median (raw ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("latencyP99MicrosMedianFormula", "p99 median (µs, formula)", { type: "number", unit: "µs", source: SOURCE_FORMULA, definition: "Conversione da nanosecondi usando la costante visibile nel foglio Readme-Protocol.", width: 18, format: "#,##0.000" }),
  descriptor("latencyP99NanosMean", "p99 mean (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 15, format: "#,##0" }),
  descriptor("latencyP99NanosSampleStandardDeviation", "p99 sample SD (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("latencyP99NanosFirstQuartile", "p99 Q1 (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 13, format: "#,##0" }),
  descriptor("latencyP99NanosThirdQuartile", "p99 Q3 (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 13, format: "#,##0" }),
  descriptor("latencyP99NanosMinimum", "p99 min (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 13, format: "#,##0" }),
  descriptor("latencyP99NanosMaximum", "p99 max (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 13, format: "#,##0" }),
  descriptor("measuredLatencySamplesMedian", "latency samples median", { type: "number", unit: "sample", source: SOURCE_ANALYSIS, width: 18, format: "#,##0" }),
];

const PERFORMANCE_FORK_COLUMNS = [
  descriptor("processRunId", "processRunId", { source: SOURCE_ANALYSIS, width: 54 }),
  descriptor("scenario", "scenario", { source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("fork", "fork", { type: "integer", source: SOURCE_ANALYSIS, width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("phase", "phase", { source: SOURCE_ANALYSIS, width: 11 }),
  descriptor("analysisSet", "analysis set", { source: SOURCE_ANALYSIS, width: 28 }),
  descriptor("cycleObservationCount", "cycle observations", { type: "integer", source: SOURCE_ANALYSIS, width: 16, format: "0" }),
  descriptor("blockValid", "block valid", { type: "boolean", source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("semanticGatePassed", "semantic gate", { type: "boolean", source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("performanceComparisonEligible", "performance eligible", { type: "boolean", source: SOURCE_ANALYSIS, width: 16 }),
  descriptor("includedInPerformanceSummary", "included in summary", { type: "boolean", source: SOURCE_ANALYSIS, width: 16 }),
  descriptor("redeployReadyAllCycles", "redeploy ready all cycles", { type: "boolean", source: SOURCE_ANALYSIS, width: 18 }),
  descriptor("observedMedian_operationsPerSecond", "observed median throughput (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 23, format: "#,##0" }),
  descriptor("comparisonMedian_operationsPerSecond", "comparison median throughput (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 25, format: "#,##0" }),
  descriptor("observedMedian_fillOperationsPerSecond", "observed fill median (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 21, format: "#,##0" }),
  descriptor("comparisonMedian_fillOperationsPerSecond", "comparison fill median (ops/s)", { type: "number", unit: "operation/s", source: SOURCE_ANALYSIS, width: 22, format: "#,##0" }),
  descriptor("observedMedian_latencyP50Nanos", "observed p50 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("comparisonMedian_latencyP50Nanos", "comparison p50 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 20, format: "#,##0" }),
  descriptor("observedMedian_latencyP95Nanos", "observed p95 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("comparisonMedian_latencyP95Nanos", "comparison p95 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 20, format: "#,##0" }),
  descriptor("observedMedian_latencyP99Nanos", "observed p99 median (ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("comparisonMedian_latencyP99Nanos", "comparison p99 median (raw ns)", { type: "number", unit: "ns", source: SOURCE_ANALYSIS, width: 23, format: "#,##0" }),
  descriptor("comparisonMedian_latencyP99MicrosFormula", "comparison p99 median (µs, formula)", { type: "number", unit: "µs", source: SOURCE_FORMULA, definition: "P99 per fork convertito da nanosecondi a microsecondi.", width: 24, format: "#,##0.000" }),
  descriptor("observedMedian_measuredLatencySamples", "observed latency samples median", { type: "number", unit: "sample", source: SOURCE_ANALYSIS, width: 22, format: "#,##0" }),
  descriptor("comparisonMedian_measuredLatencySamples", "comparison latency samples median", { type: "number", unit: "sample", source: SOURCE_ANALYSIS, width: 23, format: "#,##0" }),
];

const PAIRED_RATIO_COLUMNS = [
  descriptor("scenario", "scenario", { source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("referenceProvider", "reference provider", { source: SOURCE_ANALYSIS, width: 16 }),
  descriptor("phase", "phase", { source: SOURCE_ANALYSIS, width: 11 }),
  descriptor("analysisSet", "analysis set", { source: SOURCE_ANALYSIS, width: 28 }),
  descriptor("pairingUnit", "pairing unit", { source: SOURCE_ANALYSIS, width: 18 }),
  descriptor("ratioMetric", "provider/JCS4 ratio metric", { source: SOURCE_ANALYSIS, definition: "Metrica del rapporto appaiato: valore del provider diviso per il valore JCS4 nello stesso Williams block.", width: 24 }),
  descriptor("ratioToJcs4N", "paired N", { type: "integer", source: SOURCE_ANALYSIS, width: 10, format: "0" }),
  descriptor("ratioToJcs4Median", "provider/JCS4 median", { type: "number", unit: "×", source: SOURCE_ANALYSIS, definition: "Mediana dei sei rapporti appaiati provider ÷ JCS4.", width: 18, format: "0.00x" }),
  descriptor("ratioToJcs4Mean", "provider/JCS4 mean", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 18, format: "0.00x" }),
  descriptor("ratioToJcs4SampleStandardDeviation", "provider/JCS4 sample SD", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 19, format: "0.00" }),
  descriptor("ratioToJcs4FirstQuartile", "provider/JCS4 Q1", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 16, format: "0.00x" }),
  descriptor("ratioToJcs4ThirdQuartile", "provider/JCS4 Q3", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 16, format: "0.00x" }),
  descriptor("ratioToJcs4Minimum", "provider/JCS4 min", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 16, format: "0.00x" }),
  descriptor("ratioToJcs4Maximum", "provider/JCS4 max", { type: "number", unit: "×", source: SOURCE_ANALYSIS, width: 16, format: "0.00x" }),
  descriptor("valuesByBlock", "values by Williams block (JSON)", { source: SOURCE_ANALYSIS, width: 58, wrap: true }),
];

const LIFECYCLE_SUMMARY_COLUMNS = [
  descriptor("scenario", "scenario", { source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("statisticalUnit", "statistical unit", { source: SOURCE_ANALYSIS, width: 31 }),
  descriptor("studyRole", "study role", { source: SOURCE_ANALYSIS, width: 34 }),
  descriptor("forkCount", "valid forks", { type: "integer", source: SOURCE_ANALYSIS, width: 11, format: "0" }),
  descriptor("observedForkCount", "observed forks", { type: "integer", source: SOURCE_ANALYSIS, width: 13, format: "0" }),
  descriptor("invalidBlockForkCount", "invalid-block forks", { type: "integer", source: SOURCE_ANALYSIS, width: 15, format: "0" }),
  descriptor("redeployReadyForkCount", "redeploy-ready forks", { type: "integer", source: SOURCE_ANALYSIS, width: 16, format: "0" }),
  descriptor("forksWithTargetFindleaksObservation", "forks with positive findleaks checkpoint", { type: "integer", source: SOURCE_ANALYSIS, width: 24, format: "0" }),
  descriptor("forksWithThreadLeakWarning", "forks with thread-leak warning", { type: "integer", source: SOURCE_ANALYSIS, width: 22, format: "0" }),
  descriptor("forksWithJcsThreadSignature", "forks with JCS signature", { type: "integer", source: SOURCE_ANALYSIS, width: 19, format: "0" }),
  descriptor("forksWithJcs248CorroboratedSignal", "forks with corroborated JCS-248 signal", { type: "integer", source: SOURCE_ANALYSIS, width: 25, format: "0" }),
  descriptor("jcs248PositiveControlCriterionMet", "JCS-248 positive-control criterion", { type: "boolean", source: SOURCE_ANALYSIS, width: 24 }),
  descriptor("targetFindleaksObservationCountMedian", "positive findleaks checkpoints median", { type: "number", unit: "checkpoint/fork", source: SOURCE_ANALYSIS, width: 24, format: "0.0" }),
  descriptor("threadLeakWarningCountMedian", "thread-leak warning median", { type: "number", unit: "warning/fork", source: SOURCE_ANALYSIS, width: 21, format: "0.0" }),
  descriptor("jcsThreadSignatureObservationCountMedian", "JCS signature median", { type: "number", unit: "observation/fork", source: SOURCE_ANALYSIS, width: 19, format: "0.0" }),
  descriptor("absoluteFinalHeapSlopeBytesPerCycleMedian", "heap slope median (bytes/cycle)", { type: "number", unit: "byte/cycle", source: SOURCE_ANALYSIS, width: 21, format: "#,##0" }),
  descriptor("absoluteFinalNativeCommittedSlopeBytesPerCycleMedian", "NMT slope median (bytes/cycle)", { type: "number", unit: "byte/cycle", source: SOURCE_ANALYSIS, width: 21, format: "#,##0" }),
  descriptor("absoluteFinalWebappClassloaderSlopePerCycleMedian", "classloader-row slope median", { type: "number", unit: "row/cycle", source: SOURCE_ANALYSIS, width: 20, format: "0.000" }),
  descriptor("absoluteFinalLiveThreadSlopePerCycleMedian", "thread slope median", { type: "number", unit: "thread/cycle", source: SOURCE_ANALYSIS, width: 18, format: "0.000" }),
  descriptor("redeployReadyRateFormula", "redeploy-ready rate (formula)", { type: "percent", source: SOURCE_FORMULA, width: 19, format: "0.0%" }),
  descriptor("jcsSignatureForkRateFormula", "JCS-signature fork rate (formula)", { type: "percent", source: SOURCE_FORMULA, width: 20, format: "0.0%" }),
];

const LIFECYCLE_FORK_COLUMNS = [
  descriptor("processRunId", "processRunId", { source: SOURCE_ANALYSIS, width: 54 }),
  descriptor("scenario", "scenario", { source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("fork", "fork", { type: "integer", source: SOURCE_ANALYSIS, width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("blockValid", "block valid", { type: "boolean", source: SOURCE_ANALYSIS, width: 12 }),
  descriptor("cycleCount", "cycles", { type: "integer", source: SOURCE_ANALYSIS, width: 9, format: "0" }),
  descriptor("redeployReadyAllCycles", "redeploy ready all cycles", { type: "boolean", source: SOURCE_ANALYSIS, width: 18 }),
  descriptor("firstUndeployTargetFindleaksObservationCount", "positive findleaks checkpoints: first undeploy", { type: "integer", source: SOURCE_ANALYSIS, definition: "Numero di checkpoint nei quali il contesto target compare nell'output findleaks dopo il primo undeploy.", width: 25, format: "0" }),
  descriptor("finalUndeployTargetFindleaksObservationCount", "positive findleaks checkpoints: final undeploy", { type: "integer", source: SOURCE_ANALYSIS, definition: "Numero di checkpoint nei quali il contesto target compare nell'output findleaks dopo l'undeploy finale.", width: 25, format: "0" }),
  descriptor("targetFindleaksObservationCount", "positive findleaks checkpoints: total", { type: "integer", source: SOURCE_ANALYSIS, width: 23, format: "0" }),
  descriptor("firstUndeployThreadLeakWarningCount", "thread warnings first", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("finalUndeployThreadLeakWarningCount", "thread warnings final", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("threadLeakWarningCount", "thread warnings total", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("jcsThreadSignatureObservationCount", "JCS signature observations", { type: "integer", source: SOURCE_ANALYSIS, width: 20, format: "0" }),
  descriptor("jcsThreadSignatureObserved", "JCS signature observed", { type: "boolean", source: SOURCE_ANALYSIS, width: 18 }),
  descriptor("jcs248CorroboratedUndeployCount", "corroborated undeploy intervals", { type: "integer", unit: "interval", source: SOURCE_ANALYSIS, definition: "Numero di intervalli di undeploy nei quali coesistono firma thread JCS e warning Tomcat.", width: 22, format: "0" }),
  descriptor("jcs248CorroboratedIntervals", "corroborated interval details (JSON)", { source: SOURCE_ANALYSIS, definition: "Dettaglio preservato di ciclo, fase e conteggi che formano ciascun segnale corroborato.", width: 62, wrap: true }),
  descriptor("jcs248CorroboratedSignalObserved", "JCS-248 signal corroborated", { type: "boolean", source: SOURCE_ANALYSIS, width: 20 }),
  descriptor("absoluteFinalHeapSlopeBytesPerCycle", "heap slope (bytes/cycle)", { type: "number", unit: "byte/cycle", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("absoluteFinalNativeCommittedSlopeBytesPerCycle", "NMT slope (bytes/cycle)", { type: "number", unit: "byte/cycle", source: SOURCE_ANALYSIS, width: 19, format: "#,##0" }),
  descriptor("absoluteFinalWebappClassloaderSlopePerCycle", "classloader-row slope", { type: "number", unit: "row/cycle", source: SOURCE_ANALYSIS, width: 18, format: "0.000" }),
  descriptor("absoluteFinalLiveThreadSlopePerCycle", "thread slope", { type: "number", unit: "thread/cycle", source: SOURCE_ANALYSIS, width: 15, format: "0.000" }),
  descriptor("absoluteFinalHeapFirstBytes", "heap first (bytes)", { type: "bytes", unit: "byte", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("absoluteFinalHeapLastBytes", "heap last (bytes)", { type: "bytes", unit: "byte", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("absoluteFinalNativeCommittedFirstBytes", "NMT first (bytes)", { type: "bytes", unit: "byte", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("absoluteFinalNativeCommittedLastBytes", "NMT last (bytes)", { type: "bytes", unit: "byte", source: SOURCE_ANALYSIS, width: 17, format: "#,##0" }),
  descriptor("absoluteFinalWebappClassloaderFirst", "classloader rows first", { type: "integer", unit: "row", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("absoluteFinalWebappClassloaderLast", "classloader rows last", { type: "integer", unit: "row", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("absoluteFinalLiveThreadFirst", "threads first", { type: "integer", unit: "thread", source: SOURCE_ANALYSIS, width: 14, format: "0" }),
  descriptor("absoluteFinalLiveThreadLast", "threads last", { type: "integer", unit: "thread", source: SOURCE_ANALYSIS, width: 14, format: "0" }),
];

const LIFECYCLE_CYCLE_COLUMNS = [
  descriptor("processRunId", "processRunId", { width: 54 }),
  descriptor("scenario", "scenario", { width: 12 }),
  descriptor("provider", "provider", { width: 13 }),
  descriptor("fork", "fork", { type: "integer", width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", width: 12, format: "0" }),
  descriptor("orderPosition", "orderPosition", { type: "integer", width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", width: 8, format: "0" }),
  descriptor("deployMs", "deploy (ms)", { type: "duration", unit: "ms", width: 13, format: "#,##0" }),
  descriptor("undeployMs", "undeploy (ms)", { type: "duration", unit: "ms", width: 13, format: "#,##0" }),
  descriptor("redeployMs", "redeploy (ms)", { type: "duration", unit: "ms", width: 13, format: "#,##0" }),
  descriptor("secondUndeployMs", "second undeploy (ms)", { type: "duration", unit: "ms", width: 17, format: "#,##0" }),
  descriptor("redeployReady", "redeploy ready", { type: "boolean", width: 14 }),
  descriptor("redeployWorkloadPassed", "redeploy workload gate", { type: "boolean", width: 18 }),
  descriptor("redeployPassed", "redeploy passed", { type: "boolean", width: 14 }),
  descriptor("firstEarlyTargetSeconds", "first undeploy: early target (s)", { type: "duration", unit: "s after undeploy", definition: "Soglia temporale minima configurata, non istante esatto di campionamento.", width: 20, format: "0.000" }),
  descriptor("firstEarlyStartedSeconds", "first undeploy: early start (s)", { type: "duration", unit: "s after undeploy", definition: "Tempo monotonic effettivo di avvio della raccolta thread precoce.", width: 20, format: "0.000" }),
  descriptor("firstEarlyCompletedSeconds", "first undeploy: early complete (s)", { type: "duration", unit: "s after undeploy", width: 21, format: "0.000" }),
  descriptor("firstFinalTargetSeconds", "first undeploy: final target (s)", { type: "duration", unit: "s after undeploy", definition: "Soglia temporale minima configurata per la diagnostica finale.", width: 20, format: "0.000" }),
  descriptor("firstFinalStartedSeconds", "first undeploy: final start (s)", { type: "duration", unit: "s after undeploy", width: 20, format: "0.000" }),
  descriptor("firstFindLeaksCompletedSeconds", "first undeploy: findleaks complete (s)", { type: "duration", unit: "s after undeploy", width: 23, format: "0.000" }),
  descriptor("firstSnapshotCompletedSeconds", "first undeploy: snapshot complete (s)", { type: "duration", unit: "s after undeploy", width: 23, format: "0.000" }),
  descriptor("finalEarlyTargetSeconds", "final undeploy: early target (s)", { type: "duration", unit: "s after undeploy", definition: "Soglia temporale minima configurata, non istante esatto di campionamento.", width: 20, format: "0.000" }),
  descriptor("finalEarlyStartedSeconds", "final undeploy: early start (s)", { type: "duration", unit: "s after undeploy", width: 20, format: "0.000" }),
  descriptor("finalEarlyCompletedSeconds", "final undeploy: early complete (s)", { type: "duration", unit: "s after undeploy", width: 21, format: "0.000" }),
  descriptor("finalFinalTargetSeconds", "final undeploy: final target (s)", { type: "duration", unit: "s after undeploy", definition: "Soglia temporale minima configurata per la diagnostica finale.", width: 20, format: "0.000" }),
  descriptor("finalFinalStartedSeconds", "final undeploy: final start (s)", { type: "duration", unit: "s after undeploy", width: 20, format: "0.000" }),
  descriptor("finalFindLeaksCompletedSeconds", "final undeploy: findleaks complete (s)", { type: "duration", unit: "s after undeploy", width: 23, format: "0.000" }),
  descriptor("finalSnapshotCompletedSeconds", "final undeploy: snapshot complete (s)", { type: "duration", unit: "s after undeploy", width: 23, format: "0.000" }),
  descriptor("cacheHeapDeltaBytes", "loaded-idle heap Δ (bytes)", { type: "bytes", unit: "byte", width: 20, format: "+#,##0;-#,##0;0" }),
  descriptor("retainedHeapBytes", "final-baseline heap Δ (bytes)", { type: "bytes", unit: "byte", width: 22, format: "+#,##0;-#,##0;0" }),
  descriptor("finalClassloaderCountAtOrBelowCycleBaseline", "final classloader rows ≤ baseline", { type: "boolean", width: 23 }),
  descriptor("firstUndeployTargetFindleaksObserved", "findleaks checkpoint positive after first", { type: "boolean", definition: "Segnale diagnostico positivo al checkpoint; non è un verdetto causale isolato.", width: 25 }),
  descriptor("finalUndeployTargetFindleaksObserved", "findleaks checkpoint positive after final", { type: "boolean", definition: "Segnale diagnostico positivo al checkpoint; non è un verdetto causale isolato.", width: 25 }),
  descriptor("finalThreadCountAtOrBelowCycleBaseline", "final threads ≤ baseline", { type: "boolean", width: 18 }),
  descriptor("candidateApplicationThreadCountAfterFinalUndeploy", "candidate app thread count", { type: "integer", unit: "thread", width: 19, format: "0" }),
  descriptor("candidateApplicationThreadsAfterFinalUndeploy", "candidate app thread names", { width: 56, wrap: true }),
  descriptor("noCandidateApplicationThreadSignalAfterFinalUndeploy", "no candidate-thread signal", { type: "boolean", width: 20 }),
];

const JCS_EVIDENCE_COLUMNS = [
  descriptor("processRunId", "processRunId", { source: SOURCE_ANALYSIS, width: 54 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("fork", "fork", { type: "integer", source: SOURCE_ANALYSIS, width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("cycle", "cycle", { type: "integer", source: SOURCE_ANALYSIS, width: 8, format: "0" }),
  descriptor("phase", "phase", { source: SOURCE_ANALYSIS, width: 11 }),
  descriptor("earlyJcsThreadSignatureCount", "early JCS signatures", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("finalJcsThreadSignatureCount", "final JCS signatures", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("threadLeakWarningCount", "thread-leak warnings", { type: "integer", source: SOURCE_ANALYSIS, width: 17, format: "0" }),
  descriptor("tomcatFindLeaksTargetContextCount", "positive findleaks target occurrences", { type: "integer", source: SOURCE_ANALYSIS, width: 24, format: "0" }),
  descriptor("semanticGatePassed", "semantic gate", { type: "boolean", source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("blockValid", "block valid", { type: "boolean", source: SOURCE_ANALYSIS, width: 12 }),
];

const JCS_INTERVAL_COLUMNS = [
  descriptor("processRunId", "processRunId", { source: SOURCE_ANALYSIS, width: 54 }),
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("fork", "fork", { type: "integer", source: SOURCE_ANALYSIS, width: 8, format: "0" }),
  descriptor("block", "Williams block", { type: "integer", source: SOURCE_ANALYSIS, width: 12, format: "0" }),
  descriptor("jcs248CorroboratedUndeployCount", "corroborated intervals", { type: "integer", unit: "interval", source: SOURCE_ANALYSIS, width: 18, format: "0" }),
  descriptor("jcs248CorroboratedSignalObserved", "corroborated signal observed", { type: "boolean", source: SOURCE_ANALYSIS, width: 21 }),
  descriptor("jcs248CorroboratedIntervals", "interval details (JSON)", { source: SOURCE_ANALYSIS, definition: "Ogni record identifica ciclo, primo/finale undeploy, firme osservate e warning concorrenti.", width: 72, wrap: true }),
];

const JCS_CONTROL_COLUMNS = [
  descriptor("provider", "provider", { source: SOURCE_ANALYSIS, width: 13 }),
  descriptor("studyRole", "study role", { source: SOURCE_ANALYSIS, definition: "Ruolo prespecificato nel contrasto di controllo JCS-248.", width: 34 }),
  descriptor("forkCount", "valid forks", { type: "integer", source: SOURCE_ANALYSIS, width: 11, format: "0" }),
  descriptor("observedForkCount", "observed forks", { type: "integer", source: SOURCE_ANALYSIS, width: 13, format: "0" }),
  descriptor("redeployReadyForkCount", "redeploy-ready forks", { type: "integer", source: SOURCE_ANALYSIS, width: 16, format: "0" }),
  descriptor("forksWithThreadLeakWarning", "thread-warning forks", { type: "integer", source: SOURCE_ANALYSIS, width: 18, format: "0" }),
  descriptor("forksWithJcsThreadSignature", "JCS-signature forks", { type: "integer", source: SOURCE_ANALYSIS, width: 18, format: "0" }),
  descriptor("forksWithJcs248CorroboratedSignal", "corroborated-signal forks", { type: "integer", source: SOURCE_ANALYSIS, width: 21, format: "0" }),
  descriptor("jcs248PositiveControlCriterionMet", "runner criterion", { type: "boolean", source: SOURCE_ANALYSIS, definition: "Criterio prodotto dall'analisi: applicabile come controllo positivo a JCS 3.2.1.", width: 16 }),
  descriptor("recomputedCriterionFormula", "recomputed criterion", { type: "boolean", source: SOURCE_FORMULA, definition: "TRUE solo per JCS 3.2.1 con 6 fork validi e almeno 5 fork con segnale corroborato.", width: 19 }),
  descriptor("formulaMatchesRunner", "formula = runner", { type: "boolean", source: SOURCE_FORMULA, width: 16 }),
];

function populateReadme(sheet, raw, analysis, paperValues, files) {
  styleTitle(
    sheet,
    "Beyond Throughput — dataset e protocollo v4.2",
    "Workbook scientifico riproducibile. Nessuna classifica: prestazioni, correttezza e lifecycle sono riportati come dimensioni distinte.",
    "I",
  );
  sheet.showGridLines = false;

  styleSection(sheet, 4, "A", "D", "Tracciabilità della campagna finale");
  const totalCycles = asArray(raw.processRuns).reduce((sum, run) => sum + asArray(run.cycles).length, 0);
  const totalWindows = totalCycles * 2;
  const identity = [
    ["Campaign", path.basename(files.rawPath).replace(/-results\.json$/i, "")],
    ["Results JSON", displayPath(files.rawPath)],
    ["Results SHA-256", files.rawSha],
    ["Analysis JSON", displayPath(files.analysisPath)],
    ["Analysis SHA-256", files.analysisSha],
    ["Protocol / JSON schema", PROTOCOL_VERSION],
    ["Started at", raw.campaignStartedAt],
    ["Finished at", raw.campaignFinishedAt],
    ["Independent process runs", asArray(raw.processRuns).length],
    ["Lifecycle cycles", totalCycles],
    ["Timed workload windows", totalWindows],
    ["Invalid Williams blocks", asArray(analysis.invalidBlocks).length],
    ["Statistical unit", analysis.statisticalUnit],
    ["Primary analysis", analysis.primaryAnalysis],
    ["Sensitivity analysis", analysis.sensitivityAnalysis],
    ["Ranking produced", analysis.rankingProduced],
  ];
  sheet.getRange("A5:D20").values = identity.map(([key, value]) => [key, safeCellValue(value), null, null]);
  sheet.getRange("A5:A20").format = { font: { name: "Aptos", size: 9, bold: true, color: COLORS.ink }, fill: COLORS.paleBlue };
  sheet.getRange("B5:D20").format = { font: { name: "Aptos", size: 9, color: COLORS.ink }, wrapText: true };
  // The workbook runtime recognises ISO-8601 strings as Excel dates. Make the
  // two campaign timestamps human-readable instead of exposing date serials.
  sheet.getRange("B11:B12").setNumberFormat("yyyy-mm-dd hh:mm:ss");
  sheet.getRange("A16:D19").format.rowHeight = 30;

  styleSection(sheet, 4, "F", "I", "Provenienza e archivio diagnostico");
  const diagnosticArchive = raw.diagnosticArchive ?? {};
  const provenanceRows = [
    ["Source manifest SHA-256", raw.sourceProvenance?.manifestSha256, null, "results.sourceProvenance"],
    ["Frozen protocol", EXPECTED_PROTOCOL_PATH, null, "results.sourceProvenance.files"],
    ["Frozen protocol SHA-256", EXPECTED_PROTOCOL_SHA256, null, "results.sourceProvenance.files"],
    ["Diagnostic archive", artifactFileName(diagnosticArchive.file), null, "results.diagnosticArchive"],
    ["Diagnostic archive SHA-256", diagnosticArchive.sha256, null, "results.diagnosticArchive"],
    ["Diagnostic archive size", diagnosticArchive.sizeBytes, "byte", "results.diagnosticArchive"],
    ["Analysis reference in results", artifactFileName(raw.analysisFile), null, "results.analysisFile"],
    ["Paper-values JSON", displayPath(files.paperValuesPath), null, SOURCE_PAPER_VALUES],
    ["Paper-values SHA-256", files.paperValuesSha, null, SOURCE_PAPER_VALUES],
    ["Paper-values status", paperValues.datasetStatus, null, SOURCE_PAPER_VALUES],
    ["Timed undeploy intervals", paperValues.lifecycle?.timingEvidence?.intervals, "interval", SOURCE_PAPER_VALUES],
    ["Timing reference", `${paperValues.lifecycle?.timingEvidence?.clock}; origin: ${paperValues.lifecycle?.timingEvidence?.referenceOrigin}`, null, SOURCE_PAPER_VALUES],
    ["Infrastructure failures", asArray(raw.infrastructureFailures).length, "event", "results.infrastructureFailures"],
    ["Raw invalid blocks", asArray(raw.invalidBlocks).length, "block", "results.invalidBlocks"],
    ["Performance exclusions", clippedJson(analysis.performanceExclusions), null, "analysis.performanceExclusions"],
  ];
  sheet.getRange(`F5:I${4 + provenanceRows.length}`).values = provenanceRows.map((row) => row.map(safeCellValue));
  sheet.getRange(`F5:F${4 + provenanceRows.length}`).format = { font: { name: "Aptos", size: 9, bold: true, color: COLORS.ink }, fill: COLORS.paleTeal };
  sheet.getRange(`G5:I${4 + provenanceRows.length}`).format = { font: { name: "Aptos", size: 9, color: COLORS.ink }, wrapText: true };
  sheet.getRange(`F${4 + provenanceRows.length}:I${4 + provenanceRows.length}`).format.rowHeight = 42;

  styleSection(sheet, 22, "A", "D", "Costanti visibili usate dalle formule");
  sheet.getRange("A23:D32").values = [
    ["Constant", "Value", "Unit", "Purpose"],
    ["Nanoseconds per second", 1_000_000_000, "ns/s", "Conversione delle durate"],
    ["Nanoseconds per microsecond", 1_000, "ns/µs", "Presentazione della latenza p99 in microsecondi"],
    ["Bytes per MiB", 1_048_576, "byte/MiB", "Conversione di heap, NMT e limiti container"],
    ["Percentage points per unit", 100, "pp", "Differenza assoluta tra tassi"],
    ["Hit-rate tolerance", HIT_RATE_TOLERANCE, "fraction", "Soglia numerica prespecificata: mezzo punto percentuale"],
    ["JCS-248 required valid forks", 6, "fork", "Criterio prespecificato del controllo positivo"],
    ["JCS-248 minimum corroborated forks", 5, "fork", "Criterio prespecificato del controllo positivo"],
    ["Seconds per day", 86_400, "s/day", "Conversione delle date Excel in secondi"],
    ["Minimum capacity fraction", 0.99, "fraction", "Soglia applicata a entrambi i checkpoint di capacità"],
  ];
  styleHeader(sheet.getRange("A23:D23"));
  styleBody(sheet.getRange("A24:D32"));
  sheet.getRange("B24:B27").setNumberFormat("#,##0");
  sheet.getRange("B28:B28").setNumberFormat("0.000");
  sheet.getRange("B29:B31").setNumberFormat("#,##0");
  sheet.getRange("B32").setNumberFormat("0.00");

  styleSection(sheet, 34, "A", "D", "Parametri del workload");
  const configRows = Object.entries(raw.configuration ?? {}).map(([key, value]) => [key, safeCellValue(value), null, "results.configuration"]);
  sheet.getRange(`A35:D${35 + configRows.length}`).values = [["Parameter", "Value", "Unit", "Source"], ...configRows];
  styleHeader(sheet.getRange("A35:D35"));
  styleBody(sheet.getRange(`A36:D${35 + configRows.length}`));

  styleSection(sheet, 34, "F", "I", "Protocollo lifecycle");
  const lifecycleRows = Object.entries(raw.lifecycleProtocol ?? {}).map(([key, value]) => [key, safeCellValue(value), null, "results.lifecycleProtocol"]);
  sheet.getRange(`F35:I${35 + lifecycleRows.length}`).values = [["Protocol field", "Value", "Unit", "Source"], ...lifecycleRows];
  styleHeader(sheet.getRange("F35:I35"));
  styleBody(sheet.getRange(`F36:I${35 + lifecycleRows.length}`));

  styleSection(sheet, 51, "A", "I", "Ordine Williams prespecificato (non ordinamento per risultato)");
  const scheduleRows = asArray(raw.schedule?.canonicalRows).map((row, index) => [index + 1, ...row]);
  sheet.getRange(`A52:G${52 + scheduleRows.length}`).values = [["Row", "1", "2", "3", "4", "5", "6"], ...scheduleRows];
  styleHeader(sheet.getRange("A52:G52"));
  styleBody(sheet.getRange(`A53:G${52 + scheduleRows.length}`));

  styleSection(sheet, 61, "A", "D", "Ruoli delle condizioni");
  sheet.getRange("A62:D65").values = [
    ["Role", "Conditions", "Performance comparison", "Meaning"],
    ["current-provider-primary-comparison", "caffeine, ehcache, cache2k, jcs4", "Eligible if QC passes", "Provider correnti nel confronto applicativo"],
    ["JCS-248-positive-control", "jcs321", "Excluded", "Controllo positivo per la firma diagnostica storica"],
    ["lifecycle-negative-control", "nostore", "Excluded", "Controllo del percorso di deploy/undeploy senza storage"],
  ];
  styleHeader(sheet.getRange("A62:D62"));
  styleBody(sheet.getRange("A63:D65"));

  styleSection(sheet, 61, "F", "I", "Versioni provider prespecificate");
  const providerVersionRows = CANONICAL_PROVIDERS.map((provider) => {
    const metadata = PRESPECIFIED_PROVIDER_VERSIONS[provider];
    return [provider, metadata.version, metadata.version ? "prespecificata" : "non applicabile", metadata.evidence];
  });
  sheet.getRange("F62:I68").values = [["Provider", "Version", "Status", "Evidence / limit"], ...providerVersionRows];
  styleHeader(sheet.getRange("F62:I62"));
  styleBody(sheet.getRange("F63:I68"));
  sheet.getRange("I63:I68").format.wrapText = true;

  styleSection(sheet, 70, "A", "I", "Lettura corretta del workbook");
  const notes = [
    "La JVM/container indipendente è l'unità statistica; i cicli interni sono osservazioni ripetute, non repliche indipendenti.",
    "La tabella primaria include il ciclo 1; sensitivity-without-cycle-1 lo omette. Entrambe sono prespecificate e conservate senza scegliere ex post il risultato più favorevole.",
    "JCS 3.2.1 e nostore sono controlli di lifecycle e non entrano nel confronto prestazionale.",
    "Il conteggio delle righe classloader è un indicatore diagnostico testuale; non equivale da solo a una prova di leak.",
    "I grafici mostrano l'ordine del protocollo o del fork, mai un ranking per velocità.",
    "Per JCS-248 la conclusione richiede corroborazione fra firma del thread e warning Tomcat; heap/NMT/classloader restano evidenze complementari.",
    "Le 36 JVM indipendenti sono state eseguite in sequenza sullo stesso host Docker; questo controlla l'hardware, ma non elimina variazioni temporali dell'host.",
    "writePercent è registrato nella configurazione, ma con workload=uniform non governa la finestra cronometrata: concurrentWriteOperations deve essere 0; la write probe è separata.",
    "I fogli Raw sono viste appiattite di comodo e possono perdere struttura annidata; i JSON, identificati dai rispettivi SHA-256, restano la fonte autorevole.",
    "Un checkpoint findleaks positivo è evidenza diagnostica da corroborare, non un verdetto autonomo di memory leak.",
    "Per nostore il single-flight non è applicabile: loaderInvocationsUnderContention resta visibile (16 chiamanti nel controllo), ma non entra nel gate negativo.",
    "Il gate di capacità v4.2 verifica due checkpoint distinti: subito dopo il workload e dopo la write probe; providerMetrics resta solo un alias compatibile del secondo.",
    "I valori 2 s e 10 s sono soglie minime di avvio. Il foglio Lifecycle riporta i tempi monotonic effettivi di avvio e completamento delle diagnostiche, senza presentarli come istanti esatti.",
  ];
  notes.forEach((note, index) => {
    const row = 71 + index;
    const range = sheet.getRange(`A${row}:I${row}`);
    range.merge();
    range.values = [[`• ${note}`]];
    range.format = { font: { name: "Aptos", size: 9, color: COLORS.ink }, wrapText: true };
    range.format.rowHeight = 25;
  });

  sheet.getRange("A1:A84").format.columnWidth = 34;
  sheet.getRange("B1:B84").format.columnWidth = 64;
  sheet.getRange("C1:C84").format.columnWidth = 16;
  sheet.getRange("D1:D84").format.columnWidth = 48;
  sheet.getRange("E1:E84").format.columnWidth = 3;
  sheet.getRange("F1:F84").format.columnWidth = 34;
  sheet.getRange("G1:G84").format.columnWidth = 48;
  sheet.getRange("H1:H84").format.columnWidth = 16;
  sheet.getRange("I1:I84").format.columnWidth = 42;
  sheet.freezePanes.freezeRows(2);
}

const CONSTANT_REFS = {
  nanosecondsPerSecond: "'Readme-Protocol'!$B$24",
  nanosecondsPerMicrosecond: "'Readme-Protocol'!$B$25",
  bytesPerMiB: "'Readme-Protocol'!$B$26",
  percentagePoints: "'Readme-Protocol'!$B$27",
  hitRateTolerance: "'Readme-Protocol'!$B$28",
  jcs248RequiredForks: "'Readme-Protocol'!$B$29",
  jcs248MinimumCorroboratedForks: "'Readme-Protocol'!$B$30",
  secondsPerDay: "'Readme-Protocol'!$B$31",
  minimumCapacityFraction: "'Readme-Protocol'!$B$32",
};

function populateRuns(sheet, rows) {
  const info = writeFlatSheet(sheet, RUN_COLUMNS, rows, { tableName: "RunsV4", freezeColumns: 5 });
  if (!rows.length) return info;
  const started = keyColumn(RUN_COLUMNS, "startedAt");
  const finished = keyColumn(RUN_COLUMNS, "finishedAt");
  const duration = keyColumn(RUN_COLUMNS, "durationSecondsFormula");
  const memoryBytes = keyColumn(RUN_COLUMNS, "containerMemoryLimitBytes");
  const memoryMiB = keyColumn(RUN_COLUMNS, "containerMemoryLimitMiBFormula");
  const durationFormulas = [];
  const memoryFormulas = [];
  for (let row = info.firstDataRow; row <= info.lastDataRow; row += 1) {
    durationFormulas.push([`=IF(OR(${started}${row}="",${finished}${row}=""),"",(${finished}${row}-${started}${row})*${CONSTANT_REFS.secondsPerDay})`]);
    memoryFormulas.push([`=IF(${memoryBytes}${row}="","",${memoryBytes}${row}/${CONSTANT_REFS.bytesPerMiB})`]);
  }
  sheet.getRange(`${duration}${info.firstDataRow}:${duration}${info.lastDataRow}`).formulas = durationFormulas;
  sheet.getRange(`${memoryMiB}${info.firstDataRow}:${memoryMiB}${info.lastDataRow}`).formulas = memoryFormulas;
  return info;
}

function populateQualityGates(sheet, rows) {
  const info = writeFlatSheet(sheet, QC_COLUMNS, rows, { tableName: "QualityGatesV4", freezeColumns: 9 });
  if (!rows.length) return info;
  const c = (key) => keyColumn(QC_COLUMNS, key);
  const formulas = [];
  for (let row = info.firstDataRow; row <= info.lastDataRow; row += 1) {
    const observedSeconds = `=IF(${c("observedMeasurementNanos")}${row}="","",${c("observedMeasurementNanos")}${row}/${CONSTANT_REFS.nanosecondsPerSecond})`;
    const durationRatio = `=IF(OR(${c("requestedMeasurementNanos")}${row}="",${c("requestedMeasurementNanos")}${row}=0),"",${c("observedMeasurementNanos")}${row}/${c("requestedMeasurementNanos")}${row})`;
    const hitDelta = `=IF(OR(${c("expectedHitRate")}${row}="",${c("observedHitRate")}${row}=""),"",ABS(${c("observedHitRate")}${row}-${c("expectedHitRate")}${row})*${CONSTANT_REFS.percentagePoints})`;
    const operationMeasurementsNumeric = `=AND(${c("requiredOperations")}${row}>0,${c("measuredOperations")}${row}>=0,${c("operationsPerSecond")}${row}>0)`;
    const completedNumeric = `=AND(${c("operationMeasurementsValidRecomputedFormula")}${row},${c("measuredOperations")}${row}>=${c("requiredOperations")}${row})`;
    const durationNumeric = `=OR(${c("requestedMeasurementNanos")}${row}=0,${c("observedMeasurementNanos")}${row}>=${c("requestedMeasurementNanos")}${row})`;
    const hitNumeric = `=IF(${c("gateType")}${row}="cache-semantics",OR(${c("workloadType")}${row}<>"uniform",ABS(${c("observedHitRate")}${row}-${c("configuredHitPercent")}${row}/${CONSTANT_REFS.percentagePoints})<=${CONSTANT_REFS.hitRateTolerance}),TRUE)`;
    const minimumEntriesNumeric = `=IF(${c("gateType")}${row}="cache-semantics",INT(${c("configuredEntries")}${row}*${CONSTANT_REFS.minimumCapacityFraction}),"")`;
    const minimumAfterWorkloadMatches = `=IF(${c("gateType")}${row}="cache-semantics",${c("minimumEntriesRecomputedFormula")}${row}=${c("minimumExpectedEntriesAfterWorkload")}${row},TRUE)`;
    const minimumAfterWriteMatches = `=IF(${c("gateType")}${row}="cache-semantics",${c("minimumEntriesRecomputedFormula")}${row}=${c("minimumExpectedEntriesAfterWriteProbe")}${row},TRUE)`;
    const capacityAfterWorkloadNumeric = `=IF(${c("gateType")}${row}="cache-semantics",${c("observedEntriesAfterWorkload")}${row}>=${c("minimumEntriesRecomputedFormula")}${row},IF(${c("gateType")}${row}="no-store-control",${c("observedEntriesAfterWorkload")}${row}=0,FALSE))`;
    const capacityAfterWriteNumeric = `=IF(${c("gateType")}${row}="cache-semantics",${c("observedEntriesAfterWriteProbe")}${row}>=${c("minimumEntriesRecomputedFormula")}${row},IF(${c("gateType")}${row}="no-store-control",${c("observedEntriesAfterWriteProbe")}${row}=0,FALSE))`;
    const capacityNumeric = `=AND(${c("capacityAfterWorkloadRecomputedFormula")}${row},${c("capacityAfterWriteProbeRecomputedFormula")}${row})`;
    const noEntriesNumeric = `=IF(${c("gateType")}${row}="no-store-control",AND(${c("observedEntriesAfterWorkload")}${row}=0,${c("observedEntriesAfterWriteProbe")}${row}=0),TRUE)`;
    const zeroHitsNumeric = `=IF(${c("gateType")}${row}="no-store-control",${c("noStoreHitRate")}${row}=0,TRUE)`;
    const singleFlightNumeric = `=IF(${c("gateType")}${row}="cache-semantics",${c("loaderInvocationsUnderContention")}${row}=1,TRUE)`;
    const cacheGate = `AND(${c("completedOperationsRecomputedFormula")}${row},${c("durationGateRecomputedFormula")}${row},${c("providerMetricCheckpointsValid")}${row},${c("hitRateGateRecomputedFormula")}${row},${c("capacityGateRecomputedFormula")}${row},${c("singleFlightRecomputedFormula")}${row})`;
    const noStoreGate = `AND(${c("completedOperationsRecomputedFormula")}${row},${c("durationGateRecomputedFormula")}${row},${c("providerMetricCheckpointsValid")}${row},${c("noEntriesRecomputedFormula")}${row},${c("zeroHitsRecomputedFormula")}${row})`;
    const recomputed = `=IF(${c("gateType")}${row}="cache-semantics",${cacheGate},IF(${c("gateType")}${row}="no-store-control",${noStoreGate},FALSE))`;
    const capacityMatches = `AND(${c("capacityAfterWorkloadRecomputedFormula")}${row}=${c("capacityAfterWorkloadPassed")}${row},${c("capacityAfterWriteProbeRecomputedFormula")}${row}=${c("capacityAfterWriteProbePassed")}${row},${c("capacityGateRecomputedFormula")}${row}=${c("capacityCheckPassed")}${row})`;
    const cacheMatches = `AND(${c("hitRateGateRecomputedFormula")}${row}=${c("hitRateWithinHalfPercentagePoint")}${row},${capacityMatches},${c("singleFlightRecomputedFormula")}${row}=${c("singleFlightPassed")}${row})`;
    const noStoreMatches = `AND(${capacityMatches},${c("noEntriesRecomputedFormula")}${row}=${c("noEntriesRetained")}${row},${c("zeroHitsRecomputedFormula")}${row}=${c("zeroHits")}${row})`;
    const match = `=AND(${c("providerMetricsAliasMatchesPostWrite")}${row},${c("operationMeasurementsValidRecomputedFormula")}${row}=${c("operationMeasurementsValid")}${row},${c("completedOperationsRecomputedFormula")}${row}=${c("completedOperations")}${row},${c("durationGateRecomputedFormula")}${row}=${c("measurementDurationPassed")}${row},${c("minimumEntriesAfterWorkloadMatchesRunnerFormula")}${row},${c("minimumEntriesAfterWriteProbeMatchesRunnerFormula")}${row},IF(${c("gateType")}${row}="cache-semantics",${cacheMatches},IF(${c("gateType")}${row}="no-store-control",${noStoreMatches},FALSE)),${c("recomputedPassFormula")}${row}=${c("runnerPassed")}${row})`;
    const included = `=AND(${c("blockValid")}${row},${c("performanceComparisonEligible")}${row},${c("recomputedPassFormula")}${row})`;
    formulas.push([
      observedSeconds,
      durationRatio,
      hitDelta,
      operationMeasurementsNumeric,
      completedNumeric,
      durationNumeric,
      hitNumeric,
      minimumEntriesNumeric,
      minimumAfterWorkloadMatches,
      minimumAfterWriteMatches,
      capacityAfterWorkloadNumeric,
      capacityAfterWriteNumeric,
      capacityNumeric,
      noEntriesNumeric,
      zeroHitsNumeric,
      singleFlightNumeric,
      recomputed,
      match,
      included,
    ]);
  }
  const firstFormulaColumn = keyColumn(QC_COLUMNS, "observedMeasurementSecondsFormula");
  const lastFormulaColumn = keyColumn(QC_COLUMNS, "expectedPerformanceInclusionFormula");
  sheet.getRange(`${firstFormulaColumn}${info.firstDataRow}:${lastFormulaColumn}${info.lastDataRow}`).formulas = formulas;
  return info;
}

function populatePerformance(sheet, raw, analysis) {
  styleTitle(
    sheet,
    "Prestazioni — statistiche per JVM indipendente",
    "Valori emessi dall'analisi v4.2 (JSON schemaVersion 4). Il confronto primario riguarda solo i provider eleggibili con gate semantico superato e blocco valido.",
    "AG",
  );
  sheet.showGridLines = false;
  const summaries = sortByStudyOrder(asArray(analysis.summaries), raw).map((row) => ({
    ...row,
    latencyP99MicrosMedianFormula: null,
  }));
  const forks = sortByStudyOrder(asArray(analysis.forks), raw).map((row) => ({
    ...row,
    comparisonMedian_latencyP99MicrosFormula: null,
  }));
  const ratios = sortByStudyOrder(asArray(analysis.pairedRatios), raw).map((row) => ({ ...row, valuesByBlock: clippedJson(row.valuesByBlock) }));

  styleSection(sheet, 4, "A", "AG", "Sintesi descrittive — primary e sensitivity");
  const summaryInfo = writeSectionTable(sheet, 5, 1, PERFORMANCE_SUMMARY_COLUMNS, summaries, "PerformanceSummaryV4");
  if (summaries.length) {
    const sourceColumn = keyColumn(PERFORMANCE_SUMMARY_COLUMNS, "latencyP99NanosMedian");
    const targetColumn = keyColumn(PERFORMANCE_SUMMARY_COLUMNS, "latencyP99MicrosMedianFormula");
    const formulas = Array.from({ length: summaries.length }, (_, index) => {
      const row = summaryInfo.firstDataRow + index;
      return [`=IF(${sourceColumn}${row}="","",${sourceColumn}${row}/${CONSTANT_REFS.nanosecondsPerMicrosecond})`];
    });
    sheet.getRange(`${targetColumn}${summaryInfo.firstDataRow}:${targetColumn}${summaryInfo.lastDataRow}`).formulas = formulas;
  }
  const forkTitleRow = summaryInfo.lastDataRow + 3;
  styleSection(sheet, forkTitleRow, "A", "AA", "Mediane interne a ciascuna process run (unità statistica = fork/JVM)");
  const forkInfo = writeSectionTable(sheet, forkTitleRow + 1, 1, PERFORMANCE_FORK_COLUMNS, forks, "PerformanceForksV4");
  if (forks.length) {
    const sourceColumn = keyColumn(PERFORMANCE_FORK_COLUMNS, "comparisonMedian_latencyP99Nanos");
    const targetColumn = keyColumn(PERFORMANCE_FORK_COLUMNS, "comparisonMedian_latencyP99MicrosFormula");
    const formulas = Array.from({ length: forks.length }, (_, index) => {
      const row = forkInfo.firstDataRow + index;
      return [`=IF(${sourceColumn}${row}="","",${sourceColumn}${row}/${CONSTANT_REFS.nanosecondsPerMicrosecond})`];
    });
    sheet.getRange(`${targetColumn}${forkInfo.firstDataRow}:${targetColumn}${forkInfo.lastDataRow}`).formulas = formulas;
  }
  const ratioTitleRow = forkInfo.lastDataRow + 3;
  styleSection(sheet, ratioTitleRow, "A", "P", "Rapporti appaiati provider ÷ JCS4 per Williams block");
  const ratioInfo = writeSectionTable(sheet, ratioTitleRow + 1, 1, PAIRED_RATIO_COLUMNS, ratios, "PairedRatiosV4");
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(3);

  const forkRowMap = new Map();
  forks.forEach((row, index) => {
    forkRowMap.set(`${row.provider}|${row.fork}|${row.phase}|${row.analysisSet}`, forkInfo.firstDataRow + index);
  });
  return { summaryInfo, forkInfo, ratioInfo, forkRowMap, forks };
}

function populateLifecycle(sheet, raw, analysis, cycleRows) {
  const lastColumn = excelColumn(Math.max(
    LIFECYCLE_SUMMARY_COLUMNS.length,
    LIFECYCLE_FORK_COLUMNS.length,
    LIFECYCLE_CYCLE_COLUMNS.length,
  ));
  styleTitle(
    sheet,
    "Lifecycle Tomcat — sintesi e traiettorie",
    "Redeploy, warning, firme thread e pendenze diagnostiche sono riportati separatamente. Una singola metrica non viene trattata come prova autonoma di leak.",
    lastColumn,
  );
  sheet.showGridLines = false;
  const summaries = sortByStudyOrder(asArray(analysis.lifecycleSummaries), raw).map((row) => ({
    ...row,
    redeployReadyRateFormula: null,
    jcsSignatureForkRateFormula: null,
  }));
  const forks = sortByStudyOrder(asArray(analysis.lifecycleForks), raw);
  const cycles = sortByStudyOrder(cycleRows, raw);

  styleSection(sheet, 4, "A", lastColumn, "Sintesi per provider");
  const summaryInfo = writeSectionTable(sheet, 5, 1, LIFECYCLE_SUMMARY_COLUMNS, summaries, "LifecycleSummaryV4");
  if (summaries.length) {
    const c = (key) => keyColumn(LIFECYCLE_SUMMARY_COLUMNS, key);
    const formulas = [];
    for (let row = summaryInfo.firstDataRow; row <= summaryInfo.lastDataRow; row += 1) {
      formulas.push([
        `=IFERROR(${c("redeployReadyForkCount")}${row}/${c("forkCount")}${row},"")`,
        `=IFERROR(${c("forksWithJcsThreadSignature")}${row}/${c("forkCount")}${row},"")`,
      ]);
    }
    sheet.getRange(`${c("redeployReadyRateFormula")}${summaryInfo.firstDataRow}:${c("jcsSignatureForkRateFormula")}${summaryInfo.lastDataRow}`).formulas = formulas;
  }

  const forkTitleRow = summaryInfo.lastDataRow + 3;
  styleSection(sheet, forkTitleRow, "A", lastColumn, "Risultati lifecycle per process run");
  const forkInfo = writeSectionTable(sheet, forkTitleRow + 1, 1, LIFECYCLE_FORK_COLUMNS, forks, "LifecycleForksV4");
  if (forks.length) {
    // Preserve the full JSON evidence in-cell without allowing it to expand a
    // single record to hundreds of screen rows. Excel's formula bar still
    // exposes the complete value when the cell is selected.
    sheet.getRange(`A${forkInfo.firstDataRow}:${lastColumn}${forkInfo.lastDataRow}`).format.rowHeight = 22;
    const intervalDetailsColumn = keyColumn(LIFECYCLE_FORK_COLUMNS, "jcs248CorroboratedIntervals");
    sheet.getRange(`${intervalDetailsColumn}${forkInfo.firstDataRow}:${intervalDetailsColumn}${forkInfo.lastDataRow}`).format.wrapText = false;
  }
  const cycleTitleRow = forkInfo.lastDataRow + 3;
  styleSection(sheet, cycleTitleRow, "A", lastColumn, "Osservazioni di deploy/undeploy per ciclo");
  const cycleInfo = writeSectionTable(sheet, cycleTitleRow + 1, 1, LIFECYCLE_CYCLE_COLUMNS, cycles, "LifecycleCyclesV4");
  if (cycles.length) {
    sheet.getRange(`A${cycleInfo.firstDataRow}:${lastColumn}${cycleInfo.lastDataRow}`).format.rowHeight = 22;
    const candidateNamesColumn = keyColumn(LIFECYCLE_CYCLE_COLUMNS, "candidateApplicationThreadsAfterFinalUndeploy");
    sheet.getRange(`${candidateNamesColumn}${cycleInfo.firstDataRow}:${candidateNamesColumn}${cycleInfo.lastDataRow}`).format.wrapText = false;
  }
  sheet.freezePanes.freezeRows(5);
  sheet.freezePanes.freezeColumns(3);

  const summaryRowMap = new Map();
  summaries.forEach((row, index) => summaryRowMap.set(`${row.scenario}|${row.provider}`, summaryInfo.firstDataRow + index));
  const forkRowMap = new Map();
  forks.forEach((row, index) => forkRowMap.set(`${row.scenario}|${row.provider}|${row.fork}`, forkInfo.firstDataRow + index));
  return { summaries, summaryInfo, summaryRowMap, forks, forkRowMap, forkInfo, cycleInfo, lastColumn };
}

function populateJcs248(sheet, analysis, lifecycleLayout) {
  styleTitle(
    sheet,
    "JCS-248 — verifica separata del controllo positivo",
    "Apache Commons JCS 3.2.1 (versione distribuita) è il controllo positivo; Apache Commons JCS 4.0.0-SNAPSHOT da main, identificato dal commit nei Runs, è il target. Il contrasto è separato dal benchmark prestazionale e richiede corroborazione.",
    "L",
  );
  sheet.showGridLines = false;
  sheet.getRange("A3:L3").merge();
  sheet.getRange("A3:L3").values = [["Issue: https://issues.apache.org/jira/browse/JCS-248 — criterio prespecificato: 6 fork validi e segnale corroborato in almeno 5 fork del controllo positivo."]];
  sheet.getRange("A3:L3").format = { fill: COLORS.paleAmber, font: { name: "Aptos", size: 9, color: COLORS.ink }, wrapText: true };
  sheet.getRange("A3:L3").format.rowHeight = 27;

  styleSection(sheet, 5, "A", "K", "Contrasto di controllo: Apache Commons JCS 3.2.1 vs Apache Commons JCS 4.0.0-SNAPSHOT");
  sheet.getRange("A6:K8").values = [JCS_CONTROL_COLUMNS.map((column) => column.label), ["jcs321", ...Array(10).fill(null)], ["jcs4", ...Array(10).fill(null)]];
  styleHeader(sheet.getRange("A6:K6"));
  styleBody(sheet.getRange("A7:K8"));

  const life = (key) => excelColumn(keyIndex(LIFECYCLE_SUMMARY_COLUMNS, key) + 1);
  for (const [row, provider] of [[7, "jcs321"], [8, "jcs4"]]) {
    const sourceRow = lifecycleLayout.summaryRowMap.get(`default|${provider}`)
      ?? [...lifecycleLayout.summaryRowMap.entries()].find(([key]) => key.endsWith(`|${provider}`))?.[1];
    if (!sourceRow) continue;
    const directKeys = [
      "studyRole", "forkCount", "observedForkCount", "redeployReadyForkCount",
      "forksWithThreadLeakWarning", "forksWithJcsThreadSignature",
      "forksWithJcs248CorroboratedSignal", "jcs248PositiveControlCriterionMet",
    ];
    const directFormulas = directKeys.map((key) => `=${cellRef("Lifecycle", life(key), sourceRow)}`);
    const recomputed = `=AND(A${row}="jcs321",C${row}=${CONSTANT_REFS.jcs248RequiredForks},H${row}>=${CONSTANT_REFS.jcs248MinimumCorroboratedForks})`;
    sheet.getRange(`B${row}:K${row}`).formulas = [[...directFormulas, recomputed, `=I${row}=J${row}`]];
  }
  addExcelTable(sheet, "A6:K8", "Jcs248ControlContrastV4");
  sheet.getRange("C7:H8").setNumberFormat("0");

  const intervals = sortByStudyOrder(
    asArray(analysis.lifecycleForks).filter((row) => ["jcs321", "jcs4"].includes(row.provider)),
    { providers: ["jcs321", "jcs4"] },
  ).map((row) => ({ ...row, jcs248CorroboratedIntervals: clippedJson(row.jcs248CorroboratedIntervals) }));
  styleSection(sheet, 11, "A", "G", "Intervalli corroborati per process run");
  const intervalInfo = writeSectionTable(sheet, 12, 1, JCS_INTERVAL_COLUMNS, intervals, "Jcs248IntervalsV4");
  if (intervals.length) {
    sheet.getRange(`A${intervalInfo.firstDataRow}:G${intervalInfo.lastDataRow}`).format.rowHeight = 22;
    sheet.getRange(`G${intervalInfo.firstDataRow}:G${intervalInfo.lastDataRow}`).format.wrapText = false;
  }

  const evidence = sortByStudyOrder(
    asArray(analysis.observations).filter((row) => ["jcs321", "jcs4"].includes(row.provider)),
    { providers: ["jcs321", "jcs4"] },
  );
  const evidenceTitleRow = intervalInfo.lastDataRow + 3;
  styleSection(sheet, evidenceTitleRow, "A", "L", "Evidenza per ciclo e fase");
  const evidenceInfo = writeSectionTable(sheet, evidenceTitleRow + 1, 1, JCS_EVIDENCE_COLUMNS, evidence, "Jcs248EvidenceV4");
  sheet.freezePanes.freezeRows(6);
  sheet.freezePanes.freezeColumns(2);
  return { intervalInfo, evidenceInfo };
}

function configureChart(chart, title, numberFormat, colors = []) {
  chart.title = title;
  chart.titleTextStyle.fontSize = 12;
  chart.hasLegend = true;
  chart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 8 } };
  chart.yAxis = { numberFormatCode: numberFormat, textStyle: { fontSize: 8 } };
  asArray(chart.series?.items).forEach((series, index) => {
    series.fill = colors[index] ?? COLORS.blue;
  });
}

function writeFigureHelper(sheet, startRow, columns, rows, name) {
  styleSection(sheet, startRow, "A", excelColumn(columns.length), name);
  const headerRow = startRow + 1;
  const matrix = [columns, ...rows.map((row) => row.map(safeCellValue))];
  const endRow = headerRow + matrix.length - 1;
  sheet.getRange(`A${headerRow}:${excelColumn(columns.length)}${endRow}`).values = matrix;
  styleHeader(sheet.getRange(`A${headerRow}:${excelColumn(columns.length)}${headerRow}`), COLORS.teal);
  if (rows.length) styleBody(sheet.getRange(`A${headerRow + 1}:${excelColumn(columns.length)}${endRow}`));
  return { headerRow, firstDataRow: headerRow + 1, lastDataRow: endRow, endRow, columnCount: columns.length };
}

function populateFigures(sheet, raw, performanceLayout, lifecycleLayout, snapshotRowMap) {
  styleTitle(
    sheet,
    "Figure — protocollo primario e diagnostica di lifecycle",
    "Grafici formula-backed. Le barre confrontano fork distinti; le sole linee collegano i cinque cicli della stessa JVM. Nessuna falsa continuità fra process run e nessun ranking per risultato.",
    "AA",
  );
  sheet.showGridLines = false;

  const primaryForks = performanceLayout.forks.filter((row) => row.analysisSet === "primary-all-cycles");
  const throughputPairs = [];
  for (const provider of asArray(raw.providers)) {
    for (let fork = 1; fork <= (raw.forks ?? 0); fork += 1) {
      const initial = primaryForks.find((row) => row.provider === provider && row.fork === fork && row.phase === "initial" && row.includedInPerformanceSummary);
      const redeploy = primaryForks.find((row) => row.provider === provider && row.fork === fork && row.phase === "redeploy" && row.includedInPerformanceSummary);
      if (initial && redeploy) throughputPairs.push({ provider, fork, initial, redeploy });
    }
  }

  const throughputHelper = writeFigureHelper(
    sheet,
    4,
    ["provider / fork", "initial (ops/s)", "redeploy (ops/s)"],
    throughputPairs.map(() => [null, null, null]),
    "Throughput per fork e fase — primary all cycles",
  );
  const perfCol = (key) => keyColumn(PERFORMANCE_FORK_COLUMNS, key);
  throughputPairs.forEach((pair, index) => {
    const row = throughputHelper.firstDataRow + index;
    const initialRow = performanceLayout.forkRowMap.get(`${pair.provider}|${pair.fork}|initial|primary-all-cycles`);
    const redeployRow = performanceLayout.forkRowMap.get(`${pair.provider}|${pair.fork}|redeploy|primary-all-cycles`);
    sheet.getRange(`A${row}:C${row}`).formulas = [[
      `=${cellRef("Performance", perfCol("provider"), initialRow)}&" / F"&${cellRef("Performance", perfCol("fork"), initialRow)}`,
      `=${cellRef("Performance", perfCol("comparisonMedian_operationsPerSecond"), initialRow)}`,
      `=${cellRef("Performance", perfCol("comparisonMedian_operationsPerSecond"), redeployRow)}`,
    ]];
  });
  if (throughputPairs.length) {
    sheet.getRange(`B${throughputHelper.firstDataRow}:C${throughputHelper.lastDataRow}`).setNumberFormat("#,##0");
    const chart = sheet.charts.add("bar", sheet.getRange(`A${throughputHelper.headerRow}:C${throughputHelper.lastDataRow}`));
    configureChart(chart, "Throughput per JVM e fase (ops/s)", "#,##0", [COLORS.blue, COLORS.teal]);
    chart.setPosition("I3", "Q30");
  }

  const p99Start = Math.max(32, throughputHelper.endRow + 3);
  const p99Helper = writeFigureHelper(
    sheet,
    p99Start,
    ["provider / fork", "initial p99 (µs)", "redeploy p99 (µs)"],
    throughputPairs.map(() => [null, null, null]),
    "Latenza p99 per fork e fase — primary all cycles",
  );
  throughputPairs.forEach((pair, index) => {
    const row = p99Helper.firstDataRow + index;
    const initialRow = performanceLayout.forkRowMap.get(`${pair.provider}|${pair.fork}|initial|primary-all-cycles`);
    const redeployRow = performanceLayout.forkRowMap.get(`${pair.provider}|${pair.fork}|redeploy|primary-all-cycles`);
    sheet.getRange(`A${row}:C${row}`).formulas = [[
      `=${cellRef("Performance", perfCol("provider"), initialRow)}&" / F"&${cellRef("Performance", perfCol("fork"), initialRow)}`,
      `=${cellRef("Performance", perfCol("comparisonMedian_latencyP99MicrosFormula"), initialRow)}`,
      `=${cellRef("Performance", perfCol("comparisonMedian_latencyP99MicrosFormula"), redeployRow)}`,
    ]];
  });
  if (throughputPairs.length) {
    sheet.getRange(`B${p99Helper.firstDataRow}:C${p99Helper.lastDataRow}`).setNumberFormat("#,##0.000");
    const chart = sheet.charts.add("bar", sheet.getRange(`A${p99Helper.headerRow}:C${p99Helper.lastDataRow}`));
    configureChart(chart, "Latenza p99 per JVM e fase (µs)", "#,##0.000", [COLORS.blue, COLORS.teal]);
    chart.setPosition("S3", "AA30");
  }

  const cycleCount = raw.cyclesPerProcessRun ?? Math.max(0, ...asArray(raw.processRuns).flatMap((run) => asArray(run.cycles).map((cycle) => cycle.cycle)));
  function populateJcsThreadTrajectories(startRow, provider, fullName, chartPosition) {
    const rows = Array.from({ length: cycleCount }, (_, index) => [index + 1, ...Array.from({ length: raw.forks }, () => null)]);
    const helper = writeFigureHelper(
      sheet,
      startRow,
      ["cycle", ...Array.from({ length: raw.forks }, (_, index) => `fork ${index + 1}`)],
      rows,
      `${fullName}: firme thread al checkpoint finale dopo il secondo undeploy (una serie per JVM)`,
    );
    const signatureColumn = keyColumn(SNAPSHOT_COLUMNS, "jcsThreadSignatureCount");
    for (let cycleIndex = 0; cycleIndex < cycleCount; cycleIndex += 1) {
      const targetRow = helper.firstDataRow + cycleIndex;
      const formulas = Array.from({ length: raw.forks }, (_, forkIndex) => {
        const sourceRow = snapshotRowMap.get(`${provider}|${forkIndex + 1}|${cycleIndex + 1}|afterFinalUndeploy`);
        assert(sourceRow, `Missing final snapshot row for ${provider} fork ${forkIndex + 1} cycle ${cycleIndex + 1}`);
        return `=${cellRef("Snapshots Raw", signatureColumn, sourceRow)}`;
      });
      sheet.getRange(`B${targetRow}:${excelColumn(raw.forks + 1)}${targetRow}`).formulas = [formulas];
    }
    sheet.getRange(`B${helper.firstDataRow}:${excelColumn(raw.forks + 1)}${helper.lastDataRow}`).setNumberFormat("0");
    const chart = sheet.charts.add("line", sheet.getRange(`A${helper.headerRow}:${excelColumn(raw.forks + 1)}${helper.lastDataRow}`));
    configureChart(chart, `${fullName}: firme thread per singola JVM`, "0", [COLORS.red, "#C65D60", "#D97A7D", COLORS.amber, "#E4B766", COLORS.teal]);
    chart.setPosition(chartPosition[0], chartPosition[1]);
    return helper;
  }

  const jcs321ThreadHelper = populateJcsThreadTrajectories(
    p99Helper.endRow + 3,
    "jcs321",
    "Apache Commons JCS 3.2.1",
    ["I32", "Q50"],
  );
  const jcs4ThreadHelper = populateJcsThreadTrajectories(
    jcs321ThreadHelper.endRow + 3,
    "jcs4",
    "Apache Commons JCS 4.0.0-SNAPSHOT",
    ["S32", "AA50"],
  );

  const lifecycleForks = lifecycleLayout.forks;
  function populateForkSlope(startRow, title, valueKey, format, divisor, chartTitle, chartPosition, color) {
    const helper = writeFigureHelper(
      sheet,
      startRow,
      ["provider / fork", title],
      lifecycleForks.map(() => [null, null]),
      `${title}: una barra per process run indipendente`,
    );
    const sourceColumn = keyColumn(LIFECYCLE_FORK_COLUMNS, valueKey);
    lifecycleForks.forEach((forkRow, index) => {
      const targetRow = helper.firstDataRow + index;
      const sourceRow = lifecycleLayout.forkRowMap.get(`${forkRow.scenario}|${forkRow.provider}|${forkRow.fork}`);
      assert(sourceRow, `Missing lifecycle fork row for ${forkRow.provider} fork ${forkRow.fork}`);
      const sourceCell = cellRef("Lifecycle", sourceColumn, sourceRow);
      sheet.getRange(`A${targetRow}:B${targetRow}`).formulas = [[
        `=${cellRef("Lifecycle", keyColumn(LIFECYCLE_FORK_COLUMNS, "provider"), sourceRow)}&" / F"&${cellRef("Lifecycle", keyColumn(LIFECYCLE_FORK_COLUMNS, "fork"), sourceRow)}`,
        divisor ? `=${sourceCell}/${divisor}` : `=${sourceCell}`,
      ]];
    });
    sheet.getRange(`B${helper.firstDataRow}:B${helper.lastDataRow}`).setNumberFormat(format);
    const chart = sheet.charts.add("bar", sheet.getRange(`A${helper.headerRow}:B${helper.lastDataRow}`));
    configureChart(chart, chartTitle, format, [color]);
    chart.setPosition(chartPosition[0], chartPosition[1]);
    return helper;
  }

  const heapHelper = populateForkSlope(
    jcs4ThreadHelper.endRow + 3,
    "heap slope (MiB/cycle)",
    "absoluteFinalHeapSlopeBytesPerCycle",
    "0.000",
    CONSTANT_REFS.bytesPerMiB,
    "Pendenza heap post-undeploy per singola JVM (MiB/ciclo)",
    ["I52", "Q70"],
    COLORS.blue,
  );
  const nmtHelper = populateForkSlope(
    heapHelper.endRow + 3,
    "NMT slope (MiB/cycle)",
    "absoluteFinalNativeCommittedSlopeBytesPerCycle",
    "0.000",
    CONSTANT_REFS.bytesPerMiB,
    "Pendenza NMT post-undeploy per singola JVM (MiB/ciclo)",
    ["S52", "AA70"],
    COLORS.teal,
  );
  const classloaderHelper = populateForkSlope(
    nmtHelper.endRow + 3,
    "classloader-row slope (rows/cycle)",
    "absoluteFinalWebappClassloaderSlopePerCycle",
    "0.000",
    null,
    "Pendenza righe classloader per singola JVM (righe/ciclo)",
    ["I72", "Q90"],
    COLORS.amber,
  );

  const jcsForks = lifecycleForks.filter((row) => ["jcs321", "jcs4"].includes(row.provider));
  const corroborationHelper = writeFigureHelper(
    sheet,
    classloaderHelper.endRow + 3,
    ["provider / fork", "corroborated undeploy intervals"],
    jcsForks.map(() => [null, null]),
    "JCS-248: intervalli corroborati per singola process run",
  );
  const corroborationColumn = keyColumn(LIFECYCLE_FORK_COLUMNS, "jcs248CorroboratedUndeployCount");
  jcsForks.forEach((forkRow, index) => {
    const targetRow = corroborationHelper.firstDataRow + index;
    const sourceRow = lifecycleLayout.forkRowMap.get(`${forkRow.scenario}|${forkRow.provider}|${forkRow.fork}`);
    sheet.getRange(`A${targetRow}:B${targetRow}`).formulas = [[
      `=${cellRef("Lifecycle", keyColumn(LIFECYCLE_FORK_COLUMNS, "provider"), sourceRow)}&" / F"&${cellRef("Lifecycle", keyColumn(LIFECYCLE_FORK_COLUMNS, "fork"), sourceRow)}`,
      `=${cellRef("Lifecycle", corroborationColumn, sourceRow)}`,
    ]];
  });
  sheet.getRange(`B${corroborationHelper.firstDataRow}:B${corroborationHelper.lastDataRow}`).setNumberFormat("0");
  const corroborationChart = sheet.charts.add("bar", sheet.getRange(`A${corroborationHelper.headerRow}:B${corroborationHelper.lastDataRow}`));
  configureChart(corroborationChart, "JCS-248: corroborazione per JVM", "0", [COLORS.red]);
  corroborationChart.setPosition("S72", "AA90");

  const lastFigureRow = corroborationHelper.endRow;
  sheet.getRange(`A1:A${lastFigureRow + 2}`).format.columnWidth = 34;
  sheet.getRange(`B1:G${lastFigureRow + 2}`).format.columnWidth = 18;
  sheet.getRange(`H1:H${lastFigureRow + 2}`).format.columnWidth = 3;
  sheet.freezePanes.freezeRows(2);
  return { lastRow: lastFigureRow, corroborationHelper, heapHelper, nmtHelper, classloaderHelper };
}

function dictionaryRows(tableDefinitions) {
  const rows = [];
  for (const definition of tableDefinitions) {
    for (const column of definition.columns) {
      rows.push({
        sheet: definition.sheet,
        table: definition.table,
        columnHeader: column.label,
        fieldOrFormula: column.key,
        unit: column.unit,
        dataType: column.type,
        source: column.source,
        definition: column.definition,
      });
    }
  }
  rows.push(
    { sheet: "All", table: "Glossary", columnHeader: "fork", fieldOrFormula: "fork", unit: "JVM", dataType: "identifier", source: "Protocollo v4.2", definition: "Una process run in un container/JVM indipendente; è l'unità statistica." },
    { sheet: "All", table: "Glossary", columnHeader: "cycle", fieldOrFormula: "cycle", unit: "cycle", dataType: "identifier", source: "Protocollo v4.2", definition: "Ripetizione interna alla stessa JVM; non è una replica statistica indipendente." },
    { sheet: "All", table: "Glossary", columnHeader: "primary-all-cycles", fieldOrFormula: "analysisSet", unit: "", dataType: "category", source: "Protocollo v4.2", definition: "Analisi primaria prespecificata: mediana dei cicli 1–5 dentro ciascuna JVM, poi descrizione fra JVM." },
    { sheet: "All", table: "Glossary", columnHeader: "sensitivity-without-cycle-1", fieldOrFormula: "analysisSet", unit: "", dataType: "category", source: "Protocollo v4.2", definition: "Analisi di sensibilità prespecificata: omette il ciclo 1 prima di calcolare la mediana interna alla JVM." },
    { sheet: "All", table: "Glossary", columnHeader: "findleaks occurrence", fieldOrFormula: "tomcatFindLeaksOccurrences", unit: "occurrence", dataType: "diagnostic", source: "Tomcat Manager findleaks", definition: "Occorrenza testuale conservata con molteplicità; non è da sola prova causale di leak." },
    { sheet: "All", table: "Glossary", columnHeader: "raw worksheets", fieldOrFormula: "flattened views", unit: "", dataType: "provenance", source: "Builder", definition: "Viste appiattite di comodo. La struttura e i JSON identificati dai checksum restano autorevoli." },
  );
  return rows;
}

const DICTIONARY_COLUMNS = [
  descriptor("sheet", "sheet", { source: "Builder", width: 20 }),
  descriptor("table", "table / section", { source: "Builder", width: 28 }),
  descriptor("columnHeader", "column header", { source: "Builder", width: 38 }),
  descriptor("fieldOrFormula", "JSON field / formula key", { source: "Builder", width: 44 }),
  descriptor("unit", "unit", { source: "Builder", width: 18 }),
  descriptor("dataType", "data type", { source: "Builder", width: 15 }),
  descriptor("source", "source", { source: "Builder", width: 22 }),
  descriptor("definition", "definition / interpretation", { source: "Builder", width: 76, wrap: true }),
];

function populateDictionary(sheet, definitions) {
  const rows = dictionaryRows(definitions);
  return writeFlatSheet(sheet, DICTIONARY_COLUMNS, rows, { tableName: "DataDictionaryV4", freezeColumns: 4 });
}

function inspectionRecords(result) {
  const ndjson = result?.ndjson ?? "";
  return String(ndjson)
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return { unparsedInspectionLine: line };
      }
    });
}

function flattenScalars(value, output = []) {
  if (Array.isArray(value)) {
    value.forEach((item) => flattenScalars(item, output));
  } else if (!isRecord(value)) {
    output.push(value);
  }
  return output;
}

function assertFormulaAgreement(values, expectedRows, label) {
  const booleans = flattenScalars(values).filter((value) => [true, false, "TRUE", "FALSE", "true", "false", 1, 0].includes(value));
  const failed = booleans.filter((value) => value === false || value === "FALSE" || value === "false" || value === 0);
  assert(booleans.length >= expectedRows, `${label} formula inspection returned only ${booleans.length}/${expectedRows} calculated boolean rows`);
  assert(failed.length === 0, `${failed.length} ${label} formula rows disagree with their source values; export refused`);
}

function formulaErrorLocations(inspection) {
  const errorTokens = ["#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A"];
  const ignoredKeys = new Set(["searchTerm", "summary", "query", "pattern", "regex"]);
  const hits = [];
  const walk = (value, hasLocation, trail) => {
    if (typeof value === "string") {
      const token = errorTokens.find((candidate) => value.includes(candidate));
      if (token && hasLocation) hits.push(`${trail.join(".")}: ${token}`);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item, index) => walk(item, hasLocation, [...trail, String(index)]));
      return;
    }
    if (!isRecord(value)) return;
    const located = hasLocation || Object.keys(value).some((key) => /^(address|cell|location|range|sheet|sheetId|sheetName|worksheet)$/i.test(key));
    for (const [key, child] of Object.entries(value)) {
      if (ignoredKeys.has(key)) continue;
      if (/^(matchCount|totalMatches|resultCount)$/i.test(key) && typeof child === "number" && child > 0) {
        hits.push(`${trail.join(".")}.${key}: ${child} matches`);
      }
      walk(child, located, [...trail, key]);
    }
  };
  inspectionRecords(inspection).forEach((record, index) => walk(record, false, [`record${index + 1}`]));
  return hits;
}

async function inspectRepresentativeWorkbookState(workbook, layouts, qcRows) {
  const inspections = [];
  inspections.push(await workbook.inspect({
    kind: "table",
    range: "Runs!A1:H4",
    include: "values,formulas",
    tableMaxRows: 4,
    tableMaxCols: 8,
    maxChars: 5000,
  }));

  const versionStart = keyColumn(RUN_COLUMNS, "providerVersionRuntime");
  const versionEnd = keyColumn(RUN_COLUMNS, "providerVersionEvidence");
  inspections.push(await workbook.inspect({
    kind: "table",
    range: `Runs!${versionStart}1:${versionEnd}4`,
    include: "values,formulas",
    tableMaxRows: 4,
    tableMaxCols: 6,
    maxChars: 5000,
  }));
  const manifestStart = keyColumn(RUN_COLUMNS, "artifactManifestJson");
  const manifestEnd = keyColumn(RUN_COLUMNS, "dependencyTreeSizeBytes");
  inspections.push(await workbook.inspect({
    kind: "table",
    range: `Runs!${manifestStart}1:${manifestEnd}3`,
    include: "values,formulas",
    tableMaxRows: 3,
    tableMaxCols: 10,
    maxChars: 9000,
  }));

  const noStoreIndex = qcRows.findIndex((row) => row.provider === "nostore");
  assert(noStoreIndex >= 0, "No nostore QC row is available for representative inspection");
  const noStoreRow = layouts.flat["QC Gates"].firstDataRow + noStoreIndex;
  const noStoreStart = keyColumn(QC_COLUMNS, "gateType");
  const noStoreEnd = keyColumn(QC_COLUMNS, "formulaMatchesRunner");
  inspections.push(await workbook.inspect({
    kind: "table",
    range: `QC Gates!${noStoreStart}${noStoreRow}:${noStoreEnd}${noStoreRow}`,
    include: "values,formulas",
    tableMaxRows: 2,
    tableMaxCols: QC_COLUMNS.length,
    maxChars: 12000,
  }));

  inspections.push(await workbook.inspect({
    kind: "table",
    range: `JCS-248!A1:L${Math.min(18, layouts.jcs248.intervalInfo.lastDataRow)}`,
    include: "values,formulas",
    tableMaxRows: 18,
    tableMaxCols: 12,
    maxChars: 12000,
  }));
  inspections.push(await workbook.inspect({
    kind: "table",
    range: "Figures!A1:G15",
    include: "values,formulas",
    tableMaxRows: 15,
    tableMaxCols: 7,
    maxChars: 10000,
  }));
  inspections.push(await workbook.inspect({
    kind: "table",
    range: `Figures!A${layouts.figures.corroborationHelper.headerRow}:B${layouts.figures.corroborationHelper.lastDataRow}`,
    include: "values,formulas",
    tableMaxRows: 16,
    tableMaxCols: 2,
    maxChars: 8000,
  }));
  inspections.push(await workbook.inspect({
    kind: "drawing",
    sheetId: "Figures",
    summary: "representative chart inspection",
  }));

  for (const inspection of inspections) console.log(inspection.ndjson);

  const agreementColumn = keyColumn(QC_COLUMNS, "formulaMatchesRunner");
  const qcAgreementInspection = await workbook.inspect({
    kind: "table",
    range: `QC Gates!${agreementColumn}1:${agreementColumn}${layouts.flat["QC Gates"].lastDataRow}`,
    include: "values",
    tableMaxRows: layouts.flat["QC Gates"].lastDataRow,
    tableMaxCols: 1,
    maxChars: 60000,
  });
  console.log(qcAgreementInspection.ndjson);
  const qcAgreementValues = workbook.worksheets
    .getItem("QC Gates")
    .getRange(`${agreementColumn}${layouts.flat["QC Gates"].firstDataRow}:${agreementColumn}${layouts.flat["QC Gates"].lastDataRow}`)
    .values;
  assertFormulaAgreement(qcAgreementValues, qcRows.length, "QC gate");
  const jcsContrastAgreement = workbook.worksheets.getItem("JCS-248").getRange("K7:K8").values;
  assertFormulaAgreement(jcsContrastAgreement, 2, "JCS-248 contrast");

  const formulaErrorInspection = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "blocking final formula error scan",
  });
  console.log(formulaErrorInspection.ndjson);
  const errors = formulaErrorLocations(formulaErrorInspection);
  assert(errors.length === 0, `Formula errors detected; export refused:\n${errors.slice(0, 30).join("\n")}`);
}

function renderSpecFor(sheetName, layouts) {
  const flat = layouts.flat[sheetName];
  if (flat) {
    const rows = Math.min(Math.max(flat.lastDataRow, 2), 35);
    return { range: `A1:${flat.lastColumn}${rows}`, scale: 0.6 };
  }
  if (sheetName === "Readme-Protocol") return { range: "A1:I84", scale: 0.75 };
  if (sheetName === "Performance") return { range: `A1:AG${layouts.performance.ratioInfo.lastDataRow}`, scale: 0.4 };
  if (sheetName === "Lifecycle") return { range: `A1:${layouts.lifecycle.lastColumn}${layouts.lifecycle.cycleInfo.lastDataRow}`, scale: 0.3 };
  if (sheetName === "JCS-248") return { range: `A1:L${layouts.jcs248.evidenceInfo.lastDataRow}`, scale: 0.55 };
  if (sheetName === "Figures") return { range: `A1:AA${Math.max(75, layouts.figures.lastRow)}`, scale: 0.65 };
  if (sheetName === "Dictionary") return { range: "A1:H40", scale: 0.75 };
  return { range: "A1:Z35", scale: 0.65 };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const args = await resolveCampaignFiles(options);
  assert(path.extname(args.outputPath).toLowerCase() === ".xlsx", "Fixed workbook output must end in .xlsx");
  assert(path.resolve(args.outputPath) === path.resolve(OUTPUT_PATH), `Workbook output must be ${OUTPUT_PATH}`);
  const [rawBuffer, analysisBuffer, paperValuesBuffer] = await Promise.all([
    fs.readFile(args.rawPath),
    fs.readFile(args.analysisPath),
    fs.readFile(args.paperValuesPath),
  ]);
  const raw = parseJson(rawBuffer, args.rawPath);
  const analysis = parseJson(analysisBuffer, args.analysisPath);
  const paperValues = parseJson(paperValuesBuffer, args.paperValuesPath);
  assert(Number(raw.schemaVersion) === 4, `Expected results schemaVersion 4, found ${raw.schemaVersion}`);
  assert(Number(analysis.schemaVersion) === 4, `Expected analysis schemaVersion 4, found ${analysis.schemaVersion}`);
  assert(Array.isArray(raw.processRuns), "results.json is missing processRuns[]");
  assert(Array.isArray(analysis.summaries), "analysis.json is missing summaries[]");
  const analysisSha = sha256(analysisBuffer);
  if (raw.analysisSha256) {
    assert(raw.analysisSha256.toLowerCase() === analysisSha.toLowerCase(), "analysis.json SHA-256 does not match results.analysisSha256");
  }

  const files = {
    ...args,
    rawSha: sha256(rawBuffer),
    analysisSha,
    paperValuesSha: sha256(paperValuesBuffer),
  };
  validateFinalInputs(raw, analysis, paperValues, files);
  const roles = roleMaps(analysis);
  const runRows = flattenRuns(raw, roles);
  const workloadRows = flattenWorkloads(raw, roles);
  const snapshotRows = flattenSnapshots(raw);
  const snapshotRowMap = new Map();
  snapshotRows.forEach((row, index) => {
    snapshotRowMap.set(`${row.provider}|${row.fork}|${row.cycle}|${row.snapshotName}`, index + 2);
  });
  const threadRows = flattenThreadEvidence(raw);
  const eventRows = flattenEvents(raw);
  const qcRows = flattenQualityGates(raw, analysis);
  const lifecycleCycleRows = flattenLifecycleCycles(raw);

  const workbook = Workbook.create();
  const sheets = Object.fromEntries(SHEET_NAMES.map((name) => [name, workbook.worksheets.add(name)]));

  populateReadme(sheets["Readme-Protocol"], raw, analysis, paperValues, files);
  const runsInfo = populateRuns(sheets.Runs, runRows);
  const workloadsInfo = writeFlatSheet(sheets["Workloads Raw"], WORKLOAD_COLUMNS, workloadRows, { tableName: "WorkloadsRawV4", freezeColumns: 10 });
  const snapshotsInfo = writeFlatSheet(sheets["Snapshots Raw"], SNAPSHOT_COLUMNS, snapshotRows, { tableName: "SnapshotsRawV4", freezeColumns: 9 });
  const threadsInfo = writeFlatSheet(sheets["Thread Evidence"], THREAD_COLUMNS, threadRows, { tableName: "ThreadEvidenceV4", freezeColumns: 10 });
  const eventsInfo = writeFlatSheet(sheets["Events-Warnings"], EVENT_COLUMNS, eventRows, { tableName: "EventsWarningsV4", freezeColumns: 10 });
  const qcInfo = populateQualityGates(sheets["QC Gates"], qcRows);
  const performanceLayout = populatePerformance(sheets.Performance, raw, analysis);
  const lifecycleLayout = populateLifecycle(sheets.Lifecycle, raw, analysis, lifecycleCycleRows);
  const jcs248Layout = populateJcs248(sheets["JCS-248"], analysis, lifecycleLayout);
  const figuresLayout = populateFigures(sheets.Figures, raw, performanceLayout, lifecycleLayout, snapshotRowMap);

  const definitions = [
    { sheet: "Runs", table: "RunsV4", columns: RUN_COLUMNS },
    { sheet: "Workloads Raw", table: "WorkloadsRawV4", columns: WORKLOAD_COLUMNS },
    { sheet: "Snapshots Raw", table: "SnapshotsRawV4", columns: SNAPSHOT_COLUMNS },
    { sheet: "Thread Evidence", table: "ThreadEvidenceV4", columns: THREAD_COLUMNS },
    { sheet: "Events-Warnings", table: "EventsWarningsV4", columns: EVENT_COLUMNS },
    { sheet: "QC Gates", table: "QualityGatesV4", columns: QC_COLUMNS },
    { sheet: "Performance", table: "PerformanceSummaryV4", columns: PERFORMANCE_SUMMARY_COLUMNS },
    { sheet: "Performance", table: "PerformanceForksV4", columns: PERFORMANCE_FORK_COLUMNS },
    { sheet: "Performance", table: "PairedRatiosV4", columns: PAIRED_RATIO_COLUMNS },
    { sheet: "Lifecycle", table: "LifecycleSummaryV4", columns: LIFECYCLE_SUMMARY_COLUMNS },
    { sheet: "Lifecycle", table: "LifecycleForksV4", columns: LIFECYCLE_FORK_COLUMNS },
    { sheet: "Lifecycle", table: "LifecycleCyclesV4", columns: LIFECYCLE_CYCLE_COLUMNS },
    { sheet: "JCS-248", table: "Jcs248ControlContrastV4", columns: JCS_CONTROL_COLUMNS },
    { sheet: "JCS-248", table: "Jcs248IntervalsV4", columns: JCS_INTERVAL_COLUMNS },
    { sheet: "JCS-248", table: "Jcs248EvidenceV4", columns: JCS_EVIDENCE_COLUMNS },
  ];
  const dictionaryInfo = populateDictionary(sheets.Dictionary, definitions);

  const layouts = {
    flat: {
      Runs: runsInfo,
      "Workloads Raw": workloadsInfo,
      "Snapshots Raw": snapshotsInfo,
      "Thread Evidence": threadsInfo,
      "Events-Warnings": eventsInfo,
      "QC Gates": qcInfo,
      Dictionary: dictionaryInfo,
    },
    figures: figuresLayout,
    performance: performanceLayout,
    lifecycle: lifecycleLayout,
    jcs248: jcs248Layout,
  };

  await inspectRepresentativeWorkbookState(workbook, layouts, qcRows);

  await fs.mkdir(path.dirname(args.outputPath), { recursive: true });
  await fs.mkdir(args.renderDir, { recursive: true });

  for (let index = 0; index < SHEET_NAMES.length; index += 1) {
    const sheetName = SHEET_NAMES[index];
    const spec = renderSpecFor(sheetName, layouts);
    const preview = await workbook.render({ sheetName, range: spec.range, scale: spec.scale, format: "png" });
    const fileName = `${String(index + 1).padStart(2, "0")}-${sheetName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.png`;
    await fs.writeFile(path.join(args.renderDir, fileName), new Uint8Array(await preview.arrayBuffer()));
    console.log(`Rendered ${sheetName} -> ${fileName} (${spec.range})`);
  }

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(args.outputPath);
  console.log(`Workbook exported: ${args.outputPath}`);
}

main().catch((error) => {
  console.error(error.stack ?? error.message ?? String(error));
  process.exitCode = 1;
});

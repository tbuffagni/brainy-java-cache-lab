package it.tekne.benchmark.workload;

import it.tekne.benchmark.cache.ProviderMetrics;

public record BenchmarkResult(
        String provider,
        BenchmarkRequest configuration,
        long warmupOperationsExecuted,
        long warmupNanos,
        long warmupOvershootNanos,
        String accessPlanSha256,
        double fillOperationsPerSecond,
        double operationsPerSecond,
        long measuredOperations,
        long measurementNanos,
        long measurementOvershootNanos,
        double readOperationsPerSecond,
        long readOperations,
        long concurrentWriteOperations,
        double writeProbeOperationsPerSecond,
        long latencyP50Nanos,
        long latencyP95Nanos,
        long latencyP99Nanos,
        int measuredLatencySamples,
        long loaderInvocationsUnderContention,
        boolean singleFlightPassed,
        ProviderMetrics providerMetricsAfterWorkload,
        ProviderMetrics providerMetricsAfterWriteProbe,
        ProviderMetrics providerMetrics) {
}

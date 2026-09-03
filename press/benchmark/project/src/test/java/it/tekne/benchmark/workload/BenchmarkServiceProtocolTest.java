package it.tekne.benchmark.workload;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockServletContext;

class BenchmarkServiceProtocolTest {
    @Test
    void generatedAsciiPayloadHasExactlyTheRequestedByteLength() {
        for (long id : new long[] {0L, 9L, 10_000L, Long.MAX_VALUE}) {
            String value = BenchmarkService.value(id, 512);
            assertEquals(512, value.length());
            assertEquals(512, value.getBytes(java.nio.charset.StandardCharsets.UTF_8).length);
        }
    }

    @Test
    void timeWindowsAreMinimaAndPlanIsReproducible() throws Exception {
        MockServletContext context = new MockServletContext();
        context.setContextPath("/caffeine");
        BenchmarkService service = new BenchmarkService(context);
        BenchmarkRequest request = new BenchmarkRequest(
                100, 1_000, 2, 95, 64, 500, 0.02, 300,
                "uniform", 0, "strict", 0x5EEDL, 64, 0.02);
        try {
            BenchmarkResult first = service.run(request);
            BenchmarkResult second = service.run(request);

            assertTrue(first.warmupOperationsExecuted() >= request.warmupOperations());
            assertTrue(first.warmupNanos() >= 20_000_000L);
            assertEquals(first.warmupNanos() - 20_000_000L, first.warmupOvershootNanos());
            assertTrue(first.measuredOperations() >= request.operations());
            assertTrue(first.measurementNanos() >= 20_000_000L);
            assertEquals(first.measurementNanos() - 20_000_000L,
                    first.measurementOvershootNanos());
            assertEquals(first.accessPlanSha256(), second.accessPlanSha256());
            assertEquals(64, first.accessPlanSha256().length());
            assertEquals(first.readOperations(),
                    first.providerMetricsAfterWorkload().requestCount());
            assertEquals(first.readOperations(),
                    first.providerMetricsAfterWriteProbe().requestCount());
            assertEquals(request.entries(),
                    first.providerMetricsAfterWorkload().currentEntries());
            assertEquals(request.entries(),
                    first.providerMetricsAfterWriteProbe().currentEntries());
            assertEquals(request.entries(), first.providerMetricsAfterWorkload().putCount());
            assertEquals(request.entries() + Math.max(1, request.entries() / 2),
                    first.providerMetricsAfterWriteProbe().putCount());
            assertEquals(first.providerMetricsAfterWriteProbe(), first.providerMetrics(),
                    "providerMetrics must remain the post-write compatibility alias");

            var json = new ObjectMapper().valueToTree(first);
            assertTrue(json.has("providerMetricsAfterWorkload"));
            assertTrue(json.has("providerMetricsAfterWriteProbe"));
            assertTrue(json.has("providerMetrics"));
            assertFalse(Thread.getAllStackTraces().keySet().stream()
                    .anyMatch(thread -> thread.isAlive()
                            && thread.getName().startsWith("cache-benchmark-")),
                    "the harness must terminate its worker pools before returning");
        } finally {
            service.shutdown();
        }
    }

    @Test
    void noStoreReportsZeroEntriesAtBothCapacityCheckpoints() throws Exception {
        MockServletContext context = new MockServletContext();
        context.setContextPath("/nostore");
        BenchmarkService service = new BenchmarkService(context);
        BenchmarkRequest request = new BenchmarkRequest(
                100, 1_000, 2, 95, 64, 0, 300,
                "uniform", 0, "strict", 0x5EEDL, 64);
        try {
            BenchmarkResult result = service.run(request);

            assertEquals(0, result.providerMetricsAfterWorkload().currentEntries());
            assertEquals(0, result.providerMetricsAfterWriteProbe().currentEntries());
            assertEquals(result.providerMetricsAfterWriteProbe(), result.providerMetrics());
        } finally {
            service.shutdown();
        }
    }
}

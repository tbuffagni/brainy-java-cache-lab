package it.tekne.benchmark.workload;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.ObjectMapper;
import it.tekne.benchmark.cache.JcsMemoryMode;
import org.junit.jupiter.api.Test;

class BenchmarkConfigurationTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void oldRequestPayloadGetsSafeDefaults() throws Exception {
        BenchmarkRequest request = mapper.readValue("""
                {"entries":1000,"operations":1000,"threads":4,"hitPercent":95,
                 "payloadBytes":64,"warmupOperations":0,"ttlSeconds":300}
                """, BenchmarkRequest.class);

        assertEquals(WorkloadType.UNIFORM, request.workloadType());
        assertEquals(JcsMemoryMode.STRICT, request.jcsMode());
        assertEquals(16, request.latencySampleRate());
        assertEquals(0.0, request.warmupSeconds());
        assertEquals(0.0, request.measurementSeconds());
    }

    @Test
    void acceptsStrictJcs4Mode() {
        BenchmarkRequest request = new BenchmarkRequest(1000, 1000, 4, 95, 64, 0, 1,
                "ZIPF", 10, "STRICT", 1, 32);

        assertEquals("zipf", request.workload());
        assertEquals("strict", request.jcsMemoryMode());
    }

    @Test
    void acceptsTimeBoundedMeasurement() {
        BenchmarkRequest request = new BenchmarkRequest(1000, 1000, 4, 95, 64, 0, 2.0, 1,
                "uniform", 10, "strict", 1, 64, 5.0);

        assertEquals(2.0, request.warmupSeconds());
        assertEquals(5.0, request.measurementSeconds());
    }

    @Test
    void rejectsArticleTwoExperimentalMemoryPolicies() {
        assertThrows(IllegalArgumentException.class, () -> new BenchmarkRequest(
                1000, 1000, 4, 95, 64, 0, 300,
                "uniform", 0, "bounded_clock", 1, 16));
    }

    @Test
    void rejectsAnExpiryRunThatWouldPauseForTooLong() {
        assertThrows(IllegalArgumentException.class, () -> new BenchmarkRequest(
                1000, 1000, 4, 95, 64, 0, 300, "expiry", 0, "strict", 1, 16));
    }
}

package it.tekne.benchmark.cache;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class ProviderContractTest {
    @ParameterizedTest
    @ValueSource(strings = {"caffeine", "ehcache", "cache2k", "jcs4", "jcs321"})
    void putGetClearAndSingleFlight(String name) throws Exception {
        try (LocalCacheProvider provider = ProviderFactory.create(name, 100, Duration.ofMinutes(5))) {
            BenchmarkKey key = BenchmarkKey.of(1);
            provider.put(key, "value");
            assertEquals("value", provider.get(key));
            Thread.sleep(750);
            assertEquals("value", provider.get(key),
                    "a five-minute TTL must not be interpreted as 300 milliseconds");
            provider.clear();
            assertNull(provider.get(key));

            AtomicInteger loads = new AtomicInteger();
            CountDownLatch start = new CountDownLatch(1);
            var executor = Executors.newFixedThreadPool(8);
            try {
                var futures = java.util.stream.IntStream.range(0, 8).mapToObj(i -> executor.submit(() -> {
                    start.await();
                    return provider.getOrLoad(key, ignored -> {
                        loads.incrementAndGet();
                        return "loaded";
                    });
                })).toList();
                start.countDown();
                for (var future : futures) assertEquals("loaded", future.get());
            } finally {
                executor.shutdownNow();
                assertTrue(executor.awaitTermination(5, TimeUnit.SECONDS));
            }
            assertEquals(1, loads.get());
        }
    }

    @org.junit.jupiter.api.Test
    void noStoreIsAnExplicitNonRetainingLifecycleControl() {
        try (LocalCacheProvider provider = ProviderFactory.create(
                "nostore", 100, Duration.ofMinutes(5))) {
            BenchmarkKey key = BenchmarkKey.of(1);
            provider.put(key, "value");
            assertNull(provider.get(key));
            assertEquals(0, provider.metrics().currentEntries());
            assertTrue(ProviderFactory.SUPPORTED.contains("nostore"));
        }
    }
}

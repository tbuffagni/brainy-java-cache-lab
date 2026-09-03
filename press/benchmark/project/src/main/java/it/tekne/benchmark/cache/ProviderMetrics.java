package it.tekne.benchmark.cache;

import java.util.Map;

public record ProviderMetrics(
        String provider,
        long currentEntries,
        long requestCount,
        long hitCount,
        long missCount,
        double hitRate,
        long loadSuccessCount,
        long loadFailureCount,
        long totalLoadTimeNanos,
        long evictionCount,
        long expirationCount,
        long putCount,
        long removeCount,
        Map<String, Number> nativeMetrics) {
}

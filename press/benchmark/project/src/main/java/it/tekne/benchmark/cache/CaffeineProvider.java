package it.tekne.benchmark.cache;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import java.time.Duration;
import java.util.LinkedHashMap;

final class CaffeineProvider extends AbstractProvider {
    private final Cache<BenchmarkKey, String> cache;

    CaffeineProvider(long capacity, Duration ttl) {
        cache = Caffeine.newBuilder().maximumSize(capacity).expireAfterWrite(ttl).build();
    }

    public String name() { return "caffeine"; }
    protected String nativeGet(BenchmarkKey key) { return cache.getIfPresent(key); }
    protected void nativePut(BenchmarkKey key, String value) { cache.put(key, value); }
    public void clear() { cache.invalidateAll(); cache.cleanUp(); }

    private java.util.Map<String, Number> nativeMetrics() {
        cache.cleanUp();
        var nativeMetrics = new LinkedHashMap<String, Number>();
        // Caffeine statistics are opt-in and add work to each operation. The
        // benchmark uses the adapter's common counters instead of enabling an
        // optional feature for this provider only.
        nativeMetrics.put("statisticsEnabled", 0);
        return nativeMetrics;
    }

    @Override
    public void resetMetrics() {
        super.resetMetrics();
        snapshotNativeCounters(nativeMetrics(), ignored -> true);
    }

    public ProviderMetrics metrics() {
        var nativeMetrics = nativeMetricsSinceReset(nativeMetrics(), ignored -> true);
        return commonMetrics(cache.estimatedSize(), -1, -1, nativeMetrics);
    }

    public void close() { clear(); }
}

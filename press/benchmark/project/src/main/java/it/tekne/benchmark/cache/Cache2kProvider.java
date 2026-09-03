package it.tekne.benchmark.cache;

import java.time.Duration;
import java.util.LinkedHashMap;
import org.cache2k.Cache;
import org.cache2k.Cache2kBuilder;
import org.cache2k.operation.CacheControl;
import org.cache2k.operation.CacheStatistics;

final class Cache2kProvider extends AbstractProvider {
    private final Cache<BenchmarkKey, String> cache;

    Cache2kProvider(long capacity, Duration ttl) {
        cache = new Cache2kBuilder<BenchmarkKey, String>() {}
                .name("benchmark-" + System.nanoTime())
                .entryCapacity(capacity)
                .expireAfterWrite(ttl)
                .build();
    }

    public String name() { return "cache2k"; }
    protected String nativeGet(BenchmarkKey key) { return cache.peek(key); }
    protected void nativePut(BenchmarkKey key, String value) { cache.put(key, value); }
    public void clear() { cache.clear(); }

    private java.util.Map<String, Number> nativeMetrics() {
        CacheControl control = CacheControl.of(cache);
        CacheStatistics s = control.sampleStatistics();
        var nativeMetrics = new LinkedHashMap<String, Number>();
        nativeMetrics.put("getCount", s.getGetCount());
        nativeMetrics.put("missCount", s.getMissCount());
        nativeMetrics.put("loadCount", s.getLoadCount());
        nativeMetrics.put("loadExceptionCount", s.getLoadExceptionCount());
        nativeMetrics.put("suppressedLoadExceptionCount", s.getSuppressedLoadExceptionCount());
        nativeMetrics.put("refreshCount", s.getRefreshCount());
        nativeMetrics.put("refreshFailedCount", s.getRefreshFailedCount());
        nativeMetrics.put("refreshedHitCount", s.getRefreshedHitCount());
        nativeMetrics.put("expiredCount", s.getExpiredCount());
        nativeMetrics.put("evictedCount", s.getEvictedCount());
        nativeMetrics.put("putCount", s.getPutCount());
        nativeMetrics.put("removeCount", s.getRemoveCount());
        nativeMetrics.put("keyMutationCount", s.getKeyMutationCount());
        nativeMetrics.put("totalLoadMillis", s.getTotalLoadMillis());
        return nativeMetrics;
    }

    @Override
    public void resetMetrics() {
        super.resetMetrics();
        snapshotNativeCounters(nativeMetrics(), ignored -> true);
    }

    public ProviderMetrics metrics() {
        CacheControl control = CacheControl.of(cache);
        var nativeMetrics = nativeMetricsSinceReset(nativeMetrics(), ignored -> true);
        return commonMetrics(control.getSize(), nativeMetrics.get("evictedCount").longValue(),
                nativeMetrics.get("expiredCount").longValue(), nativeMetrics);
    }

    public void close() { cache.close(); }
}

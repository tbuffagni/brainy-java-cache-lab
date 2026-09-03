package it.tekne.benchmark.cache;

import java.util.concurrent.atomic.LongAdder;
import java.util.function.Function;
import java.util.function.Predicate;

abstract class AbstractProvider implements LocalCacheProvider {
    protected final LongAdder requests = new LongAdder();
    protected final LongAdder hits = new LongAdder();
    protected final LongAdder misses = new LongAdder();
    protected final LongAdder loadSuccess = new LongAdder();
    protected final LongAdder loadFailure = new LongAdder();
    protected final LongAdder totalLoadNanos = new LongAdder();
    protected final LongAdder puts = new LongAdder();
    protected final LongAdder removes = new LongAdder();
    private final Object[] loadLocks = new Object[256];
    private java.util.Map<String, Long> nativeCounterBaseline = java.util.Map.of();

    protected AbstractProvider() {
        for (int i = 0; i < loadLocks.length; i++) loadLocks[i] = new Object();
    }

    protected abstract String nativeGet(BenchmarkKey key);
    protected abstract void nativePut(BenchmarkKey key, String value);

    @Override
    public String get(BenchmarkKey key) {
        requests.increment();
        String value = nativeGet(key);
        if (value == null) misses.increment(); else hits.increment();
        return value;
    }

    @Override
    public String getDirect(BenchmarkKey key) {
        return nativeGet(key);
    }

    @Override
    public void put(BenchmarkKey key, String value) {
        nativePut(key, value);
        puts.increment();
    }

    @Override
    public void putDirect(BenchmarkKey key, String value) {
        nativePut(key, value);
    }

    @Override
    public String getOrLoad(BenchmarkKey key, Function<BenchmarkKey, String> loader) {
        String value = get(key);
        if (value != null) return value;
        Object lock = loadLocks[(key.hashCode() & 0x7fffffff) % loadLocks.length];
        synchronized (lock) {
            value = nativeGet(key);
            if (value != null) return value;
            long started = System.nanoTime();
            try {
                value = loader.apply(key);
                if (value == null) throw new NullPointerException("loader returned null");
                nativePut(key, value);
                puts.increment();
                loadSuccess.increment();
                return value;
            } catch (RuntimeException failure) {
                loadFailure.increment();
                throw failure;
            } finally {
                totalLoadNanos.add(System.nanoTime() - started);
            }
        }
    }

    @Override
    public void resetMetrics() {
        requests.reset();
        hits.reset();
        misses.reset();
        loadSuccess.reset();
        loadFailure.reset();
        totalLoadNanos.reset();
        puts.reset();
        removes.reset();
        nativeCounterBaseline = java.util.Map.of();
    }

    protected final void snapshotNativeCounters(java.util.Map<String, Number> metrics,
                                                Predicate<String> isCounter) {
        var baseline = new java.util.LinkedHashMap<String, Long>();
        metrics.forEach((name, value) -> {
            if (isCounter.test(name)) baseline.put(name, value.longValue());
        });
        nativeCounterBaseline = java.util.Map.copyOf(baseline);
    }

    protected final java.util.Map<String, Number> nativeMetricsSinceReset(
            java.util.Map<String, Number> metrics, Predicate<String> isCounter) {
        var normalized = new java.util.LinkedHashMap<String, Number>();
        metrics.forEach((name, value) -> {
            if (isCounter.test(name)) {
                normalized.put(name, Math.max(0L,
                        value.longValue() - nativeCounterBaseline.getOrDefault(name, 0L)));
            } else {
                normalized.put(name, value);
            }
        });
        return normalized;
    }

    protected ProviderMetrics commonMetrics(long size, long evictions, long expirations,
                                             java.util.Map<String, Number> nativeMetrics) {
        long requestCount = requests.sum();
        long hitCount = hits.sum();
        return new ProviderMetrics(name(), size, requestCount, hitCount, misses.sum(),
                requestCount == 0 ? 0.0 : (double) hitCount / requestCount,
                loadSuccess.sum(), loadFailure.sum(), totalLoadNanos.sum(),
                evictions, expirations, puts.sum(), removes.sum(), nativeMetrics);
    }
}

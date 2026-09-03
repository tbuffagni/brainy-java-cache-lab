package it.tekne.benchmark.cache;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.apache.commons.jcs3.JCS;
import org.apache.commons.jcs3.access.CacheAccess;
import org.apache.commons.jcs3.engine.CompositeCacheAttributes;
import org.apache.commons.jcs3.engine.ElementAttributes;
import org.apache.commons.jcs3.engine.stats.behavior.ICacheStats;
import org.apache.commons.jcs3.engine.stats.behavior.IStats;

/** Adapter for the unmodified Apache Commons JCS 3.2.1 release control. */
final class Jcs321Provider extends AbstractProvider {
    private static final String CONFIG = "/jcs321-cache.ccf";
    private static final String MEMORY_IMPLEMENTATION =
            "org.apache.commons.jcs3.engine.memory.lru.LRUMemoryCache";
    private final CacheAccess<BenchmarkKey, String> cache;

    Jcs321Provider(int capacity, Duration ttl) {
        requireImplementation();
        JCS.setConfigFilename(CONFIG);
        CompositeCacheAttributes attributes = new CompositeCacheAttributes();
        attributes.setMaxObjects(capacity);
        attributes.setMemoryCacheName(MEMORY_IMPLEMENTATION);
        ElementAttributes element = new ElementAttributes();
        element.setIsEternal(false);
        element.setMaxLife(Math.max(1L, ttl.toSeconds()));
        try {
            cache = JCS.getInstance("benchmark-" + System.nanoTime(), attributes, element);
        } catch (Exception failure) {
            throw new IllegalStateException("Cannot initialize JCS 3.2.1", failure);
        }
    }

    private static void requireImplementation() {
        try {
            Class.forName(MEMORY_IMPLEMENTATION, false, Jcs321Provider.class.getClassLoader());
        } catch (ClassNotFoundException failure) {
            throw new IllegalStateException("JCS 3.2.1 strict LRU implementation is unavailable: "
                    + MEMORY_IMPLEMENTATION, failure);
        }
    }

    public String name() { return "jcs321"; }
    protected String nativeGet(BenchmarkKey key) { return cache.get(key); }
    protected void nativePut(BenchmarkKey key, String value) { cache.put(key, value); }
    public void clear() { cache.clear(); }

    private Map<String, Number> nativeMetrics() {
        ICacheStats stats = cache.getStatistics();
        var nativeMetrics = new LinkedHashMap<String, Number>();
        collectMetrics(stats, "Composite", nativeMetrics);
        stats.getAuxiliaryCacheStats().forEach(auxiliary ->
                collectMetrics(auxiliary, auxiliary.getTypeName(), nativeMetrics));
        return nativeMetrics;
    }

    @Override
    public void resetMetrics() {
        super.resetMetrics();
        snapshotNativeCounters(nativeMetrics(), Jcs321Provider::isCounter);
    }

    public ProviderMetrics metrics() {
        var nativeMetrics = nativeMetricsSinceReset(nativeMetrics(), Jcs321Provider::isCounter);
        return commonMetrics(cache.getCacheControl().getSize(), number(nativeMetrics, "Eviction Count"),
                number(nativeMetrics, "Expired Count"), nativeMetrics);
    }

    private static boolean isCounter(String name) {
        return name.toLowerCase(Locale.ROOT).contains("count");
    }

    private void collectMetrics(IStats stats, String source, Map<String, Number> metrics) {
        stats.getStatElements().forEach(element -> {
            if (element.getData() instanceof Number number) {
                metrics.putIfAbsent(element.getName(), number);
                metrics.put(source + "." + element.getName(), number);
            }
        });
    }

    private long number(Map<String, Number> metrics, String name) {
        Number value = metrics.get(name);
        return value == null ? -1 : value.longValue();
    }

    public void close() {
        try {
            cache.dispose();
        } catch (Exception failure) {
            throw new IllegalStateException("Cannot dispose JCS 3.2.1 cache", failure);
        } finally {
            JCS.shutdown();
        }
    }
}

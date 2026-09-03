package it.tekne.benchmark.cache;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.apache.commons.jcs4.JCS;
import org.apache.commons.jcs4.access.CacheAccess;
import org.apache.commons.jcs4.engine.CompositeCacheAttributes;
import org.apache.commons.jcs4.engine.ElementAttributes;
import org.apache.commons.jcs4.engine.stats.behavior.ICacheStats;
import org.apache.commons.jcs4.engine.stats.behavior.IStats;

final class Jcs4Provider extends AbstractProvider {
    private static final String CONFIG = "/jcs4-cache.ccf";
    private final CacheAccess<BenchmarkKey, String> cache;

    Jcs4Provider(int capacity, Duration ttl, JcsMemoryMode memoryMode) {
        requireImplementation(memoryMode);
        JCS.setConfigFilename(CONFIG);
        String regionName = "benchmark-" + System.nanoTime();
        CompositeCacheAttributes defaults = CompositeCacheAttributes.defaults();
        CompositeCacheAttributes attributes = new CompositeCacheAttributes(
                regionName,
                capacity,
                defaults.UseMemoryShrinker(),
                defaults.ShrinkerInterval(),
                defaults.MaxSpoolPerRun(),
                defaults.MaxMemoryIdleTime(),
                memoryMode.implementationClass(),
                defaults.DiskUsagePattern(),
                defaults.SpoolChunkSize());
        ElementAttributes element = new ElementAttributes(
                true,
                true,
                true,
                false,
                ttl.isZero() || ttl.isNegative() ? Duration.ofSeconds(1) : ttl,
                Duration.ofMillis(-1));
        try {
            cache = JCS.getInstance(regionName, attributes, element);
        } catch (Exception failure) {
            throw new IllegalStateException("Cannot initialize JCS 4", failure);
        }
    }

    private static void requireImplementation(JcsMemoryMode mode) {
        try {
            Class.forName(mode.implementationClass(), false, Jcs4Provider.class.getClassLoader());
        } catch (ClassNotFoundException failure) {
            throw new IllegalStateException("JCS memory mode '" + mode.externalName()
                    + "' is unavailable; missing " + mode.implementationClass()
                    + ". Build the pinned vendor/commons-jcs4-main artifact first.", failure);
        }
    }

    public String name() { return "jcs4"; }
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
        snapshotNativeCounters(nativeMetrics(), Jcs4Provider::isCounter);
    }

    public ProviderMetrics metrics() {
        var nativeMetrics = nativeMetricsSinceReset(nativeMetrics(), Jcs4Provider::isCounter);
        return commonMetrics(cache.getCacheControl().getSize(), number(nativeMetrics, "Eviction Count"),
                number(nativeMetrics, "Expired Count"), nativeMetrics);
    }

    private static boolean isCounter(String name) {
        return name.toLowerCase(Locale.ROOT).contains("count");
    }

    private void collectMetrics(IStats stats, String source, Map<String, Number> metrics) {
        stats.getStatElements().forEach(element -> {
            if (element.data() instanceof Number number) {
                metrics.putIfAbsent(element.name(), number);
                metrics.put(source + "." + element.name(), number);
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
            throw new IllegalStateException("Cannot dispose JCS 4 cache", failure);
        } finally {
            JCS.shutdown();
        }
    }
}

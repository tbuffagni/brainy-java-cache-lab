package it.tekne.benchmark.cache;

import java.util.Map;

/** Lifecycle control that exercises the adapter and workload without retaining entries. */
final class NoStoreProvider extends AbstractProvider {
    public String name() { return "nostore"; }
    protected String nativeGet(BenchmarkKey key) { return null; }
    protected void nativePut(BenchmarkKey key, String value) { }
    public void clear() { }

    public ProviderMetrics metrics() {
        return commonMetrics(0L, 0L, 0L, Map.of("storageEnabled", 0));
    }

    public void close() { resetMetrics(); }
}

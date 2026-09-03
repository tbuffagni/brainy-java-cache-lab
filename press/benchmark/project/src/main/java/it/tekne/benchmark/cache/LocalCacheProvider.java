package it.tekne.benchmark.cache;

import java.util.function.Function;

public interface LocalCacheProvider extends AutoCloseable {
    String name();
    String get(BenchmarkKey key);
    void put(BenchmarkKey key, String value);
    String getDirect(BenchmarkKey key);
    void putDirect(BenchmarkKey key, String value);
    String getOrLoad(BenchmarkKey key, Function<BenchmarkKey, String> loader);
    void clear();
    void resetMetrics();
    ProviderMetrics metrics();
    @Override void close();
}

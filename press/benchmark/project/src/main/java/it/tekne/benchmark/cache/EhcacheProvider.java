package it.tekne.benchmark.cache;

import java.time.Duration;
import java.util.LinkedHashMap;
import org.ehcache.Cache;
import org.ehcache.CacheManager;
import org.ehcache.config.builders.CacheConfigurationBuilder;
import org.ehcache.config.builders.CacheManagerBuilder;
import org.ehcache.config.builders.ExpiryPolicyBuilder;
import org.ehcache.config.builders.ResourcePoolsBuilder;

final class EhcacheProvider extends AbstractProvider {
    private final CacheManager manager;
    private final Cache<BenchmarkKey, String> cache;

    EhcacheProvider(long capacity, Duration ttl) {
        manager = CacheManagerBuilder.newCacheManagerBuilder()
                .withCache("benchmark", CacheConfigurationBuilder
                        .newCacheConfigurationBuilder(BenchmarkKey.class, String.class,
                                ResourcePoolsBuilder.heap(capacity))
                        .withExpiry(ExpiryPolicyBuilder.timeToLiveExpiration(ttl)))
                .build(true);
        cache = manager.getCache("benchmark", BenchmarkKey.class, String.class);
    }

    public String name() { return "ehcache"; }
    protected String nativeGet(BenchmarkKey key) { return cache.get(key); }
    protected void nativePut(BenchmarkKey key, String value) { cache.put(key, value); }
    public void clear() { cache.clear(); }

    public ProviderMetrics metrics() {
        long size = 0;
        for (Cache.Entry<BenchmarkKey, String> ignored : cache) size++;
        var nativeMetrics = new LinkedHashMap<String, Number>();
        nativeMetrics.put("mappings", size);
        return commonMetrics(size, -1, -1, nativeMetrics);
    }

    public void close() { manager.close(); }
}

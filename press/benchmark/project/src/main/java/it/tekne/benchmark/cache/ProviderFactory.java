package it.tekne.benchmark.cache;

import java.time.Duration;
import java.util.Set;

public final class ProviderFactory {
    public static final Set<String> SUPPORTED = Set.of(
            "caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore");
    private ProviderFactory() { }

    public static LocalCacheProvider create(String name, int capacity, Duration ttl) {
        return create(name, capacity, ttl, JcsMemoryMode.STRICT);
    }

    public static LocalCacheProvider create(String name, int capacity, Duration ttl, JcsMemoryMode jcsMode) {
        return switch (name) {
            case "caffeine" -> new CaffeineProvider(capacity, ttl);
            case "ehcache" -> new EhcacheProvider(capacity, ttl);
            case "cache2k" -> new Cache2kProvider(capacity, ttl);
            case "jcs4" -> new Jcs4Provider(capacity, ttl, jcsMode);
            case "jcs321" -> new Jcs321Provider(capacity, ttl);
            case "nostore" -> new NoStoreProvider();
            default -> throw new IllegalArgumentException("Unsupported provider: " + name);
        };
    }
}

package it.tekne.benchmark.cache;

import java.util.Locale;

public enum JcsMemoryMode {
    STRICT("strict", "org.apache.commons.jcs4.engine.memory.lru.LRUMemoryCache");

    private final String externalName;
    private final String implementationClass;

    JcsMemoryMode(String externalName, String implementationClass) {
        this.externalName = externalName;
        this.implementationClass = implementationClass;
    }

    public String externalName() {
        return externalName;
    }

    public String implementationClass() {
        return implementationClass;
    }

    public static JcsMemoryMode parse(String value) {
        if (value == null || value.isBlank()) return STRICT;
        String normalized = value.trim().toLowerCase(Locale.ROOT).replace('_', '-');
        for (JcsMemoryMode mode : values()) {
            if (mode.externalName.equals(normalized)) return mode;
        }
        throw new IllegalArgumentException(
                "jcsMemoryMode must be strict for the JCS 4 article-one benchmark: " + value);
    }
}

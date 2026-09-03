package it.tekne.benchmark.workload;

import java.util.Locale;

public enum WorkloadType {
    UNIFORM,
    ZIPF,
    SCAN,
    MIXED,
    EXPIRY;

    public static WorkloadType parse(String value) {
        if (value == null || value.isBlank()) return UNIFORM;
        try {
            return valueOf(value.trim().toUpperCase(Locale.ROOT).replace('-', '_'));
        } catch (IllegalArgumentException failure) {
            throw new IllegalArgumentException(
                    "workload must be uniform, zipf, scan, mixed or expiry: " + value, failure);
        }
    }

    public String externalName() {
        return name().toLowerCase(Locale.ROOT).replace('_', '-');
    }
}

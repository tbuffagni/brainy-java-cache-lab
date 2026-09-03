package it.tekne.benchmark.cache;

import java.io.Serial;
import java.io.Serializable;

public record BenchmarkKey(
        String environment,
        String central,
        String username,
        String sessionId,
        long applicationId,
        long entryPointId) implements Serializable {
    @Serial
    private static final long serialVersionUID = 1L;

    public static BenchmarkKey of(long id) {
        return new BenchmarkKey(
                "TCDT", "CDT", "user-" + id, "rg1.v1.session-" + id,
                100L + (id % 31), id);
    }
}

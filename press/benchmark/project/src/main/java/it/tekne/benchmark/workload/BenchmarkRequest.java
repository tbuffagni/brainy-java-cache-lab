package it.tekne.benchmark.workload;

public record BenchmarkRequest(
        int entries,
        int operations,
        int threads,
        int hitPercent,
        int payloadBytes,
        int warmupOperations,
        double warmupSeconds,
        long ttlSeconds,
        String workload,
        int writePercent,
        String jcsMemoryMode,
        long seed,
        int latencySampleRate,
        double measurementSeconds) {

    public BenchmarkRequest {
        if (entries < 100 || entries > 100_000) throw new IllegalArgumentException("entries must be 100..100000");
        if (operations < 1_000 || operations > 10_000_000) throw new IllegalArgumentException("operations must be 1000..10000000");
        if (threads < 1 || threads > 128) throw new IllegalArgumentException("threads must be 1..128");
        if (hitPercent < 0 || hitPercent > 100) throw new IllegalArgumentException("hitPercent must be 0..100");
        if (payloadBytes < 16 || payloadBytes > 65_536) throw new IllegalArgumentException("payloadBytes must be 16..65536");
        if (warmupOperations < 0 || warmupOperations > 2_000_000) throw new IllegalArgumentException("warmupOperations must be 0..2000000");
        if (!Double.isFinite(warmupSeconds) || warmupSeconds < 0.0 || warmupSeconds > 60.0) {
            throw new IllegalArgumentException("warmupSeconds must be 0..60");
        }
        if (ttlSeconds < 1 || ttlSeconds > 3600) throw new IllegalArgumentException("ttlSeconds must be 1..3600");
        if (writePercent < 0 || writePercent > 100) throw new IllegalArgumentException("writePercent must be 0..100");
        if (latencySampleRate == 0) latencySampleRate = 16;
        if (latencySampleRate < 1 || latencySampleRate > 65_536) {
            throw new IllegalArgumentException("latencySampleRate must be 1..65536");
        }
        if (!Double.isFinite(measurementSeconds) || measurementSeconds < 0.0
                || measurementSeconds > 60.0) {
            throw new IllegalArgumentException("measurementSeconds must be 0..60");
        }
        workload = WorkloadType.parse(workload).externalName();
        jcsMemoryMode = it.tekne.benchmark.cache.JcsMemoryMode.parse(jcsMemoryMode).externalName();
        if (WorkloadType.EXPIRY.externalName().equals(workload) && ttlSeconds > 10) {
            throw new IllegalArgumentException("expiry workload requires ttlSeconds <= 10");
        }
    }

    public static BenchmarkRequest standard() {
        return new BenchmarkRequest(10_000, 400_000, 8, 95, 512, 50_000, 2.0, 300,
                "uniform", 10, "strict", 0x5EEDL, 64, 5.0);
    }

    /** Compatibility constructor for stored v3 requests and unit tests. */
    public BenchmarkRequest(int entries, int operations, int threads, int hitPercent,
            int payloadBytes, int warmupOperations, long ttlSeconds, String workload,
            int writePercent, String jcsMemoryMode, long seed, int latencySampleRate) {
        this(entries, operations, threads, hitPercent, payloadBytes, warmupOperations,
                0.0, ttlSeconds, workload, writePercent, jcsMemoryMode, seed,
                latencySampleRate, 0.0);
    }

    /** Compatibility constructor for callers that set a measurement window but no warm-up window. */
    public BenchmarkRequest(int entries, int operations, int threads, int hitPercent,
            int payloadBytes, int warmupOperations, long ttlSeconds, String workload,
            int writePercent, String jcsMemoryMode, long seed, int latencySampleRate,
            double measurementSeconds) {
        this(entries, operations, threads, hitPercent, payloadBytes, warmupOperations,
                0.0, ttlSeconds, workload, writePercent, jcsMemoryMode, seed,
                latencySampleRate, measurementSeconds);
    }

    public WorkloadType workloadType() { return WorkloadType.parse(workload); }

    public it.tekne.benchmark.cache.JcsMemoryMode jcsMode() {
        return it.tekne.benchmark.cache.JcsMemoryMode.parse(jcsMemoryMode);
    }
}

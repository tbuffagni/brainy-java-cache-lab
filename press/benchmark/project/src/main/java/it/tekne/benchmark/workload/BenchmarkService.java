package it.tekne.benchmark.workload;

import it.tekne.benchmark.cache.BenchmarkKey;
import it.tekne.benchmark.cache.LocalCacheProvider;
import it.tekne.benchmark.cache.ProviderFactory;
import jakarta.annotation.PreDestroy;
import jakarta.servlet.ServletContext;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.SplittableRandom;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Service;

@Service
public class BenchmarkService {
    private static final int CLOCK_CHECK_INTERVAL = 256;
    private static final AtomicLong WORKER_SEQUENCE = new AtomicLong();

    private final String providerName;
    private LocalCacheProvider provider;

    public BenchmarkService(ServletContext context) {
        String path = context.getContextPath();
        providerName = path == null || path.length() < 2 ? "caffeine" : path.substring(1).toLowerCase();
        if (!ProviderFactory.SUPPORTED.contains(providerName)) {
            throw new IllegalStateException("Deploy the WAR as one of " + ProviderFactory.SUPPORTED);
        }
    }

    public String providerName() { return providerName; }

    public synchronized BenchmarkResult run(BenchmarkRequest request) throws Exception {
        closeProvider();
        provider = ProviderFactory.create(providerName, request.entries(),
                Duration.ofSeconds(request.ttlSeconds()), request.jcsMode());

        PreparedData data = prepareData(request);
        AccessPlan plan = preparePlan(request);

        WorkloadExecution warmup = WorkloadExecution.empty();
        if (request.warmupOperations() > 0 || request.warmupSeconds() > 0.0) {
            preload(request, data);
            warmup = concurrentWorkload(request, data, plan, request.warmupOperations(),
                    request.warmupSeconds(), false);
        }

        // The measured phase uses the same provider instance, but starts from an empty cache
        // and counters whose baseline excludes both warm-up and its cleanup.
        provider.clear();
        provider.resetMetrics();

        long fillStart = System.nanoTime();
        preload(request, data);
        long fillNanos = System.nanoTime() - fillStart;

        if (request.workloadType() == WorkloadType.EXPIRY) awaitExpiry(request.ttlSeconds());
        WorkloadExecution execution = concurrentWorkload(request, data, plan,
                request.operations(), request.measurementSeconds(), true);
        Arrays.sort(execution.latencies());
        var providerMetricsAfterWorkload = provider.metrics();

        int writes = Math.max(1, request.entries() / 2);
        long writeStart = System.nanoTime();
        for (int i = 0; i < writes; i++) {
            provider.put(data.missKeys()[i], data.values()[i]);
        }
        long writeNanos = System.nanoTime() - writeStart;

        var providerMetricsAfterWriteProbe = provider.metrics();
        long loaderInvocations = singleFlightProbe(request.payloadBytes());
        return new BenchmarkResult(providerName, request,
                warmup.operations(), warmup.elapsedNanos(),
                overshoot(warmup.elapsedNanos(), request.warmupSeconds()), plan.sha256(),
                rate(request.entries(), fillNanos),
                rate(execution.operations(), execution.elapsedNanos()),
                execution.operations(), execution.elapsedNanos(),
                overshoot(execution.elapsedNanos(), request.measurementSeconds()),
                rate(execution.readOperations(), execution.elapsedNanos()), execution.readOperations(),
                execution.writeOperations(), rate(writes, writeNanos),
                percentile(execution.latencies(), 0.50), percentile(execution.latencies(), 0.95),
                percentile(execution.latencies(), 0.99), execution.latencies().length,
                loaderInvocations, loaderInvocations == 1,
                providerMetricsAfterWorkload, providerMetricsAfterWriteProbe,
                providerMetricsAfterWriteProbe);
    }

    private void preload(BenchmarkRequest request, PreparedData data) {
        for (int i = 0; i < request.entries(); i++) {
            provider.put(data.hitKeys()[i], data.values()[i]);
        }
    }

    private WorkloadExecution concurrentWorkload(BenchmarkRequest request, PreparedData data,
            AccessPlan plan, long minimumOperations, double minimumSeconds,
            boolean collectLatencies) throws Exception {
        var ready = new CountDownLatch(request.threads());
        var start = new CountDownLatch(1);
        var executor = newWorkerPool(request.threads(), "workload");
        try {
            long durationNanos = secondsToNanos(minimumSeconds);
            var startNanos = new AtomicLong();
            var futures = new java.util.ArrayList<java.util.concurrent.Future<WorkerExecution>>();
            int planBase = plan.keySlots().length / request.threads();
            int planRemainder = plan.keySlots().length % request.threads();
            long operationBase = minimumOperations / request.threads();
            long operationRemainder = minimumOperations % request.threads();
            int planOffset = 0;
            for (int thread = 0; thread < request.threads(); thread++) {
                int planCount = planBase + (thread < planRemainder ? 1 : 0);
                int from = planOffset;
                planOffset += planCount;
                long workerMinimum = operationBase + (thread < operationRemainder ? 1 : 0);
                futures.add(executor.submit(() -> {
                    ready.countDown();
                    await(start);
                    long deadline = startNanos.get() + durationNanos;
                    long operations = 0;
                    long reads = 0;
                    long writes = 0;
                    LongSamples samples = new LongSamples(collectLatencies
                            ? Math.max(16, samplesFor(planCount, request.latencySampleRate())) : 16);
                    while (true) {
                        if (operations >= workerMinimum) {
                            if (durationNanos == 0L) break;
                            if ((operations & (CLOCK_CHECK_INTERVAL - 1L)) == 0L
                                    && System.nanoTime() >= deadline) break;
                        }
                        int operation = from + (int) (operations % planCount);
                        int slot = plan.keySlots()[operation];
                        boolean sample = collectLatencies
                                && operations % request.latencySampleRate() == 0;
                        long before = sample ? System.nanoTime() : 0L;
                        if (plan.writes()[operation]) {
                            int writeSlot = slot >= 0 ? slot : ~slot;
                            provider.put(data.hitKeys()[writeSlot], data.values()[writeSlot]);
                            writes++;
                        } else {
                            BenchmarkKey key = slot >= 0 ? data.hitKeys()[slot] : data.missKeys()[~slot];
                            provider.get(key);
                            reads++;
                        }
                        if (sample) samples.add(System.nanoTime() - before);
                        operations++;
                    }
                    return new WorkerExecution(operations, reads, writes, samples.toArray());
                }));
            }
            if (!ready.await(30, TimeUnit.SECONDS)) throw new IllegalStateException("workers not ready");
            long before = System.nanoTime();
            startNanos.set(before);
            start.countDown();
            long operations = 0;
            long readOperations = 0;
            long writeOperations = 0;
            var workers = new java.util.ArrayList<WorkerExecution>();
            for (var future : futures) {
                WorkerExecution worker = future.get(2, TimeUnit.MINUTES);
                workers.add(worker);
                operations += worker.operations();
                readOperations += worker.readOperations();
                writeOperations += worker.writeOperations();
            }
            long elapsedNanos = System.nanoTime() - before;
            int sampleTotal = workers.stream().mapToInt(worker -> worker.latencies().length).sum();
            long[] latencies = new long[sampleTotal];
            int sampleOffset = 0;
            for (WorkerExecution worker : workers) {
                System.arraycopy(worker.latencies(), 0, latencies, sampleOffset,
                        worker.latencies().length);
                sampleOffset += worker.latencies().length;
            }
            return new WorkloadExecution(elapsedNanos, operations, readOperations,
                    writeOperations, latencies);
        } finally {
            shutdownExecutor(executor);
        }
    }

    private static PreparedData prepareData(BenchmarkRequest request) {
        BenchmarkKey[] hitKeys = new BenchmarkKey[request.entries()];
        BenchmarkKey[] missKeys = new BenchmarkKey[request.entries()];
        String[] values = new String[request.entries()];
        for (int i = 0; i < request.entries(); i++) {
            hitKeys[i] = BenchmarkKey.of(i);
            missKeys[i] = BenchmarkKey.of(request.entries() + 1_000_000L + i);
            values[i] = value(i, request.payloadBytes());
        }
        return new PreparedData(hitKeys, missKeys, values);
    }

    private static AccessPlan preparePlan(BenchmarkRequest request) {
        int[] slots = new int[request.operations()];
        boolean[] writes = new boolean[request.operations()];
        SplittableRandom random = new SplittableRandom(request.seed());
        double[] zipfCdf = request.workloadType() == WorkloadType.ZIPF
                ? zipfCdf(request.entries(), 1.10) : null;
        for (int i = 0; i < slots.length; i++) {
            boolean hit = random.nextInt(100) < request.hitPercent();
            int slot = switch (request.workloadType()) {
                case SCAN -> i % request.entries();
                case ZIPF -> sampleZipf(zipfCdf, random.nextDouble());
                default -> random.nextInt(request.entries());
            };
            slots[i] = hit ? slot : ~slot;
            writes[i] = request.workloadType() == WorkloadType.MIXED
                    && random.nextInt(100) < request.writePercent();
        }
        return new AccessPlan(slots, writes, checksum(slots, writes));
    }

    private static String checksum(int[] slots, boolean[] writes) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            updateInt(digest, slots.length);
            for (int i = 0; i < slots.length; i++) {
                updateInt(digest, slots[i]);
                digest.update((byte) (writes[i] ? 1 : 0));
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    private static void updateInt(MessageDigest digest, int value) {
        digest.update((byte) (value >>> 24));
        digest.update((byte) (value >>> 16));
        digest.update((byte) (value >>> 8));
        digest.update((byte) value);
    }

    private static double[] zipfCdf(int entries, double exponent) {
        double[] cdf = new double[entries];
        double total = 0;
        for (int rank = 1; rank <= entries; rank++) total += 1.0 / Math.pow(rank, exponent);
        double cumulative = 0;
        for (int rank = 1; rank <= entries; rank++) {
            cumulative += (1.0 / Math.pow(rank, exponent)) / total;
            cdf[rank - 1] = cumulative;
        }
        cdf[entries - 1] = 1.0;
        return cdf;
    }

    private static int sampleZipf(double[] cdf, double value) {
        int index = Arrays.binarySearch(cdf, value);
        return index >= 0 ? index : -index - 1;
    }

    private static int samplesFor(int operations, int rate) {
        return (operations + rate - 1) / rate;
    }

    private static void awaitExpiry(long ttlSeconds) {
        try {
            Thread.sleep(TimeUnit.SECONDS.toMillis(ttlSeconds) + 50);
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted while waiting for expiry", failure);
        }
    }

    private long singleFlightProbe(int payloadBytes) throws Exception {
        BenchmarkKey key = BenchmarkKey.of(Long.MAX_VALUE - 1);
        AtomicLong loads = new AtomicLong();
        CountDownLatch ready = new CountDownLatch(16);
        CountDownLatch start = new CountDownLatch(1);
        var executor = newWorkerPool(16, "single-flight");
        try {
            var futures = new java.util.ArrayList<java.util.concurrent.Future<String>>();
            for (int i = 0; i < 16; i++) {
                futures.add(executor.submit(() -> {
                    ready.countDown();
                    await(start);
                    return provider.getOrLoad(key, ignored -> {
                        loads.incrementAndGet();
                        try { Thread.sleep(25); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                        return value(Long.MAX_VALUE, payloadBytes);
                    });
                }));
            }
            ready.await(10, TimeUnit.SECONDS);
            start.countDown();
            for (var future : futures) future.get(30, TimeUnit.SECONDS);
        } finally {
            shutdownExecutor(executor);
        }
        return loads.get();
    }

    private static void shutdownExecutor(java.util.concurrent.ExecutorService executor) {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    throw new IllegalStateException("benchmark worker pool did not terminate");
                }
            }
        } catch (InterruptedException failure) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
            throw new IllegalStateException("interrupted while terminating benchmark workers", failure);
        }
    }

    private static java.util.concurrent.ExecutorService newWorkerPool(int size, String role) {
        return Executors.newFixedThreadPool(size, task -> new Thread(
                task,
                "cache-benchmark-" + role + "-" + WORKER_SEQUENCE.incrementAndGet()));
    }

    private static void await(CountDownLatch latch) {
        try { latch.await(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IllegalStateException(e); }
    }

    static String value(long id, int bytes) {
        String prefix = "https://portal.example.test/route/" + id + "?v=";
        String seed = prefix + Integer.toHexString(Long.hashCode(id));
        if (seed.length() >= bytes) return seed.substring(0, bytes);
        return seed + "x".repeat(bytes - seed.length());
    }

    private static long secondsToNanos(double seconds) {
        return Math.round(seconds * 1_000_000_000.0);
    }

    private static long overshoot(long elapsedNanos, double minimumSeconds) {
        long minimumNanos = secondsToNanos(minimumSeconds);
        return minimumNanos == 0L ? 0L : Math.max(0L, elapsedNanos - minimumNanos);
    }

    private static double rate(long count, long nanos) {
        return count * 1_000_000_000.0 / Math.max(1, nanos);
    }

    private static long percentile(long[] values, double p) {
        if (values.length == 0) return 0L;
        return values[Math.min(values.length - 1, (int) Math.ceil(values.length * p) - 1)];
    }

    private record PreparedData(BenchmarkKey[] hitKeys, BenchmarkKey[] missKeys, String[] values) { }
    private record AccessPlan(int[] keySlots, boolean[] writes, String sha256) { }
    private record WorkerExecution(long operations, long readOperations, long writeOperations,
                                   long[] latencies) { }
    private record WorkloadExecution(long elapsedNanos, long operations, long readOperations,
                                     long writeOperations, long[] latencies) {
        private static WorkloadExecution empty() {
            return new WorkloadExecution(0L, 0L, 0L, 0L, new long[0]);
        }
    }

    private static final class LongSamples {
        private long[] values;
        private int size;

        private LongSamples(int initialCapacity) {
            values = new long[initialCapacity];
        }

        private void add(long value) {
            if (size == values.length) values = Arrays.copyOf(values, values.length * 2);
            values[size++] = value;
        }

        private long[] toArray() {
            return Arrays.copyOf(values, size);
        }
    }

    @PreDestroy
    public synchronized void shutdown() { closeProvider(); }

    private void closeProvider() {
        if (provider != null) {
            provider.close();
            provider = null;
        }
    }
}

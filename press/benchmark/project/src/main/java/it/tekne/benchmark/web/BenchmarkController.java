package it.tekne.benchmark.web;

import it.tekne.benchmark.workload.BenchmarkRequest;
import it.tekne.benchmark.workload.BenchmarkResult;
import it.tekne.benchmark.workload.BenchmarkService;
import java.time.Instant;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class BenchmarkController {
    private final BenchmarkService service;

    public BenchmarkController(BenchmarkService service) {
        this.service = service;
    }

    @GetMapping("/info")
    public Map<String, Object> info() {
        return Map.of("provider", service.providerName(), "ready", true,
                "java", System.getProperty("java.version"), "timestamp", Instant.now().toString());
    }

    @PostMapping("/run")
    public BenchmarkResult run(@RequestBody(required = false) BenchmarkRequest request) throws Exception {
        return service.run(request == null ? BenchmarkRequest.standard() : request);
    }
}

# Brainy Java Cache Lab

Reproducible experiments on Java cache performance, correctness, and web-application lifecycle in Apache Tomcat.

The first study, **Beyond Throughput: A Reproducible Benchmark of Java Caches in a Tomcat Lifecycle**, compares Caffeine, Ehcache, cache2k, Apache Commons JCS 4, Apache Commons JCS 3.2.1, and a no-store control under the same application workload. Throughput, latency, semantic correctness, and behavior across undeploy/redeploy are reported as separate outcomes.

## Read the paper

- [English paper (PDF)](press/article/beyond-throughput-tomcat-lifecycle-en.pdf)
- [Italian paper (PDF)](press/article/beyond-throughput-tomcat-lifecycle.pdf)
- [English source](press/article/beyond-throughput-tomcat-lifecycle-v4-2-en.md)
- [Italian source](press/article/beyond-throughput-tomcat-lifecycle-v4-2.md)
- [Experimental protocol](press/article/protocollo-campagna-v4-2.md)

## Main results

The canonical campaign completed 36 independent JVM processes, 180 Tomcat lifecycle cycles, and 360 timed windows. All timed windows passed the semantic gate.

| Cache | Initial deploy | Redeploy |
|---|---:|---:|
| cache2k | 30.777 Mops/s | 30.589 Mops/s |
| Caffeine | 27.218 Mops/s | 26.581 Mops/s |
| Ehcache | 24.813 Mops/s | 24.626 Mops/s |
| JCS 4 snapshot | 0.965 Mops/s | 0.969 Mops/s |

The JCS lifecycle test is treated separately from the performance comparison. The worker-thread retention observed with JCS 3.2.1 was reproduced in 6/6 JVM processes and was not reproduced in 0/6 processes running the pinned JCS 4 revision. This result is specific to the tested failure pattern and does not claim the absence of every possible form of resource retention.

## Reproduce the benchmark

Requirements: Docker Desktop configured for Linux containers, Docker Compose, Git, PowerShell, and Python 3.

Clone the repository together with the pinned Apache Commons JCS source revision:

```powershell
git clone --recurse-submodules https://github.com/tbuffagni/brainy-java-cache-lab.git
cd brainy-java-cache-lab
```

Run a short installation check:

```powershell
.\press\run-benchmark.ps1 `
  -Forks 1 `
  -Cycles 1 `
  -WarmupSeconds 0.2 `
  -MeasurementSeconds 0.5 `
  -EarlyDiagnosticSettleSeconds 0.2 `
  -FinalDiagnosticSettleSeconds 0.5 `
  -HeapDumpPolicy none `
  -CampaignLabel smoke-unified-v4-2
```

Run the complete frozen campaign:

```powershell
.\press\run-benchmark.ps1 `
  -Provider all `
  -Forks 6 `
  -Cycles 5 `
  -WarmupSeconds 3 `
  -MeasurementSeconds 5 `
  -LatencySampleRate 64 `
  -EarlyDiagnosticSettleSeconds 2 `
  -FinalDiagnosticSettleSeconds 10 `
  -HeapDumpPolicy jcs `
  -CampaignLabel article1-unified-v4-2 `
  -NoBuildCache
```

CPU allocation, container memory, JVM options, cache size, payload, workload, and related parameters can be changed explicitly. Every run records both requested settings and observed container settings. Modified runs are new experiments and must not be pooled with the canonical campaign.

Detailed instructions are in the [press kit](press/README.md) and [benchmark guide](press/benchmark/README.md). Published tables are available as [CSV and Excel files](press/results/README.md), with SHA-256 provenance manifests.

## Repository layout

- `press/article/`: papers, protocol, figures, and Libertinus fonts;
- `press/benchmark/`: Tomcat application, Docker build, and tests;
- `press/results/`: canonical tables and workbook;
- `scripts/`: runner, validators, extractors, and publication generators;
- `vendor/commons-jcs4-main/`: Git submodule pinned to the tested JCS 4 revision.

## Citation, licensing, and contact

Citation metadata is provided in [`CITATION.cff`](CITATION.cff). Software is licensed under Apache-2.0; the papers, protocol, original figures, documentation, and original data are licensed under CC BY 4.0. Third-party notices are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Thomas Buffagni — [LinkedIn](https://www.linkedin.com/in/thomasbuffagni/)

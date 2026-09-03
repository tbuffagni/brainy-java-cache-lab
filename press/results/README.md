# Published results

This directory contains the tabular results used by version 1.0.0 of *Beyond Throughput: A Reproducible Benchmark of Java Caches in a Tomcat Lifecycle*.

The publication dataset is identified by:

```text
article1-unified-v4-2-fb3f101b-20260903-000401
```

The campaign completed 36 independent JVM processes, 180 Tomcat lifecycle cycles, and 360 timed windows. The validator executed 18,934 checks with a `PASS` result, no errors, and no warnings. All reported values come from this campaign alone.

## Files

| File | Contents |
|---|---|
| `summary.csv` | aggregate performance results by provider and deployment phase |
| `forks.csv` | performance summaries for each independent JVM process |
| `lifecycle-summary.csv` | aggregate lifecycle results |
| `Beyond_Throughput_Lifecycle_v4_2_Results.xlsx` | publication workbook with tables and charts |
| `SHA256SUMS` | checksums for the published paper, protocol, figures, and result tables |

The complete evidence archive associated with the release contains the finalized raw JSON, derived analysis, individual observations, build log, diagnostic archive, and validation checkpoints. It is distributed separately because diagnostic material is substantially larger than the paper and summary tables.

## Inclusion rule

A campaign can feed the paper only when all of the following hold:

1. the results and analysis declare protocol `4.2` and schema `4`;
2. all 36 JVM processes, 180 cycles, and 360 timed windows are present;
3. the 6 × 6 Williams design and paired operation plans are complete;
4. requested and observed environment parameters agree;
5. the semantic gates can be reconstructed from elementary measurements;
6. cache population is recorded both after the workload and after the write probe;
7. lifecycle timings, diagnostics, JSON, CSV, and checksums are mutually consistent;
8. `scripts/validate_campaign_v4.py` returns `PASS`.

A semantic failure remains an observed result; it is never rewritten as an infrastructure failure. Throughput, latency, correctness, and lifecycle behavior remain separate outcomes and are not combined into a universal score.

## Integrity check

From the repository root:

```powershell
Get-Content .\press\results\SHA256SUMS | ForEach-Object {
  $expected, $path = $_ -split '\s+', 2
  $observed = (Get-FileHash -Algorithm SHA256 -LiteralPath $path.Trim()).Hash.ToLowerInvariant()
  if ($observed -ne $expected) {
    throw "Checksum mismatch: $path"
  }
}
```

## Validation and extraction

After extracting the complete evidence archive under `press/results/raw/`:

```powershell
$prefix = 'article1-unified-v4-2-fb3f101b-20260903-000401'

python .\scripts\validate_campaign_v4.py `
  ".\press\results\raw\$prefix-results.json"

python .\scripts\extract_paper_v4_2.py `
  --results ".\press\results\raw\$prefix-results.json" `
  --analysis ".\press\results\raw\$prefix-analysis.json" `
  --output ".\press\results\raw\$prefix-paper-values.json"
```

The validator checks cardinality, Williams order, provenance, semantic gates, effective timing, analysis consistency, CSV files, and the contents of the diagnostic archive.

## Scope

The dataset describes the configured application path, container environment, and workload. It is not a universal ranking of cache providers. The JCS lifecycle comparison verifies whether a specifically defined worker-thread retention pattern reappears; it does not demonstrate the absence of every possible memory or resource leak.

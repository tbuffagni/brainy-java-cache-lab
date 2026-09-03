# Benchmark Tomcat lifecycle — protocollo v4.2

Questa directory contiene il progetto riproducibile del primo articolo. Il punto di ingresso supportato è `press/run-benchmark.ps1`: costruisce e testa una sola immagine e un solo WAR, quindi esegue tutte le condizioni sullo stesso artefatto applicativo.

Il riferimento normativo è `press/article/protocollo-campagna-v4-2.md`, versione 4.2. I JSON finali devono riportare `protocolVersion: "4.2"` e `schemaVersion: 4`.

## Condizioni sperimentali

Il WAR include:

- Caffeine 3.2.4;
- Ehcache 3.12.0;
- cache2k 2.6.1.Final;
- `jcs4`: Apache Commons JCS 4 costruito dal checkout esatto in `vendor/commons-jcs4-main`;
- `jcs321`: il JAR ufficiale `org.apache.commons:commons-jcs3-core:3.2.1`;
- `nostore`: controllo di fondo che attraversa Tomcat e l'harness senza motore di cache né conservazione di elementi.

JCS 4 e JCS 3.2.1 hanno coordinate Maven e namespace Java distinti. Ogni processo esegue una sola condizione, evitando l'interazione fra i singleton delle due versioni. `jcs321` è il controllo positivo diagnostico per JCS-248; `nostore` misura il fondo del ciclo applicativo in assenza di un motore di cache. Nessuno dei due partecipa al confronto prestazionale primario.

Il wrapper rifiuta l'esecuzione di pubblicazione se il checkout JCS 4 non è pulito o non coincide con il commit congelato `fb3f101b87709b713468e8d827b8612e6e65f29b`. Il core JCS 3.2.1 viene verificato contro lo SHA-256:

```text
12c6fe08223820089f60969b6088e6ac5d358aa872de78357585cdacb6c61049
```

## Esecuzione del protocollo congelato

Dalla root del repository:

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

I default scientifici coincidono con il protocollo. `-NoBuildCache` forza la ricostruzione dei layer Docker; le dipendenze Maven già scaricate possono restare in cache, ma test e build `clean` vengono rieseguiti. `-SkipBuild` è rifiutato perché un'etichetta dell'immagine non dimostra che il WAR sia stato prodotto dai sorgenti correnti dell'harness.

`Operations=400000` è la dimensione minima del piano deterministico e il numero minimo di operazioni richiesto per finestra; il piano viene ripetuto finché sono trascorsi almeno 5 secondi. Il warm-up esegue almeno 50.000 operazioni e dura almeno 3 secondi. Il seme base `24301` e il sale `2482026` derivano un piano appaiato per blocco e ciclo, identico fra provider e fra deploy iniziale e redeploy.

I sei fork per condizione sono processi JVM/container ricreati e separati. Il disegno Williams 6 × 6 assegna ciascuna condizione una volta a ogni posizione. I processi non condividono stato JVM, ma sono eseguiti in sequenza sullo stesso host.

## Sequenza registrata

Ogni ciclo comprende due sequenze complete deploy–workload–undeploy:

```text
baseline del ciclo
  -> deploy e readiness
  -> snapshot idle
  -> warm-up, reset, fill e workload cronometrato
  -> checkpoint pre-write
  -> write probe diagnostica
  -> checkpoint post-write
  -> prova single-flight e snapshot loaded
  -> undeploy
  -> diagnostica precoce
  -> diagnostica finale
  -> redeploy e ripetizione dello stesso piano
  -> secondo undeploy e stessa diagnostica
```

### Doppio checkpoint di popolamento

La v4.2 rende esplicite due osservazioni distinte per ogni workload:

| Campo | Momento di acquisizione | Uso |
|---|---|---|
| `providerMetricsAfterWorkload` | dopo il workload, prima della write probe | gate di popolamento pre-write |
| `providerMetricsAfterWriteProbe` | dopo 5.000 `put` diagnostici | gate di popolamento post-write |
| `providerMetrics` | stesso valore del checkpoint post-write | alias legacy, non prova il checkpoint pre-write |

Per ciascun provider di cache entrambi i conteggi devono essere almeno 9.900; per `nostore` entrambi devono essere zero. Il valore post-write non può sostituire quello pre-write. La prova single-flight avviene dopo i due checkpoint e prima dello snapshot loaded.

La distinzione impedisce che una misura successiva alla prova di scrittura venga interpretata come stato della cache al termine del workload.

### Tempi post-undeploy effettivi

Le attese di 2 e 10 secondi sono soglie minime prima dell'avvio delle rispettive diagnostiche, non timestamp delle misure. Sia `firstUndeployTiming` sia `finalUndeployTiming` conservano nove campi:

| Campo | Significato |
|---|---|
| `earlyThreadSecondsAfterUndeploy` | target nominale legacy della diagnostica precoce |
| `finalMeasurementSecondsAfterUndeploy` | target nominale legacy della diagnostica finale |
| `earlyThreadTargetSecondsAfterUndeploy` | target minimo esplicito precoce |
| `finalDiagnosticTargetSecondsAfterUndeploy` | target minimo esplicito finale |
| `earlyThreadStartedSecondsAfterUndeploy` | avvio monotonic osservato della diagnostica precoce |
| `earlyThreadCompletedSecondsAfterUndeploy` | completamento monotonic osservato della diagnostica precoce |
| `finalDiagnosticStartedSecondsAfterUndeploy` | avvio monotonic osservato della sequenza finale |
| `findLeaksCompletedSecondsAfterUndeploy` | completamento osservato di `findleaks` |
| `finalSnapshotCompletedSecondsAfterUndeploy` | completamento osservato dell'ultimo snapshot |

La sequenza finale è: `findleaks`, due richieste `GC.run`, heap, class loader, thread dump, NMT e class histogram. È una diagnostica sequenziale e invasiva; i valori finali descrivono lo stato dopo quella sequenza, non un decorso passivo a un unico istante. Le singole operazioni interne allo snapshot finale non hanno timestamp indipendenti.

`-HeapDumpPolicy` accetta `none`, `jcs` e `all`. Il default `jcs` produce un dump al termine del quinto ciclo per ciascun processo JCS 4 e JCS 3.2.1. I dump possono occupare molti gigabyte.

## Provenienza della build

Le immagini base devono essere fissate per digest e ispezionabili nel Docker image store:

```text
tomcat:11.0.24-jdk25-temurin-noble@sha256:6d673ad42da6498f05755cae67f85f2128bdfd88943c9bdb22e0965f8d4c3182
maven:3.9.11-eclipse-temurin-25@sha256:407c4423cec0cf2981055bc2c6c0dc211d9605b6669279b95997f2d1c7e91e2c
```

Il Dockerfile esegue i test del reactor JCS 4 e dell'harness e archivia WAR, core JCS, checksum, effective POM, dependency tree, commit e versioni. Il JSON registra inoltre ID delle immagini, limite CPU e memoria effettivi, sistema operativo e kernel del container, JVM, Tomcat, opzioni JVM, parametri del workload, ordine Williams e manifest dei sorgenti.

## Output e checkpoint

Il prefisso ha la forma `<CampaignLabel>-fb3f101b-YYYYMMDD-HHMMSS`. Il wrapper conserva in `output/data/` e copia in `press/results/raw/`:

- `-results.json` e `-analysis.json`;
- cinque CSV: `-summary`, `-forks`, `-observations`, `-lifecycle-summary` e `-lifecycle-forks`;
- `-diagnostics.zip` e `-build.log`;
- `-raw.partial.json`, aggiornato dopo ogni processo.

Il checkpoint parziale è utile per l'audit di un'interruzione, ma non è sorgente canonica. Solo il file `-results.json` chiuso e accettato da `scripts/validate_campaign_v4.py` può entrare nella pubblicazione. Una failure infrastrutturale invalida l'intero blocco Williams; una violazione semantica resta nel raw e determina l'esclusione prevista dall'analisi, senza essere riclassificata come errore infrastrutturale.

## Parametri ambientali principali

| Variabile | Default v4.2 | Significato |
|---|---:|---|
| `CACHE_BENCH_PROVIDERS` | sei condizioni | insieme da eseguire |
| `CACHE_BENCH_FORKS` | `6` | processi JVM separati per condizione |
| `CACHE_BENCH_CYCLES` | `5` | cicli completi per processo |
| `CACHE_BENCH_WARMUP_OPERATIONS` | `50000` | operazioni minime di warm-up |
| `CACHE_BENCH_WARMUP_SECONDS` | `3` | durata minima del warm-up |
| `CACHE_BENCH_MEASUREMENT_SECONDS` | `5` | durata minima della finestra cronometrata |
| `CACHE_BENCH_LATENCY_SAMPLE_RATE` | `64` | un campione ogni N operazioni per worker |
| `CACHE_BENCH_EARLY_DIAGNOSTIC_SETTLE_SECONDS` | `2` | attesa minima prima della diagnostica precoce |
| `CACHE_BENCH_FINAL_DIAGNOSTIC_SETTLE_SECONDS` | `10` | attesa minima prima della diagnostica finale |
| `CACHE_BENCH_SCHEDULE_SEED` | `2482026` | sale per il piano appaiato |
| `CACHE_BENCH_HEAP_DUMP_POLICY` | `jcs` | selezione degli heap dump |

Il wrapper fissa esplicitamente anche le matrici a una sola configurazione, così variabili `CACHE_BENCH_*` ereditate non possono espandere silenziosamente una campagna. CPU, memoria, immagini, heap e workload restano modificabili tramite i parametri pubblici; ogni modifica deve avere una nuova etichetta ed essere analizzata separatamente.

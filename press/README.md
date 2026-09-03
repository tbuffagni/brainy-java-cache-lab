# Beyond Throughput — press kit e riproducibilità

Questa cartella è il punto di ingresso pubblico del primo studio:

> **Beyond Throughput: A Reproducible Benchmark of Java Caches in a Tomcat Lifecycle**

La versione normativa corrente è il [protocollo congelato v4.2](article/protocollo-campagna-v4-2.md), SHA-256 `4f364de62f696c687d3175931f29c69013f4ad9d96303558e2444bfc5c73596f`. I risultati destinati al paper devono dichiarare `protocolVersion: "4.2"` e `schemaVersion: 4`.

## Contenuto

- [articolo italiano compilato](article/beyond-throughput-tomcat-lifecycle-v4-2.md) — manoscritto con i valori estratti dal dataset accettato;
- [English paper](article/beyond-throughput-tomcat-lifecycle-v4-2-en.md) — complete English edition based on the same accepted dataset;
- [template verificabile](article/beyond-throughput-tomcat-lifecycle.md) — sorgente con placeholder, mantenuta per rigenerare il manoscritto;
- `article/figures/` — figure vettoriali del paper, generate dai dati della campagna canonica;
- `article/fonts/` — famiglia Libertinus 7.051 incorporata nel PDF e relativa licenza SIL OFL 1.1;
- [protocollo v4.2](article/protocollo-campagna-v4-2.md) — disegno, parametri, controlli e regole di analisi congelati prima della campagna;
- [benchmark](benchmark/README.md) — WAR, immagini Docker e istruzioni operative;
- `run-benchmark.ps1` — esecuzione plug-and-play da PowerShell;
- `results/raw/` — directory append-only creata dal wrapper per risultati, diagnostica e checkpoint delle nuove esecuzioni;
- [provenienza dei risultati](results/README.md) — regole di inclusione e catalogo degli artefatti;
- `results/Beyond_Throughput_Lifecycle_v4_2_Results.xlsx` — copia di pubblicazione del workbook v4.2, prodotta soltanto dopo la validazione definitiva.

## Campagna canonica

Il dataset incluso nel paper ha prefisso:

```text
article1-unified-v4-2-fb3f101b-20260903-000401
```

La campagna ha completato 36/36 JVM, 180/180 cicli e 360/360 finestre. Il validatore v4.2 ha eseguito 18.934 controlli con esito `PASS`, zero errori e zero warning.

## Release pubblica

La distribuzione `1.0.0` è costruita in due archivi: il press kit principale e l'archivio completo delle evidenze. Dopo avere generato il PDF, gli archivi si producono con:

```powershell
python .\scripts\build_press_release.py `
  --pdf .\output\pdf\beyond-throughput-tomcat-lifecycle-1.0.0.pdf `
  --pdf-en .\output\pdf\beyond-throughput-tomcat-lifecycle-en-1.0.0.pdf
```

I file `VERSION`, `RELEASE_NOTES.md`, `LICENSE` e `THIRD_PARTY_NOTICES.md` definiscono identità e condizioni della distribuzione. Il codice è distribuito con licenza Apache-2.0; paper, protocollo, documentazione, figure e dati originali con licenza CC BY 4.0. I materiali interni sono esclusi automaticamente.

Il protocollo distingue le metriche raccolte al termine del workload da quelle raccolte dopo la successiva prova di scrittura; entrambe entrano separatamente nel controllo semantico. In questo modo una misura successiva non viene usata per ricostruire retroattivamente lo stato precedente della cache.

## Esecuzione plug-and-play

Requisiti:

- Docker Desktop configurato per container Linux;
- Docker Compose, come `docker compose` o `docker-compose`;
- Git;
- Python 3, richiamabile tramite `py -3`, `python` oppure passato con `-PythonExecutable`.

Dalla root del repository, la campagna completa congelata si avvia con un solo comando:

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

Il wrapper verifica il checkout JCS 4 congelato, le immagini base fissate per digest e il checksum del core JCS 3.2.1; esegue build e test; costruisce un unico WAR; quindi orchestra il disegno Williams a sei condizioni. La campagna nominale comprende 36 processi JVM/container indipendenti, 180 cicli Tomcat e 360 finestre cronometrate. I processi sono separati, ma vengono eseguiti in sequenza sullo stesso host e non costituiscono repliche hardware indipendenti.

Se `python` è soltanto l'alias del Microsoft Store, specificare l'interprete reale:

```powershell
.\press\run-benchmark.ps1 -PythonExecutable 'C:\path\to\python.exe'
```

Per controllare rapidamente l'installazione, senza produrre dati pubblicabili:

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

Uno smoke test o un'esecuzione su un solo provider è diagnostica: non sostituisce la campagna Williams completa.

## Parametri modificabili

CPU, memoria, heap, immagini, capacità della cache e workload sono parametri espliciti. Per esempio:

```powershell
.\press\run-benchmark.ps1 `
  -DockerCpus 6 `
  -DockerMemory 3g `
  -JvmOptions '-Xms1g -Xmx2g -XX:+UseG1GC -XX:NativeMemoryTracking=summary' `
  -Entries 50000 `
  -Operations 2000000 `
  -Threads 16 `
  -Workload mixed `
  -WritePercent 20
```

Il JSON salva sia i valori richiesti sia quelli effettivi osservati nel container. Qualunque variazione genera una nuova campagna e non deve essere aggregata alla v4.2 congelata.

## Artefatti prodotti

Il wrapper assegna un prefisso della forma `article1-unified-v4-2-fb3f101b-YYYYMMDD-HHMMSS` e copia in `press/results/raw/`:

- `<prefisso>-results.json` e `<prefisso>-analysis.json`;
- `<prefisso>-summary.csv`, `<prefisso>-forks.csv` e `<prefisso>-observations.csv`;
- `<prefisso>-lifecycle-summary.csv` e `<prefisso>-lifecycle-forks.csv`;
- `<prefisso>-diagnostics.zip` e `<prefisso>-build.log`;
- `<prefisso>-raw.partial.json`, checkpoint di audit non usato come sorgente delle tabelle.

Dopo la chiusura della campagna, il validatore e l'estrattore producono l'evidenza derivata senza modificare i dati raw:

```powershell
$prefix = 'article1-unified-v4-2-fb3f101b-20260903-000401'
python .\scripts\validate_campaign_v4.py ".\press\results\raw\$prefix-results.json"
python .\scripts\extract_paper_v4_2.py `
  --results ".\press\results\raw\$prefix-results.json" `
  --analysis ".\press\results\raw\$prefix-analysis.json" `
  --output ".\press\results\raw\$prefix-paper-values.json"
python .\scripts\generate_paper_figures.py
```

Solo un dataset completo e accettato dal validatore può alimentare il paper, le figure e il workbook `Beyond_Throughput_Lifecycle_v4_2_Results.xlsx`. Lo script delle figure verifica i denominatori attesi prima di produrre i tre SVG. Per la pubblicazione corrente il prefisso canonico è quello dichiarato sopra; esiti, artefatti e checksum sono catalogati in `results/README.md` e `results/SHA256SUMS`.

# Protocollo congelato — campagna v4.2

**Studio:** *Beyond Throughput: A Reproducible Benchmark of Java Caches in a Tomcat Lifecycle*  
**Versione del protocollo:** 4.2  
**Congelato il:** 2 settembre 2026, prima dell'esecuzione della campagna v4.2  
**Stato dei dati al congelamento:** nessun risultato v4.2 disponibile. Le campagne v2 e v3 sono considerate pilota; il tentativo v4 e la campagna v4.1 sono conservati come campagne precedenti e non saranno combinati con la v4.2. La versione 4.2 mantiene immutati disegno, parametri e analisi della 4.1 e introduce soltanto due precisazioni nell'evidenza registrata: due conteggi distinti per il gate di popolamento e i tempi monotonic effettivi della diagnostica post-undeploy.

## 1. Obiettivo e domande

La campagna misura, con un unico harness e un unico ambiente containerizzato:

1. il throughput del percorso applicativo di quattro cache Java embedded in una web application Tomcat;
2. la correttezza osservabile del comportamento di cache richiesto dal workload;
3. il comportamento delle risorse dopo due sequenze deploy–workload–undeploy per ciclo;
4. la capacità del protocollo di rilevare il difetto JCS-248 usando Apache Commons JCS 3.2.1 come controllo positivo e JCS 4 come versione contenente la correzione;
5. la quota di segnali lifecycle prodotta dal solo harness, tramite un controllo `no-store` privo di motore di cache.

Il throughput non sarà interpretato come misura isolata della sola struttura dati interna. Il tratto cronometrato comprende adapter, contatori, concorrenza e motore di cache nella web application.

## 2. Condizioni sperimentali

Le sei condizioni sono incluse nello stesso WAR e nella stessa immagine Docker:

| Codice | Condizione | Ruolo nell'analisi |
|---|---|---|
| A | Caffeine 3.2.4 | confronto prestazionale primario |
| B | Ehcache 3.12.0 | confronto prestazionale primario |
| C | cache2k 2.6.1.Final | confronto prestazionale primario |
| D | Apache Commons JCS 4 dal commit registrato | confronto prestazionale primario e versione corretta |
| E | Apache Commons JCS 3.2.1 distribuito | controllo positivo JCS-248; analisi separata |
| F | `no-store` | controllo negativo del lifecycle; escluso dal confronto prestazionale |

JCS 3.2.1 e JCS 4 usano adapter e file di configurazione distinti, ma condividono tutto il resto dell'harness. Ogni processo esegue una sola condizione, così i singleton delle due versioni JCS non interagiscono.

## 3. Disegno e unità sperimentale

L'unità di replica indipendente è una JVM in un container ricreato. Sono previsti sei fork per condizione, cinque cicli per fork e due deploy completi per ciclo: 36 JVM, 180 cicli e 360 workload.

I sei fork completano una volta il disegno Williams 6 × 6; il numero non deriva da un calcolo di potenza statistica. Le JVM sono processi separati e non condividono stato JVM, ma vengono eseguite in sequenza sullo stesso host e possono quindi risentire delle sue variazioni temporali.

L'ordine è un disegno Williams 6 × 6 congelato:

| Blocco / fork | Ordine |
|---:|---|
| 1 | A, B, F, C, E, D |
| 2 | B, C, A, D, F, E |
| 3 | C, D, B, E, A, F |
| 4 | D, E, C, F, B, A |
| 5 | E, F, D, A, C, B |
| 6 | F, A, E, B, D, C |

Ogni condizione occupa una volta ciascuna posizione. Il numero del blocco, la posizione, l'ID del container e l'avvio della JVM saranno archiviati. Il seme base del workload è `24301` e il sale di campagna è `2482026`: entrambi entrano nella derivazione del seme del piano, che varia per blocco e ciclo ma resta identico fra condizioni appaiate e fra deploy iniziale e redeploy. Il sale non modifica l'ordine Williams, che è congelato nella tabella precedente.

## 4. Ambiente congelato

| Parametro | Valore nominale |
|---|---:|
| Tomcat | 11.0.24 |
| JDK | Eclipse Temurin 25 |
| CPU container | 4 vCPU |
| Memoria container | 1.536 MiB |
| Heap | `-Xms256m -Xmx768m` |
| Garbage collector | G1 |
| Native Memory Tracking | `summary` |
| JCS 4 `master` verificato | `fb3f101b87709b713468e8d827b8612e6e65f29b` |
| JCS 3.2.1 core SHA-256 | `12c6fe08223820089f60969b6088e6ac5d358aa872de78357585cdacb6c61049` |
| Immagine runtime | `tomcat:11.0.24-jdk25-temurin-noble@sha256:6d673ad42da6498f05755cae67f85f2128bdfd88943c9bdb22e0965f8d4c3182` |
| Immagine build | `maven:3.9.11-eclipse-temurin-25@sha256:407c4423cec0cf2981055bc2c6c0dc211d9605b6669279b95997f2d1c7e91e2c` |

Tag, ID e digest effettivi delle immagini, modello e quota CPU, processori visibili, kernel, versione del Docker Engine, sistema operativo del container, opzioni JVM, checksum del WAR, dei due core JCS, del runner e dei sorgenti dell'harness saranno salvati con i risultati. La build completa, i test Maven, l'effective POM e il dependency tree faranno parte degli artefatti.

## 5. Workload congelato

| Parametro | Valore |
|---|---:|
| Elementi | 10.000 |
| Dimensione payload | 512 byte ASCII esatti per valore |
| Thread applicativi | 8 |
| Hit pianificati | 95% |
| TTL | 300 s |
| Piano | uniforme, deterministico e pre-generato |
| Dimensione del piano riutilizzato | 400.000 operazioni |
| Operazioni nella finestra uniforme | sole letture (`writePercent` non applicato) |
| Warm-up minimo | 50.000 operazioni e almeno 3,0 s |
| Finestra cronometrata | almeno 5,0 s |
| Campionamento latenza | una operazione ogni 64 |
| Write probe fuori misura | 5.000 `put` |
| Prova single-flight fuori misura | 16 chiamanti; loader artificiale di 25 ms |

Il piano viene costruito fuori dalla finestra cronometrata e ripetuto fino al superamento della durata richiesta. Per ogni finestra si registrano operazioni completate, nanosecondi effettivi, overshoot, seed e checksum del piano. La fase di scrittura breve rimane diagnostica e non sostiene conclusioni prestazionali nel paper.

I 512 byte descrivono il contenuto ASCII codificato in UTF-8 di ciascun valore, non l'occupazione dell'oggetto `String` nell'heap. Il workload è closed-loop: ogni worker avvia l'operazione successiva al termine della precedente. Il campionamento sistematico registra una latenza ogni 64 operazioni per worker; i percentili empirici così ottenuti descrivono il tempo della chiamata adapter–provider, non la latenza HTTP né una garanzia SLO.

La campagna non tenta di rendere equivalente il costo della telemetria interna, che appartiene all'implementazione e ai default scelti. Non abilita però opzioni diagnostiche facoltative nel percorso primario: in particolare `recordStats()` di Caffeine resta disattivato. Hit rate e gate di correttezza sono calcolati esclusivamente dai contatori comuni dell'adapter.

Ogni deploy crea una sola istanza del provider. Warm-up e misura usano la stessa istanza; dopo il warm-up la cache viene svuotata e i contatori comuni vengono azzerati prima del fill misurato. Si hanno quindi due istanze per ciclo, una per ciascun deploy.

## 6. Sequenza di un ciclo

1. snapshot di baseline del ciclo;
2. deploy e verifica di readiness;
3. snapshot idle;
4. warm-up, reset, fill e workload cronometrato;
5. registrazione di `providerMetricsAfterWorkload` subito prima della write probe, esecuzione della write probe diagnostica di 5.000 `put`, registrazione di `providerMetricsAfterWriteProbe`, prova single-flight e snapshot a cache caricata;
6. undeploy;
7. trascorsa un'attesa minima di 2 s dall'undeploy, avvio della diagnostica precoce con log e thread dump, senza richiesta esplicita di GC da parte del runner;
8. trascorsa un'attesa minima di 10 s dall'undeploy, avvio della diagnostica finale: `findleaks`, due `GC.run` e, in sequenza, heap, class loader, thread dump, NMT e class histogram;
9. redeploy e ripetizione dello stesso piano;
10. secondo undeploy e stessa diagnostica.

Per ogni finestra post-undeploy vengono registrati, usando un orologio monotonic, l'avvio e il completamento della diagnostica precoce, l'avvio della sequenza finale, il completamento di `findleaks` e il completamento dello snapshot finale. Le soglie di 2 s e 10 s sono attese minime prima dell'avvio delle rispettive sequenze e non identificano un istante comune alle misure. Le singole operazioni interne allo snapshot finale non hanno un timestamp separato: sono acquisite in successione dopo `findleaks` e le due invocazioni di `GC.run`.

I campi temporali registrati sono:

| Campo | Significato |
|---|---|
| `earlyThreadSecondsAfterUndeploy` | campo legacy; target nominale dell'attesa minima prima della diagnostica precoce |
| `finalMeasurementSecondsAfterUndeploy` | campo legacy; target nominale dell'attesa minima prima della diagnostica finale |
| `earlyThreadTargetSecondsAfterUndeploy` | target esplicito dell'attesa minima prima dell'avvio della diagnostica precoce |
| `finalDiagnosticTargetSecondsAfterUndeploy` | target esplicito dell'attesa minima prima dell'avvio della diagnostica finale |
| `earlyThreadStartedSecondsAfterUndeploy` | tempo monotonic effettivo di avvio della diagnostica precoce |
| `earlyThreadCompletedSecondsAfterUndeploy` | tempo monotonic effettivo di completamento della diagnostica precoce |
| `finalDiagnosticStartedSecondsAfterUndeploy` | tempo monotonic effettivo di avvio della sequenza diagnostica finale |
| `findLeaksCompletedSecondsAfterUndeploy` | tempo monotonic effettivo al completamento di `findleaks` |
| `finalSnapshotCompletedSecondsAfterUndeploy` | tempo monotonic effettivo al completamento dell'ultimo snapshot della sequenza finale |

Tutti i campi espressi in secondi usano la stessa origine monotonic della relativa finestra post-undeploy. I campi legacy restano disponibili per compatibilità dello schema, ma non devono essere interpretati come timestamp osservati.

La diagnostica finale è invasiva: `findleaks` può richiedere a sua volta un full GC e il runner esegue inoltre due richieste esplicite tramite `GC.run`. I risultati finali descrivono pertanto lo stato osservato dopo questa sequenza diagnostica e non un decorso post-undeploy completamente passivo.

Dopo l'ultimo undeploy del quinto ciclo viene prodotto un heap dump per le due condizioni JCS, salvo impossibilità infrastrutturale documentata. I dump e i file diagnostici sono identificati da checksum.

## 7. Controlli di correttezza

Per le quattro cache correnti e JCS 3.2.1 si registrano:

- completamento della finestra richiesta e numero di operazioni;
- hit rate entro ±0,5 punti percentuali dal piano uniforme;
- `providerMetricsAfterWorkload`, acquisito subito prima della write probe, con almeno 9.900 elementi presenti;
- `providerMetricsAfterWriteProbe`, acquisito dopo la write probe diagnostica di 5.000 `put`, con almeno 9.900 elementi presenti;
- esito della prova single-flight;
- readiness e ripetizione completa del workload dopo redeploy.

Per `no-store` i criteri sono completamento, zero hit, `providerMetricsAfterWorkload` pari a zero e `providerMetricsAfterWriteProbe` pari a zero; il single-flight non è comparabile.

I due conteggi di popolamento sono campi distinti dell'evidenza e costituiscono due condizioni separate del gate semantico: per ogni cache entrambi devono essere almeno 9.900, mentre per `no-store` entrambi devono essere zero. Il valore acquisito dopo la write probe non può sostituire retroattivamente quello acquisito subito prima della sonda.

Una violazione semantica è un risultato e resta nel dataset. OOM, riavvio inatteso, timeout infrastrutturale, artefatto con checksum errato o diagnostica obbligatoria mancante invalidano l'intero blocco; il blocco può essere ripetuto soltanto conservando anche il tentativo fallito e la motivazione.

Il controllo di popolamento verifica che la cache rimanga vicina alla capacità configurata sia al termine del workload sia dopo una breve fase di ricambio; non verifica la conservazione delle specifiche chiavi inserite durante il fill. La prova single-flight è implementata nell'adapter comune e non viene presentata come semantica nativa identica dei quattro motori.

## 8. Evidenza lifecycle

Per thread e worker si conservano due viste:

- incremento rispetto alla baseline del ciclo;
- stock residuo rispetto alla baseline iniziale del processo.

La classificazione automatica è a tre stati: firma JCS riconosciuta, segnale thread non attribuito, nessun segnale rilevato. Il riconoscimento nominale è deliberatamente limitato alle firme JCS necessarie per il controllo JCS-248; gli altri provider non ricevono un'etichetta automatica di ownership. Nomi, ID, stack completi e warning Tomcat restano disponibili per ogni condizione, e un filtro per nome non costituisce da solo prova di ownership.

Le serie primarie di heap, NMT, class loader e thread usano i valori assoluti acquisiti nella sequenza diagnostica successiva all'undeploy finale. Le acquisizioni sono sequenziali, non simultanee; i dati temporali delimitano la sequenza, ma non attribuiscono un timestamp distinto a ciascun comando interno. Le pendenze sono calcolate separatamente dentro ogni JVM, mai concatenando cicli appartenenti a fork diversi. `findleaks` è conservato come sequenza di osservazioni e non trasformato automaticamente in un verdetto binario di leak.

## 9. Analisi congelata

Per ciascuna JVM e per ciascuna fase (`initial`, `redeploy`) si calcola la mediana dei cinque cicli. I sei valori indipendenti sono poi mostrati singolarmente e descritti con mediana, quartili e intervallo minimo–massimo.

Q1 e Q3 sono calcolati sui sei valori di fork ordinati mediante interpolazione lineare nella posizione `(n−1)p`, con `p=0,25` e `p=0,75`. La variazione dell'analisi di sensibilità è `(mediana cicli 2–5 − mediana cicli 1–5) / mediana cicli 1–5`, espressa in percentuale.

L'analisi prestazionale primaria include tutti i cicli. Un'analisi di sensibilità ripete il calcolo escludendo il primo ciclo, senza sostituire il risultato primario. I rapporti rispetto a JCS 4 sono calcolati entro lo stesso blocco prima della sintesi fra fork.

JCS 3.2.1 e `no-store` non partecipano a classifiche prestazionali. Non sono previsti punteggi compositi, pesi soggettivi, vincitori automatici, rimozione di outlier o pooling dei cicli come repliche indipendenti.

Nella sintesi primaria, una coppia fork–fase entra nel confronto prestazionale soltanto se tutte e cinque le finestre della fase superano il gate semantico. Nell'analisi di sensibilità il requisito vale per i cicli 2–5. Le finestre escluse rimangono nei dati raw. Un errore infrastrutturale invalida invece tutte le condizioni dello stesso blocco Williams.

Una JVM soddisfa il criterio di corroborazione JCS-248 quando, nello stesso intervallo successivo a un undeploy, viene rilevata almeno una firma thread JCS-specifica e il log Tomcat contiene almeno un warning di thread-leak relativo alla web application. Il controllo positivo è informativo se ciò accade in almeno cinque delle sei JVM JCS 3.2.1. Non viene imposta una pendenza numerica attesa. Apache Commons JCS 4.0.0-SNAPSHOT, compilato dal commit congelato, sarà descritto dai dati osservati con gli stessi criteri.

Le pendenze di ciclo di vita usano i cinque checkpoint successivi al secondo undeploy di ciascun ciclo, separatamente per ogni JVM. Le grandezze sono `heap used` acquisito dopo `findleaks` e le due richieste esplicite di GC, `NMT Total committed`, numero di righe `ParallelWebappClassLoader` e thread vivi. Per ogni sequenza restano disponibili il tempo di avvio, il completamento di `findleaks` e il completamento dello snapshot, non il timestamp di ogni singola grandezza. Per `findleaks` la sintesi principale è il numero di JVM in cui compare almeno una volta il context path della condizione; il conteggio delle occorrenze resta disponibile ma non viene interpretato come numero di class loader trattenuti.

## 10. Regole di pubblicazione

Il paper principale userà esclusivamente i dati v4.2. Le campagne precedenti resteranno materiale pilota o supplementare e non saranno combinate con la v4.2. Ogni tabella e grafico dovrà essere rigenerabile dai JSON raw tramite uno script versionato; i file raw non saranno sovrascritti dall'analisi. Qualunque deviazione dal presente protocollo sarà elencata prima dei risultati, con motivazione e impatto.

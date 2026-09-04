# Beyond Throughput Press Kit 1.0.1

Data di rilascio: 4 settembre 2026.

Release correttiva della prima distribuzione riproducibile dello studio *Beyond Throughput: A Reproducible Benchmark of Java Caches in a Tomcat Lifecycle*.

## Correzioni rispetto alla 1.0.0

- corretti quattro checksum che dipendevano dalla conversione CRLF/LF del checkout Git;
- allineati versione, data, metadati bibliografici, paper e archivi alla release 1.0.1;
- aggiunti controlli automatici multipiattaforma per test, build e provenienza;
- aggiunti i file e i template necessari alla collaborazione e alla segnalazione responsabile di vulnerabilità.

I dati della campagna, il protocollo v4.2, i risultati numerici e le conclusioni scientifiche non cambiano.

## Contenuto principale

- paper italiano e inglese in Markdown e PDF;
- protocollo sperimentale congelato v4.2;
- tre figure vettoriali generate dai dati canonici;
- impaginazione unica in Libertinus, con font incorporati e redistribuiti secondo SIL OFL 1.1;
- benchmark Tomcat/Docker eseguibile;
- workbook e riepiloghi della campagna definitiva;
- validatore, estrattore, generatore del paper, delle figure e del workbook;
- checksum SHA-256 dei file distribuiti.
- metadati bibliografici `CITATION.cff` e licenze esplicite: Apache-2.0 per il software, CC BY 4.0 per paper, protocollo, figure e dati originali.

## Identità sperimentale

- campagna: `article1-unified-v4-2-fb3f101b-20260903-000401`;
- protocollo: `4.2`;
- JCS 4: commit `fb3f101b87709b713468e8d827b8612e6e65f29b`;
- completezza: 36 JVM, 180 cicli e 360 finestre;
- validazione: `PASS`, 18.934 controlli, nessun errore e nessun warning.

## Struttura della distribuzione

Il press kit principale contiene il materiale destinato a lettori e revisori. L'archivio evidence associato conserva i dati canonici completi, il log della build e la diagnostica, separati per evitare di appesantire il pacchetto principale.

Le campagne pilota, gli smoke test e i materiali interni non fanno parte della release.

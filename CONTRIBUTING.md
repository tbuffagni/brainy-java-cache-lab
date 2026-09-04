# Contributing to Brainy Java Cache Lab

Thank you for helping improve the benchmark, its documentation, or its reproducibility.

## Choose the right channel

- Start a GitHub Discussion for methodological questions, interpretation of results, independent reproductions, or proposals for a future experiment.
- Open an issue when you can describe a specific, reproducible defect in the benchmark, paper, data, or documentation.
- Follow `SECURITY.md` for security-sensitive reports.

For substantial changes, open a discussion or issue before writing code so that scope and experimental consequences can be agreed first.

## Reproductions

A useful reproduction report identifies:

- repository release, tag, and commit;
- operating system and kernel;
- CPU model and allocated CPU count;
- physical memory and container memory limit;
- Docker, JVM, Maven, Python, and Tomcat versions;
- the exact command and non-default parameters;
- whether the run used the canonical protocol or a modified experiment;
- complete validation output and links to supporting artifacts.

Do not combine a modified run with the canonical v4.2 dataset. A change to cache versions, capacity, workload, CPU, memory, JVM options, timing, or scheduling defines a separate experiment.

## Pull requests

Keep pull requests focused and explain whether the change affects implementation, measurement, interpretation, or only documentation.

Before opening a pull request:

```text
python -m unittest discover -s scripts -p "test_*.py"
mvn -B -ntp -f vendor/commons-jcs4-main/pom.xml -pl commons-jcs4-core -am -DskipTests install
mvn -B -ntp -f press/benchmark/project/pom.xml test
```

The JCS 4 submodule must remain at the revision documented by the relevant protocol unless the pull request explicitly introduces a new experiment. Generated benchmark output and heap dumps must not be committed.

## Data and scientific claims

Raw observations are append-only evidence. Never rewrite raw data to make it agree with derived tables or prose. Changes to published values must identify the source data, validation result, derivation method, and affected release.

Separate confirmed observations from hypotheses. Performance differences in the complete application path must not be attributed to an individual cache engine without evidence that isolates that component.

## Licensing

By submitting a contribution, you agree that software contributions are licensed under Apache-2.0 and contributions to papers, protocols, figures, documentation, and original data are licensed under CC BY 4.0, as described in the repository.

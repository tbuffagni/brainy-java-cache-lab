ARG BUILD_IMAGE=maven:3.9.11-eclipse-temurin-25@sha256:407c4423cec0cf2981055bc2c6c0dc211d9605b6669279b95997f2d1c7e91e2c
ARG RUNTIME_IMAGE=tomcat:11.0.24-jdk25-temurin-noble@sha256:6d673ad42da6498f05755cae67f85f2128bdfd88943c9bdb22e0965f8d4c3182
ARG JCS4_COMMIT=unknown
ARG JCS4_VERSION=4.0.0-SNAPSHOT
ARG JCS4_COORDINATES=org.apache.commons:commons-jcs4-core:4.0.0-SNAPSHOT
ARG JCS321_VERSION=3.2.1
ARG JCS321_COORDINATES=org.apache.commons:commons-jcs3-core:3.2.1
ARG JCS321_SHA256=12c6fe08223820089f60969b6088e6ac5d358aa872de78357585cdacb6c61049

FROM ${BUILD_IMAGE} AS build
ARG JCS4_COMMIT
ARG JCS4_VERSION
ARG JCS321_VERSION
ARG JCS321_SHA256

# Compile and test the exact JCS 4 checkout used by the paper. Its local Maven
# artifact and the official JCS 3.2.1 binary intentionally coexist: their Java
# packages and Maven coordinates differ, so the same WAR can exercise both.
WORKDIR /jcs4
COPY vendor/commons-jcs4-main ./
RUN --mount=type=cache,id=cache-benchmark-v4-m2,target=/root/.m2 \
    mvn -B clean install

WORKDIR /workspace
COPY press/benchmark/project/pom.xml ./
COPY press/benchmark/project/src ./src

# `jcs.version` is the JCS 4 property retained by the harness POM;
# `jcs321.version` identifies the independent Maven Central control.
RUN --mount=type=cache,id=cache-benchmark-v4-m2,target=/root/.m2 \
    mvn -B \
        -Djcs.version=${JCS4_VERSION} \
        -Djcs321.version=${JCS321_VERSION} \
        clean verify && \
    mvn -B \
        -Djcs.version=${JCS4_VERSION} \
        -Djcs321.version=${JCS321_VERSION} \
        help:effective-pom \
        -Doutput=/tmp/effective-pom.xml && \
    mvn -B \
        -Djcs.version=${JCS4_VERSION} \
        -Djcs321.version=${JCS321_VERSION} \
        dependency:tree \
        -DoutputType=text \
        -DoutputFile=/tmp/dependency-tree.txt && \
    JCS4_JAR="/root/.m2/repository/org/apache/commons/commons-jcs4-core/${JCS4_VERSION}/commons-jcs4-core-${JCS4_VERSION}.jar" && \
    JCS321_JAR="/root/.m2/repository/org/apache/commons/commons-jcs3-core/${JCS321_VERSION}/commons-jcs3-core-${JCS321_VERSION}.jar" && \
    printf '%s  %s\n' "${JCS321_SHA256}" "${JCS321_JAR}" | sha256sum -c - && \
    mkdir -p /tmp/benchmark-artifacts && \
    cp target/cache-benchmark.war /tmp/benchmark-artifacts/cache-benchmark.war && \
    cp "${JCS4_JAR}" /tmp/benchmark-artifacts/ && \
    cp "${JCS321_JAR}" /tmp/benchmark-artifacts/ && \
    cp /tmp/effective-pom.xml /tmp/dependency-tree.txt /tmp/benchmark-artifacts/ && \
    sha256sum target/cache-benchmark.war \
        > /tmp/benchmark-artifacts/cache-benchmark.war.sha256 && \
    sha256sum "${JCS4_JAR}" \
        > /tmp/benchmark-artifacts/commons-jcs4-core.sha256 && \
    sha256sum "${JCS321_JAR}" \
        > /tmp/benchmark-artifacts/commons-jcs3-core.sha256 && \
    printf 'jcs4.commit=%s\njcs4.version=%s\njcs321.version=%s\njcs321.expectedSha256=%s\n' \
        "${JCS4_COMMIT}" "${JCS4_VERSION}" "${JCS321_VERSION}" "${JCS321_SHA256}" \
        > /tmp/benchmark-artifacts/build-provenance.properties

FROM ${RUNTIME_IMAGE}
ARG JCS4_COMMIT
ARG JCS4_VERSION
ARG JCS4_COORDINATES
ARG JCS321_VERSION
ARG JCS321_COORDINATES
ARG JCS321_SHA256

LABEL org.opencontainers.image.title="Beyond Throughput Tomcat lifecycle benchmark" \
      org.opencontainers.image.description="Unified Caffeine, Ehcache, cache2k, JCS 4 and JCS 3.2.1 lifecycle benchmark" \
      org.opencontainers.image.revision.jcs4="${JCS4_COMMIT}" \
      org.opencontainers.image.version.jcs4="${JCS4_VERSION}" \
      org.opencontainers.image.version.jcs321="${JCS321_VERSION}"

ENV JAVA_OPTS="-Xms256m -Xmx768m -XX:+UseG1GC -XX:NativeMemoryTracking=summary -Djava.awt.headless=true"
ENV CACHE_BENCH_JCS4_VERSION="${JCS4_VERSION}" \
    CACHE_BENCH_JCS4_COMMIT="${JCS4_COMMIT}" \
    CACHE_BENCH_JCS4_COORDINATES="${JCS4_COORDINATES}" \
    CACHE_BENCH_JCS321_VERSION="${JCS321_VERSION}" \
    CACHE_BENCH_JCS321_COORDINATES="${JCS321_COORDINATES}" \
    CACHE_BENCH_JCS321_SHA256="${JCS321_SHA256}"

RUN cp -R /usr/local/tomcat/webapps.dist/manager /usr/local/tomcat/webapps/manager

COPY docker/tomcat-users.xml /usr/local/tomcat/conf/tomcat-users.xml
COPY docker/manager-context.xml /usr/local/tomcat/webapps/manager/META-INF/context.xml
COPY --from=build /tmp/benchmark-artifacts/ /artifacts/

EXPOSE 8080

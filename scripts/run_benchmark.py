#!/usr/bin/env python3
"""Esegue il benchmark riproducibile nel Tomcat Docker locale."""

from __future__ import annotations

import base64
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "data"
PROTOCOL_VERSION = "4.2"
CONTAINER = "cache-benchmark-tomcat"
BASE = "http://localhost:18080"
COMPOSE_COMMAND = tuple(shlex.split(os.environ.get("CACHE_BENCH_COMPOSE_CMD", "docker-compose")))
COMPOSE_UP_ARGS = tuple(shlex.split(os.environ.get(
    "CACHE_BENCH_COMPOSE_UP_ARGS", "--no-build --force-recreate"
)))
CANONICAL_PROVIDERS = ("caffeine", "ehcache", "cache2k", "jcs4", "jcs321", "nostore")
PRIMARY_PERFORMANCE_PROVIDERS = frozenset({"caffeine", "ehcache", "cache2k", "jcs4"})
PROVIDERS = tuple(
    provider.strip()
    for provider in os.environ.get(
        "CACHE_BENCH_PROVIDERS", ",".join(CANONICAL_PROVIDERS)
    ).split(",")
    if provider.strip()
)
CYCLES = int(os.environ.get("CACHE_BENCH_CYCLES", "5"))
FORKS = int(os.environ.get("CACHE_BENCH_FORKS", "6"))
SCHEDULE_SEED = int(os.environ.get("CACHE_BENCH_SCHEDULE_SEED", "2482026"), 0)
RESULT_PREFIX = os.environ.get("CACHE_BENCH_RESULT_PREFIX", "benchmark")
EARLY_DIAGNOSTIC_SECONDS = float(
    os.environ.get("CACHE_BENCH_EARLY_DIAGNOSTIC_SETTLE_SECONDS",
                   os.environ.get("CACHE_BENCH_EARLY_DIAGNOSTIC_SECONDS", "2.0"))
)
FINAL_DIAGNOSTIC_SECONDS = float(
    os.environ.get("CACHE_BENCH_FINAL_DIAGNOSTIC_SETTLE_SECONDS",
                   os.environ.get("CACHE_BENCH_FINAL_DIAGNOSTIC_SECONDS", "10.0"))
)
FINAL_HEAP_DUMP_POLICY = os.environ.get(
    "CACHE_BENCH_HEAP_DUMP_POLICY",
    os.environ.get("CACHE_BENCH_FINAL_HEAP_DUMP_POLICY", "none")
).strip().lower()
DIAGNOSTIC_DIRECTORY = ROOT / "output" / "diagnostics" / RESULT_PREFIX
REQUEST = {
    "entries": int(os.environ.get("CACHE_BENCH_ENTRIES", "10000")),
    "operations": int(os.environ.get("CACHE_BENCH_OPERATIONS", "400000")),
    "threads": int(os.environ.get("CACHE_BENCH_THREADS", "8")),
    "hitPercent": int(os.environ.get("CACHE_BENCH_HIT_PERCENT", "95")),
    "payloadBytes": int(os.environ.get("CACHE_BENCH_PAYLOAD_BYTES", "512")),
    "warmupOperations": int(os.environ.get("CACHE_BENCH_WARMUP_OPERATIONS", "50000")),
    "warmupSeconds": float(os.environ.get("CACHE_BENCH_WARMUP_SECONDS", "3.0")),
    "measurementSeconds": float(os.environ.get("CACHE_BENCH_MEASUREMENT_SECONDS", "5.0")),
    "ttlSeconds": int(os.environ.get("CACHE_BENCH_TTL_SECONDS", "300")),
    "workload": os.environ.get("CACHE_BENCH_WORKLOAD", "uniform"),
    "writePercent": int(os.environ.get("CACHE_BENCH_WRITE_PERCENT", "10")),
    "jcsMemoryMode": os.environ.get("CACHE_BENCH_JCS_MODE", "strict"),
    "seed": int(os.environ.get("CACHE_BENCH_SEED", "24301"), 0),
    "latencySampleRate": int(os.environ.get("CACHE_BENCH_LATENCY_SAMPLE_RATE", "64")),
}
THREAD_MATRIX = tuple(int(value) for value in os.environ.get(
    "CACHE_BENCH_THREAD_MATRIX", str(REQUEST["threads"])).split(",") if value.strip())
HIT_MATRIX = tuple(int(value) for value in os.environ.get(
    "CACHE_BENCH_HIT_MATRIX", str(REQUEST["hitPercent"])).split(",") if value.strip())
WORKLOADS = tuple(value.strip() for value in os.environ.get(
    "CACHE_BENCH_WORKLOADS", REQUEST["workload"]).split(",") if value.strip())
JCS_MODES = tuple(value.strip() for value in os.environ.get(
    "CACHE_BENCH_JCS_MODES", REQUEST["jcsMemoryMode"]).split(",") if value.strip())
AUTH = "Basic " + base64.b64encode(b"benchmark:benchmark-local-only").decode("ascii")
LEAK_PATTERNS = re.compile(
    r"memory leak|started a thread|ThreadLocal (?:with key|value)|failed to unregister|WebappClassLoaderBase\.clearReferences",
    re.IGNORECASE,
)
WARN_PATTERNS = re.compile(r"\b(?:WARNING|WARN|SEVERE|ERROR)\b|deprecated|will be removed", re.IGNORECASE)
THREAD_LEAK_PATTERNS = re.compile(
    r"started a thread|ThreadLocal (?:with key|value)|clearReferencesThreads",
    re.IGNORECASE,
)
WEBAPP_CLASSLOADER = "org.apache.catalina.loader.ParallelWebappClassLoader"
THREAD_HEADER = re.compile(r'^"(?P<name>[^"]+)"(?:\s+daemon)?\s+#(?P<id>\d+)\b')
INFRASTRUCTURE_THREAD = re.compile(
    r"^(?:http-nio-|Catalina-|Attach Listener$|"
    r"C[12] CompilerThread|GC Thread#|G1 |VM |Sweeper thread$)",
    re.IGNORECASE,
)
JCS_THREAD_PATTERNS = {
    "jcs3-element-event-queue": re.compile(r"^JCS-ElementEventQueue-", re.IGNORECASE),
    "jcs4-thread-pool-event-queue": re.compile(
        r"^JCS-ThreadPoolManager-ElementEventQueue-", re.IGNORECASE
    ),
}

# Frozen canonical Williams 6x6 design.  Letter mapping is the canonical provider
# order above.  Do not shuffle these rows: reproducibility depends on preserving
# both the treatment mapping and row order.
WILLIAMS_ROWS = (
    (0, 1, 5, 2, 4, 3),  # A B F C E D
    (1, 2, 0, 3, 5, 4),  # B C A D F E
    (2, 3, 1, 4, 0, 5),  # C D B E A F
    (3, 4, 2, 5, 1, 0),  # D E C F B A
    (4, 5, 3, 0, 2, 1),  # E F D A C B
    (5, 0, 4, 1, 3, 2),  # F A E B D C
)


def atomic_write_text(path: Path, content: str) -> None:
    """Write a checkpoint in one replace operation on the destination volume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_provenance() -> dict:
    """Hash the harness inputs without copying source text into the result."""
    candidates = [
        ROOT / "scripts" / "run_benchmark.py",
        ROOT / "press" / "run-benchmark.ps1",
        ROOT / "press" / "benchmark" / "docker-compose.yml",
        ROOT / "press" / "benchmark" / "Dockerfile",
        ROOT / "docker" / "tomcat-users.xml",
        ROOT / "docker" / "manager-context.xml",
        ROOT / "press" / "article" / "protocollo-campagna-v4-2.md",
    ]
    project = ROOT / "press" / "benchmark" / "project"
    if project.exists():
        candidates.extend(path for path in project.rglob("*") if path.is_file())
    files = []
    for path in sorted(set(candidates), key=lambda item: item.as_posix()):
        if path.is_file():
            files.append({
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(path),
                "sizeBytes": path.stat().st_size,
            })
    aggregate = hashlib.sha256(
        "\n".join(f"{item['sha256']}  {item['path']}" for item in files).encode("utf-8")
    ).hexdigest()
    git_commit_output = run("git", "rev-parse", "HEAD", check=False).strip()
    valid_git_commit = (
        git_commit_output if re.fullmatch(r"[0-9a-fA-F]{40}", git_commit_output) else None
    )
    git_status = run("git", "status", "--porcelain", check=False) if valid_git_commit else ""
    jcs_source = ROOT / "vendor" / "commons-jcs4-main"
    jcs_commit_output = run(
        "git", "-C", str(jcs_source), "rev-parse", "HEAD", check=False
    ).strip()
    jcs_commit = (
        jcs_commit_output if re.fullmatch(r"[0-9a-fA-F]{40}", jcs_commit_output) else None
    )
    jcs_status = run(
        "git", "-C", str(jcs_source), "status", "--porcelain", "--untracked-files=all",
        check=False,
    ) if jcs_commit else ""
    return {
        "manifestSha256": aggregate,
        "files": files,
        "gitCommit": valid_git_commit,
        "gitDirty": bool(git_status.strip()) if valid_git_commit else None,
        "gitStatusSha256": hashlib.sha256(git_status.encode("utf-8")).hexdigest()
        if valid_git_commit else None,
        "jcs4VendorGitCommit": jcs_commit,
        "jcs4VendorGitDirty": bool(jcs_status.strip()) if jcs_commit else None,
        "jcs4VendorGitStatusSha256": hashlib.sha256(
            jcs_status.encode("utf-8")
        ).hexdigest() if jcs_commit else None,
    }


def williams_schedule(providers: tuple[str, ...] = PROVIDERS, forks: int = FORKS) -> list[dict]:
    if not providers or len(set(providers)) != len(providers):
        raise ValueError("providers must be a non-empty set of unique names")
    if forks < 1:
        raise ValueError("CACHE_BENCH_FORKS must be at least 1")
    schedule = []
    frozen_design = providers == CANONICAL_PROVIDERS
    for fork_index in range(forks):
        if frozen_design:
            row_index = fork_index % len(WILLIAMS_ROWS)
            repetition = fork_index // len(WILLIAMS_ROWS) + 1
            order = [providers[index] for index in WILLIAMS_ROWS[row_index]]
        else:
            row_index = fork_index % len(providers)
            repetition = fork_index // len(providers) + 1
            order = list(providers[row_index:] + providers[:row_index])
        schedule.append({
            "fork": fork_index + 1,
            "block": fork_index + 1,
            "williamsRow": row_index + 1 if frozen_design else None,
            "williamsRepetition": repetition if frozen_design else None,
            "design": "frozen-Williams-6x6" if frozen_design else "cyclic-subset",
            "order": order,
        })
    return schedule


def paired_request_seed(base_seed: int, schedule_seed: int, block: int, cycle: int) -> int:
    """Stable seed shared by every provider and both phases in a block/cycle."""
    material = (
        f"cache-benchmark-v4:base:{base_seed}:campaign:{schedule_seed}:"
        f"block:{block}:cycle:{cycle}"
    ).encode()
    # Remain in the positive signed-int range accepted by the Java request DTO.
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big") & 0x7fffffff


def run(*args: str, timeout: int = 120, check: bool = True) -> str:
    completed = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
    )
    if check and completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}\n{completed.stdout}")
    return completed.stdout


def http(url: str, method: str = "GET", payload: dict | None = None, manager: bool = False,
         timeout: int = 300) -> tuple[int, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if manager:
        headers["Authorization"] = AUTH
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as failure:
        return failure.code, failure.read().decode("utf-8", "replace")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, ""


def wait_tomcat(timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = http(f"{BASE}/manager/text/serverinfo", manager=True, timeout=5)
        if status == 200 and body.startswith("OK"):
            return
        time.sleep(0.5)
    raise TimeoutError("Tomcat manager not ready")


def wait_app(provider: str, expected: bool, timeout: int = 90) -> float:
    started = time.perf_counter()
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = http(f"{BASE}/{provider}/api/info", timeout=5)
        if expected and status == 200:
            info = json.loads(body)
            if info.get("ready") and info.get("provider") == provider:
                return (time.perf_counter() - started) * 1000
        if not expected and status == 404:
            return (time.perf_counter() - started) * 1000
        time.sleep(0.25)
    raise TimeoutError(f"application {provider}: expected deployed={expected}")


def manager(action: str, provider: str) -> str:
    query = {"path": f"/{provider}"}
    if action == "deploy":
        query.update({"war": "file:/artifacts/cache-benchmark.war", "update": "true"})
    url = f"{BASE}/manager/text/{action}?{urllib.parse.urlencode(query)}"
    status, body = http(url, manager=True, timeout=120)
    if status != 200 or not body.startswith("OK"):
        raise RuntimeError(f"manager {action} failed ({status}): {body}")
    return body.strip()


def deploy(provider: str) -> float:
    started = time.perf_counter()
    manager("deploy", provider)
    wait_app(provider, True)
    return (time.perf_counter() - started) * 1000


def undeploy(provider: str) -> float:
    started = time.perf_counter()
    manager("undeploy", provider)
    wait_app(provider, False)
    return (time.perf_counter() - started) * 1000


def jcmd(command: str) -> str:
    return run("docker", "exec", CONTAINER, "jcmd", "1", *command.split(), timeout=120)


def diagnostic_file(label: str, kind: str, content: str) -> str:
    DIAGNOSTIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")
    filename = f"{safe_label}-{kind}.txt"
    atomic_write_text(DIAGNOSTIC_DIRECTORY / filename, content)
    return filename


def thread_records(thread_dump: str) -> list[dict]:
    records = []
    for line in thread_dump.splitlines():
        match = THREAD_HEADER.match(line)
        if match:
            records.append({"id": int(match.group("id")), "name": match.group("name")})
    return records


def find_leaks() -> str:
    url = f"{BASE}/manager/text/findleaks?statusLine=true"
    status, body = http(url, manager=True, timeout=120)
    if status != 200 or not body.startswith("OK"):
        raise RuntimeError(f"manager findleaks failed ({status}): {body}")
    return body


def find_leak_contexts(report: str) -> list[str]:
    return list(dict.fromkeys(find_leak_occurrences(report)))


def find_leak_occurrences(report: str) -> list[str]:
    """Preserve every Manager occurrence; findleaks output can be cumulative."""
    return [line.strip() for line in report.splitlines() if line.strip().startswith("/")]


def jcs_thread_signatures(records: list[dict]) -> list[dict]:
    signatures = []
    for thread in records:
        for signature, pattern in JCS_THREAD_PATTERNS.items():
            if pattern.search(thread["name"]):
                signatures.append({**thread, "signature": signature})
    return signatures


def thread_only_snapshot(label: str, archive_details: bool = True) -> dict:
    dump = jcmd("Thread.print")
    records = thread_records(dump)
    result = {
        "label": label,
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "liveThreadCount": len(records),
        "threads": records,
        "jcsThreadSignatures": jcs_thread_signatures(records),
    }
    if archive_details:
        result["diagnosticArtifacts"] = {
            "threadDump": diagnostic_file(label, "thread-dump", dump)
        }
    return result


def snapshot(label: str, archive_details: bool = False, force_gc: bool = False,
             include_histogram: bool = False) -> dict:
    if include_histogram and not archive_details:
        raise ValueError("a class histogram requires archived snapshot details")
    forced_gc_count = 0
    if force_gc:
        jcmd("GC.run")
        time.sleep(0.25)
        jcmd("GC.run")
        forced_gc_count = 2
    heap = jcmd("GC.heap_info")
    loaders = jcmd("VM.classloader_stats")
    threads = jcmd("Thread.print")
    native = jcmd("VM.native_memory summary")
    heap_match = re.search(r"\bused\s+(\d+)K\b", heap)
    committed_match = re.search(r"\bcommitted\s+(\d+)K\b", heap)
    nmt_match = re.search(r"Total: reserved=\d+KB, committed=(\d+)KB", native)
    if not heap_match:
        raise RuntimeError(f"cannot parse heap: {heap}")
    if not nmt_match:
        raise RuntimeError(
            "Native Memory Tracking summary is unavailable or cannot be parsed"
        )
    loader_rows = [line.strip() for line in loaders.splitlines() if WEBAPP_CLASSLOADER in line]
    records = thread_records(threads)
    result = {
        "label": label,
        "capturedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "heapUsedBytes": int(heap_match.group(1)) * 1024,
        "heapCommittedBytes": int(committed_match.group(1)) * 1024 if committed_match else None,
        "nativeCommittedBytes": int(nmt_match.group(1)) * 1024 if nmt_match else None,
        "webappClassloaderCount": len(loader_rows),
        "webappClassloaderRows": loader_rows,
        "liveThreadCount": len(records),
        "threads": records,
        "jcsThreadSignatures": jcs_thread_signatures(records),
        "forcedGcCount": forced_gc_count,
    }
    if archive_details:
        result["diagnosticArtifacts"] = {
            "heapInfo": diagnostic_file(label, "heap-info", heap),
            "classloaderStats": diagnostic_file(label, "classloader-stats", loaders),
            "threadDump": diagnostic_file(label, "thread-dump", threads),
            "nativeMemory": diagnostic_file(label, "native-memory", native),
        }
        if include_histogram:
            histogram = jcmd("GC.class_histogram")
            result["diagnosticArtifacts"]["classHistogram"] = diagnostic_file(
                label, "class-histogram", histogram
            )
    return result


def wait_until(started: float, elapsed_seconds: float) -> None:
    remaining = started + elapsed_seconds - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def post_undeploy_snapshot(label: str, log_baseline: str) -> dict:
    """Capture diagnostics and their monotonic elapsed times after undeploy returns.

    The final delay is a minimum target for starting the diagnostic sequence, not
    a claim that every final command completes at that exact instant.
    """
    started = time.monotonic()
    wait_until(started, EARLY_DIAGNOSTIC_SECONDS)
    early_thread_started = time.monotonic()
    early = thread_only_snapshot(f"{label}-early-{EARLY_DIAGNOSTIC_SECONDS:g}s")
    early_log_lines = appended_log_lines(log_baseline, docker_logs())
    early["tomcatLogLineCountSinceUndeploy"] = len(early_log_lines)
    early["diagnosticArtifacts"]["tomcatLog"] = diagnostic_file(
        label + "-early", "tomcat-log", "\n".join(early_log_lines) + "\n"
    )
    early_thread_completed = time.monotonic()
    wait_until(started, FINAL_DIAGNOSTIC_SECONDS)
    final_diagnostic_started = time.monotonic()
    report = find_leaks()
    find_leaks_completed = time.monotonic()
    final = snapshot(
        f"{label}-final-{FINAL_DIAGNOSTIC_SECONDS:g}s",
        archive_details=True,
        force_gc=True,
        include_histogram=True,
    )
    final_snapshot_completed = time.monotonic()
    occurrences = find_leak_occurrences(report)
    final["tomcatFindLeaksOccurrences"] = occurrences
    final["tomcatFindLeaksOccurrenceCount"] = len(occurrences)
    final["tomcatFindLeaksOccurrenceCountsByContext"] = dict(
        collections.Counter(occurrences)
    )
    final["tomcatFindLeaksContexts"] = list(dict.fromkeys(occurrences))
    final["tomcatFindLeaksDetected"] = bool(occurrences)
    final["diagnosticArtifacts"]["tomcatFindLeaks"] = diagnostic_file(
        label, "tomcat-findleaks", report
    )
    return {
        "earlyThreadObservation": early,
        "finalObservation": final,
        "timing": {
            # Compatibility fields: both are configured targets, not observations.
            "earlyThreadSecondsAfterUndeploy": EARLY_DIAGNOSTIC_SECONDS,
            "finalMeasurementSecondsAfterUndeploy": FINAL_DIAGNOSTIC_SECONDS,
            "earlyThreadTargetSecondsAfterUndeploy": EARLY_DIAGNOSTIC_SECONDS,
            "finalDiagnosticTargetSecondsAfterUndeploy": FINAL_DIAGNOSTIC_SECONDS,
            "earlyThreadStartedSecondsAfterUndeploy": early_thread_started - started,
            "earlyThreadCompletedSecondsAfterUndeploy": early_thread_completed - started,
            "finalDiagnosticStartedSecondsAfterUndeploy": (
                final_diagnostic_started - started
            ),
            "findLeaksCompletedSecondsAfterUndeploy": find_leaks_completed - started,
            "finalSnapshotCompletedSecondsAfterUndeploy": (
                final_snapshot_completed - started
            ),
        },
    }


def restart_clean() -> None:
    run(*COMPOSE_COMMAND, "stop", timeout=120)
    run(*COMPOSE_COMMAND, "up", "-d", *COMPOSE_UP_ARGS, timeout=180)
    wait_tomcat()


def docker_image_metadata(reference: str | None) -> dict | None:
    if not reference:
        return None
    pinned_match = re.search(r"@sha256:([0-9a-f]{64})$", reference, re.IGNORECASE)
    pinned_digest = f"sha256:{pinned_match.group(1).lower()}" if pinned_match else None
    output = run("docker", "image", "inspect", reference, check=False)
    try:
        item = json.loads(output)[0]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        return {
            "reference": reference,
            "inspectionAvailable": False,
            "pinnedDigest": pinned_digest,
        }
    return {
        "reference": reference,
        "inspectionAvailable": True,
        "pinnedDigest": pinned_digest,
        "id": item.get("Id"),
        "repoDigests": item.get("RepoDigests", []),
        "created": item.get("Created"),
        "os": item.get("Os"),
        "architecture": item.get("Architecture"),
    }


def parse_cpu_info(cpu_info: str) -> tuple[str, int]:
    """Return a human CPU model and visible processor count from /proc/cpuinfo."""
    cpu_model = None
    cpu_processor_fallback = None
    for line in cpu_info.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key in {"model name", "hardware"} and normalized_value:
            cpu_model = normalized_value
            break
        if (normalized_key == "processor" and normalized_value
                and not normalized_value.isdigit() and cpu_processor_fallback is None):
            cpu_processor_fallback = normalized_value
    visible = len(re.findall(
        r"^processor\s*:", cpu_info, flags=re.MULTILINE | re.IGNORECASE
    ))
    return cpu_model or cpu_processor_fallback or "unknown", visible


def server_info() -> dict:
    _, body = http(f"{BASE}/manager/text/serverinfo", manager=True)
    values = {}
    for line in body.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip("[]")
    values["dockerImageId"] = run("docker", "inspect", "--format={{.Image}}", CONTAINER).strip()
    values["containerImageName"] = run(
        "docker", "inspect", "--format={{.Config.Image}}", CONTAINER
    ).strip()
    values["containerId"] = run(
        "docker", "inspect", "--format={{.Id}}", CONTAINER
    ).strip()
    values["containerStartedAt"] = run(
        "docker", "inspect", "--format={{.State.StartedAt}}", CONTAINER
    ).strip()
    values["imageJcs4RevisionLabel"] = run(
        "docker", "inspect",
        "--format={{ index .Config.Labels \"org.opencontainers.image.revision.jcs4\" }}",
        CONTAINER,
    ).strip()
    host_config = json.loads(run(
        "docker", "inspect", "--format={{json .HostConfig}}", CONTAINER
    ))
    values["containerCpuLimit"] = host_config.get("NanoCpus", 0) / 1_000_000_000
    values["containerMemoryLimitBytes"] = host_config.get("Memory", 0)
    os_release = run("docker", "exec", CONTAINER, "cat", "/etc/os-release", check=False)
    os_values = {}
    for line in os_release.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            os_values[key] = value.strip().strip('"')
    values["containerOS"] = os_values.get("PRETTY_NAME", os_values.get("NAME", "unknown"))
    cpu_info = run("docker", "exec", CONTAINER, "cat", "/proc/cpuinfo", check=False)
    cpu_model, visible_processors = parse_cpu_info(cpu_info)
    values["containerCpuModel"] = cpu_model
    values["containerVisibleProcessors"] = visible_processors
    values["containerKernel"] = run(
        "docker", "exec", CONTAINER, "uname", "-a", check=False
    ).strip()
    docker_info_text = run("docker", "info", "--format={{json .}}", check=False)
    try:
        docker_info = json.loads(docker_info_text)
    except json.JSONDecodeError:
        docker_info = {}
    values["dockerServerVersion"] = docker_info.get("ServerVersion")
    values["dockerServerOperatingSystem"] = docker_info.get("OperatingSystem")
    values["dockerServerKernelVersion"] = docker_info.get("KernelVersion")
    values["dockerServerArchitecture"] = docker_info.get("Architecture")
    values["dockerServerName"] = docker_info.get("Name")
    values["javaOptions"] = os.environ.get("CACHE_BENCH_JAVA_OPTS", "")
    values["jcsVersion"] = os.environ.get("CACHE_BENCH_JCS_VERSION", "unknown")
    values["jcsSourceCommit"] = os.environ.get("CACHE_BENCH_JCS_COMMIT", "unknown")
    values["jcsArtifactCoordinates"] = os.environ.get(
        "CACHE_BENCH_JCS_COORDINATES", "unknown"
    )
    values["jcs4Version"] = os.environ.get("CACHE_BENCH_JCS4_VERSION", "unknown")
    values["jcs4SourceCommit"] = os.environ.get(
        "CACHE_BENCH_JCS4_COMMIT", "unknown"
    )
    values["jcs4ArtifactCoordinates"] = os.environ.get(
        "CACHE_BENCH_JCS4_COORDINATES", "unknown"
    )
    values["jcs321Version"] = os.environ.get("CACHE_BENCH_JCS321_VERSION", "unknown")
    values["jcs321ArtifactCoordinates"] = os.environ.get(
        "CACHE_BENCH_JCS321_COORDINATES", "unknown"
    )
    values["jcs321ExpectedSha256"] = os.environ.get(
        "CACHE_BENCH_JCS321_SHA256"
    )
    values["requestedRuntimeImage"] = os.environ.get("CACHE_BENCH_TOMCAT_IMAGE")
    values["requestedBuildImage"] = os.environ.get("CACHE_BENCH_BUILD_IMAGE")
    values["runtimeBaseImage"] = docker_image_metadata(values["requestedRuntimeImage"])
    values["buildBaseImage"] = docker_image_metadata(values["requestedBuildImage"])
    values["jvmCommandLine"] = jcmd("VM.command_line")
    values["jvmFlags"] = jcmd("VM.flags")
    checksum_output = run(
        "docker", "exec", CONTAINER, "sh", "-c",
        "sha256sum /artifacts/*.war /artifacts/*.jar 2>/dev/null || true",
        check=False,
    )
    artifact_manifest = []
    for line in checksum_output.splitlines():
        match = re.match(r"^([0-9a-f]{64})\s+(.+)$", line.strip())
        if match:
            artifact_manifest.append({"sha256": match.group(1), "containerPath": match.group(2)})
    values["artifactManifest"] = artifact_manifest
    for result_key, filename in (
        ("jcs4ArtifactSha256", "commons-jcs4-core.sha256"),
        ("jcs321ArtifactSha256", "commons-jcs3-core.sha256"),
        ("warSha256", "cache-benchmark.war.sha256"),
    ):
        checksum_output = run(
            "docker", "exec", CONTAINER, "cat", f"/artifacts/{filename}", check=False
        )
        checksum_match = re.match(r"^([0-9a-f]{64})\s+", checksum_output)
        values[result_key] = checksum_match.group(1) if checksum_match else None
    provenance_output = run(
        "docker", "exec", CONTAINER, "cat", "/artifacts/build-provenance.properties",
        check=False,
    )
    build_provenance = {}
    for line in provenance_output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            build_provenance[key.strip()] = value.strip()
    values["imageBuildProvenance"] = build_provenance
    archived_build_files = []
    for container_path, filename in (
        ("/artifacts/effective-pom.xml", "effective-pom.xml"),
        ("/artifacts/dependency-tree.txt", "dependency-tree.txt"),
        ("/artifacts/build-provenance.properties", "build-provenance.properties"),
    ):
        content = run("docker", "exec", CONTAINER, "cat", container_path)
        host_path = DIAGNOSTIC_DIRECTORY / filename
        atomic_write_text(host_path, content)
        archived_build_files.append({
            "file": filename,
            "sha256": sha256_file(host_path),
            "sizeBytes": host_path.stat().st_size,
        })
    values["archivedBuildFiles"] = archived_build_files
    expected_jcs4_commit = values["jcs4SourceCommit"]
    expected_jcs321_sha = values["jcs321ExpectedSha256"]
    provenance_errors = []
    if values["imageJcs4RevisionLabel"] != expected_jcs4_commit:
        provenance_errors.append(
            "image JCS 4 revision label does not match requested source commit"
        )
    if build_provenance.get("jcs4.commit") != expected_jcs4_commit:
        provenance_errors.append(
            "embedded build provenance does not match requested JCS 4 source commit"
        )
    if values["jcs321ArtifactSha256"] != expected_jcs321_sha:
        provenance_errors.append(
            "embedded JCS 3.2.1 artifact checksum does not match the frozen checksum"
        )
    values["provenanceValidationPassed"] = not provenance_errors
    values["provenanceValidationErrors"] = provenance_errors
    if provenance_errors:
        raise RuntimeError("; ".join(provenance_errors))
    values["hostTimestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return values


def preflight_environment() -> dict:
    """Fail once, before measured JVMs, for campaign-wide configuration errors."""
    wait_tomcat()
    values = server_info()
    native = jcmd("VM.native_memory summary")
    if not re.search(r"Total: reserved=\d+KB, committed=\d+KB", native):
        raise RuntimeError("campaign preflight failed: Native Memory Tracking unavailable")
    values["nativeMemoryTrackingSummaryAvailable"] = True
    values["preflightNativeMemoryArtifact"] = diagnostic_file(
        "campaign-preflight", "native-memory", native
    )
    return values


def clean_all_apps() -> None:
    for provider in PROVIDERS:
        status, _ = http(f"{BASE}/{provider}/api/info", timeout=3)
        if status == 200:
            try:
                undeploy(provider)
            except Exception:
                pass


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_protocol(provider: str, request: dict, workload: dict, phase: str) -> dict:
    metrics_after_workload, metrics_after_write_probe = provider_metric_checkpoints(workload)
    metric_checkpoints_valid = bool(
        metrics_after_workload and metrics_after_write_probe
    )
    observed_hit_rate = float(metrics_after_workload.get("hitRate", 0.0))
    expected_hit_rate = request["hitPercent"] / 100.0
    entries_after_workload = int(metrics_after_workload.get("currentEntries", 0))
    entries_after_write_probe = int(
        metrics_after_write_probe.get("currentEntries", 0)
    )
    single_flight_valid = bool(workload.get("singleFlightPassed", False))
    requested_operations_value = request.get("operations")
    measured_operations_value = workload.get("measuredOperations")
    operations_per_second_value = workload.get("operationsPerSecond")
    operation_measurements_valid = (
        _is_nonnegative_integer(requested_operations_value)
        and requested_operations_value > 0
        and _is_nonnegative_integer(measured_operations_value)
        and _is_finite_number(operations_per_second_value)
        and float(operations_per_second_value) > 0.0
    )
    requested_operations = (
        requested_operations_value
        if _is_nonnegative_integer(requested_operations_value)
        else 0
    )
    measured_operations = (
        measured_operations_value
        if _is_nonnegative_integer(measured_operations_value)
        else 0
    )
    completed_operations = (
        operation_measurements_valid
        and measured_operations >= requested_operations
    )
    requested_measurement_nanos = int(
        float(request.get("measurementSeconds", 0.0)) * 1_000_000_000
    )
    observed_measurement_nanos = int(workload.get("measurementNanos", 0))
    duration_valid = (
        requested_measurement_nanos == 0
        or observed_measurement_nanos >= requested_measurement_nanos
    )
    if provider == "nostore":
        capacity_after_workload_valid = (
            bool(metrics_after_workload) and entries_after_workload == 0
        )
        capacity_after_write_probe_valid = (
            bool(metrics_after_write_probe) and entries_after_write_probe == 0
        )
        capacity_valid = (
            capacity_after_workload_valid and capacity_after_write_probe_valid
        )
        zero_hits = observed_hit_rate == 0.0
        return {
            "phase": phase,
            "gateType": "no-store-control",
            "performanceComparisonEligible": False,
            "completedOperations": completed_operations,
            "requiredOperations": requested_operations,
            "measuredOperations": measured_operations,
            "operationMeasurementsValid": operation_measurements_valid,
            "providerMetricCheckpointsValid": metric_checkpoints_valid,
            "requestedMeasurementNanos": requested_measurement_nanos,
            "observedMeasurementNanos": observed_measurement_nanos,
            "measurementDurationPassed": duration_valid,
            "expectedStoredEntries": 0,
            "observedEntriesAfterWorkload": entries_after_workload,
            "capacityAfterWorkloadPassed": capacity_after_workload_valid,
            "observedEntriesAfterWriteProbe": entries_after_write_probe,
            "capacityAfterWriteProbePassed": capacity_after_write_probe_valid,
            "capacityCheckPassed": capacity_valid,
            "noEntriesRetained": capacity_valid,
            "hitRate": observed_hit_rate,
            "zeroHits": zero_hits,
            "hitRateGateApplicable": False,
            "singleFlightGateApplicable": False,
            "passed": (completed_operations and duration_valid
                       and metric_checkpoints_valid and capacity_valid and zero_hits),
        }
    hit_rate_valid = (
        request["workload"].lower() != "uniform"
        or abs(observed_hit_rate - expected_hit_rate) <= 0.005
    )
    minimum_entries = int(request["entries"] * 0.99)
    capacity_after_workload_valid = (
        bool(metrics_after_workload) and entries_after_workload >= minimum_entries
    )
    capacity_after_write_probe_valid = (
        bool(metrics_after_write_probe) and entries_after_write_probe >= minimum_entries
    )
    capacity_valid = capacity_after_workload_valid and capacity_after_write_probe_valid
    return {
        "phase": phase,
        "gateType": "cache-semantics",
        "performanceComparisonEligible": provider in PRIMARY_PERFORMANCE_PROVIDERS,
        "completedOperations": completed_operations,
        "requiredOperations": requested_operations,
        "measuredOperations": measured_operations,
        "operationMeasurementsValid": operation_measurements_valid,
        "providerMetricCheckpointsValid": metric_checkpoints_valid,
        "requestedMeasurementNanos": requested_measurement_nanos,
        "observedMeasurementNanos": observed_measurement_nanos,
        "measurementDurationPassed": duration_valid,
        "expectedHitRate": expected_hit_rate,
        "observedHitRate": observed_hit_rate,
        "hitRateWithinHalfPercentagePoint": hit_rate_valid,
        "minimumExpectedEntriesAfterWorkload": minimum_entries,
        "observedEntriesAfterWorkload": entries_after_workload,
        "capacityAfterWorkloadPassed": capacity_after_workload_valid,
        "minimumExpectedEntriesAfterWriteProbe": minimum_entries,
        "observedEntriesAfterWriteProbe": entries_after_write_probe,
        "capacityAfterWriteProbePassed": capacity_after_write_probe_valid,
        "capacityCheckPassed": capacity_valid,
        "singleFlightPassed": single_flight_valid,
        "passed": (completed_operations and duration_valid and metric_checkpoints_valid
                   and hit_rate_valid
                   and capacity_valid and single_flight_valid),
    }


def provider_metric_checkpoints(workload: dict) -> tuple[dict, dict]:
    """Return only explicit, minimally well-formed v4.2 metric checkpoints."""
    after_workload = workload.get("providerMetricsAfterWorkload")
    after_write_probe = workload.get("providerMetricsAfterWriteProbe")
    if not (
        isinstance(after_workload, dict)
        and _is_nonnegative_integer(after_workload.get("currentEntries"))
        and _is_finite_number(after_workload.get("hitRate"))
        and 0.0 <= float(after_workload["hitRate"]) <= 1.0
    ):
        after_workload = {}
    if not (
        isinstance(after_write_probe, dict)
        and _is_nonnegative_integer(after_write_probe.get("currentEntries"))
    ):
        after_write_probe = {}
    return after_workload, after_write_probe


def execute_workload(provider: str, request: dict, phase: str) -> tuple[dict, dict]:
    status, body = http(f"{BASE}/{provider}/api/run", method="POST", payload=request, timeout=600)
    if status != 200:
        raise RuntimeError(f"benchmark {provider} ({phase}) failed ({status}): {body}")
    workload = json.loads(body)
    protocol_validation = validate_protocol(provider, request, workload, phase)
    # A semantic gate failure is an observation, not an infrastructure error.  It
    # remains in the raw data and excludes that run from valid comparisons later.
    if not protocol_validation["passed"]:
        print(f"semantic gate failed for {provider} ({phase}); run retained")
    return workload, protocol_validation


def new_thread_records(before: dict, after: dict) -> list[dict]:
    baseline_ids = {thread["id"] for thread in before["threads"]}
    return [thread for thread in after["threads"] if thread["id"] not in baseline_ids]


def candidate_application_threads(records: list[dict]) -> list[dict]:
    return [
        thread for thread in records
        if not INFRASTRUCTURE_THREAD.search(thread["name"])
    ]


def thread_evidence(process_baseline: dict, cycle_baseline: dict,
                    observation: dict) -> dict:
    process_new = new_thread_records(process_baseline, observation)
    cycle_new = new_thread_records(cycle_baseline, observation)
    process_candidates = candidate_application_threads(process_new)
    cycle_candidates = candidate_application_threads(cycle_new)
    signatures = observation.get("jcsThreadSignatures", [])
    if signatures:
        classification = "jcs-signature-present"
    elif process_candidates:
        classification = "unattributed-thread-signal"
    else:
        classification = "no-post-undeploy-thread-signal"
    return {
        "threadStock": observation["liveThreadCount"],
        "threadStockDeltaVsProcessBaseline": (
            observation["liveThreadCount"] - process_baseline["liveThreadCount"]
        ),
        "threadStockDeltaVsCycleBaseline": (
            observation["liveThreadCount"] - cycle_baseline["liveThreadCount"]
        ),
        "threadsNotPresentAtProcessBaseline": process_new,
        "threadsNotPresentAtCycleBaseline": cycle_new,
        "candidateApplicationThreadsVsProcessBaseline": process_candidates,
        "candidateApplicationThreadsVsCycleBaseline": cycle_candidates,
        "jcsThreadSignatures": signatures,
        "classification": classification,
        "classificationBasis": (
            "automated signatures are JCS-specific; all other candidate application "
            "threads remain unattributed and ownership requires the archived full dump"
        ),
    }


def docker_logs() -> str:
    return run("docker", "logs", CONTAINER, timeout=120, check=False)


def appended_log_lines(previous: str, current: str) -> list[str]:
    if current.startswith(previous):
        return current[len(previous):].splitlines()
    previous_lines = previous.splitlines()
    return current.splitlines()[len(previous_lines):]


def classified_warnings(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    warnings = [line.strip() for line in lines if WARN_PATTERNS.search(line)]
    leak_warnings = [line for line in warnings if LEAK_PATTERNS.search(line)]
    thread_leak_warnings = [line for line in warnings if THREAD_LEAK_PATTERNS.search(line)]
    return warnings, leak_warnings, thread_leak_warnings


def maybe_final_heap_dump(label: str, provider: str, failure_observed: bool) -> dict | None:
    if FINAL_HEAP_DUMP_POLICY not in {"none", "jcs", "all", "always", "on-failure"}:
        raise ValueError(
            "CACHE_BENCH_HEAP_DUMP_POLICY must be none, jcs, or all"
        )
    capture = FINAL_HEAP_DUMP_POLICY in {"all", "always"} or (
        FINAL_HEAP_DUMP_POLICY == "jcs" and provider in {"jcs4", "jcs321"}
    ) or (
        FINAL_HEAP_DUMP_POLICY == "on-failure" and failure_observed
    )
    if not capture:
        return None
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")
    filename = f"{safe_label}-final.hprof"
    container_path = f"/tmp/{filename}"
    host_path = DIAGNOSTIC_DIRECTORY / filename
    DIAGNOSTIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output = jcmd(f"GC.heap_dump {container_path}")
    run("docker", "cp", f"{CONTAINER}:{container_path}", str(host_path), timeout=600)
    return {
        "policy": FINAL_HEAP_DUMP_POLICY,
        "file": filename,
        "sha256": sha256_file(host_path),
        "sizeBytes": host_path.stat().st_size,
        "jcmdOutput": diagnostic_file(label, "heap-dump-command", output),
    }


def benchmark_provider(provider: str, benchmark_name: str, request: dict,
                       fork: int = 1, block: int = 1,
                       order_position: int = 1) -> dict:
    restart_clean()
    clean_all_apps()
    provider_log_baseline = docker_logs()
    baseline = snapshot(f"{benchmark_name}-process-baseline", archive_details=True)
    started_at = dt.datetime.now(dt.timezone.utc)
    run_environment = server_info()
    cycles = []
    for cycle_no in range(1, CYCLES + 1):
        cycle_request = dict(request)
        cycle_request["seed"] = paired_request_seed(
            int(request["seed"]), SCHEDULE_SEED, block, cycle_no
        )
        cycle_baseline = snapshot(
            f"{benchmark_name}-{cycle_no}-baseline", archive_details=True
        )
        deploy_ms = deploy(provider)
        idle = snapshot(f"{benchmark_name}-{cycle_no}-deployed-idle")
        workload, protocol_validation = execute_workload(
            provider, cycle_request, "initial-deploy"
        )
        loaded = snapshot(f"{benchmark_name}-{cycle_no}-loaded")
        first_undeploy_log_baseline = docker_logs()
        undeploy_ms = undeploy(provider)
        first_diagnostics = post_undeploy_snapshot(
            f"{benchmark_name}-{cycle_no}-after-undeploy",
            first_undeploy_log_baseline,
        )
        after_first_early = first_diagnostics["earlyThreadObservation"]
        after_first = first_diagnostics["finalObservation"]
        first_log_lines = appended_log_lines(first_undeploy_log_baseline, docker_logs())
        first_warnings, first_leaks, first_thread_leaks = classified_warnings(first_log_lines)
        redeploy_ms = deploy(provider)
        status, info_body = http(f"{BASE}/{provider}/api/info")
        redeploy_ready = status == 200 and json.loads(info_body).get("provider") == provider
        redeploy_workload, redeploy_validation = execute_workload(
            provider, cycle_request, "redeploy"
        )
        redeployed_loaded = snapshot(f"{benchmark_name}-{cycle_no}-redeployed-loaded")
        second_undeploy_log_baseline = docker_logs()
        second_undeploy_ms = undeploy(provider)
        final_diagnostics = post_undeploy_snapshot(
            f"{benchmark_name}-{cycle_no}-after-final-undeploy",
            second_undeploy_log_baseline,
        )
        after_final_early = final_diagnostics["earlyThreadObservation"]
        after_final = final_diagnostics["finalObservation"]
        second_log_lines = appended_log_lines(second_undeploy_log_baseline, docker_logs())
        second_warnings, second_leaks, second_thread_leaks = classified_warnings(second_log_lines)
        first_reported_context = f"/{provider}" in after_first["tomcatFindLeaksContexts"]
        final_reported_context = f"/{provider}" in after_final["tomcatFindLeaksContexts"]
        final_new_threads = new_thread_records(cycle_baseline, after_final)
        final_candidate_threads = candidate_application_threads(final_new_threads)
        cycle = {
            "cycle": cycle_no,
            "requestSeed": cycle_request["seed"],
            "request": cycle_request,
            "deployMs": deploy_ms,
            "undeployMs": undeploy_ms,
            "redeployMs": redeploy_ms,
            "secondUndeployMs": second_undeploy_ms,
            "redeployReady": redeploy_ready,
            "redeployWorkloadPassed": redeploy_validation["passed"],
            "redeployPassed": redeploy_ready and redeploy_validation["passed"],
            "baseline": cycle_baseline,
            "deployedIdle": idle,
            "loaded": loaded,
            "afterUndeployEarly": after_first_early,
            "afterUndeploy": after_first,
            "firstUndeployTiming": first_diagnostics["timing"],
            "redeployedLoaded": redeployed_loaded,
            "afterFinalUndeployEarly": after_final_early,
            "afterFinalUndeploy": after_final,
            "finalUndeployTiming": final_diagnostics["timing"],
            "cacheHeapDeltaBytes": max(0, loaded["heapUsedBytes"] - idle["heapUsedBytes"]),
            "retainedHeapBytes": after_final["heapUsedBytes"] - cycle_baseline["heapUsedBytes"],
            "finalClassloaderCountAtOrBelowCycleBaseline": (
                after_final["webappClassloaderCount"]
                <= cycle_baseline["webappClassloaderCount"]
            ),
            "tomcatFindLeaksTargetContextObservedAfterFirstUndeploy": first_reported_context,
            "tomcatFindLeaksTargetContextObservedAfterFinalUndeploy": final_reported_context,
            "finalThreadCountAtOrBelowCycleBaseline": (
                after_final["liveThreadCount"] <= cycle_baseline["liveThreadCount"]
            ),
            "firstUndeployThreadEvidenceEarly": thread_evidence(
                baseline, cycle_baseline, after_first_early
            ),
            "firstUndeployThreadEvidenceFinal": thread_evidence(
                baseline, cycle_baseline, after_first
            ),
            "finalUndeployThreadEvidenceEarly": thread_evidence(
                baseline, cycle_baseline, after_final_early
            ),
            "finalUndeployThreadEvidenceFinal": thread_evidence(
                baseline, cycle_baseline, after_final
            ),
            "threadsNotPresentAtCycleBaseline": final_new_threads,
            "candidateApplicationThreadsAfterFinalUndeploy": final_candidate_threads,
            "noCandidateApplicationThreadSignalAfterFinalUndeploy": (
                not final_candidate_threads
                and not first_thread_leaks and not second_thread_leaks
            ),
            "firstUndeployWarnings": first_warnings,
            "firstUndeployLeakWarnings": first_leaks,
            "firstUndeployThreadLeakWarnings": first_thread_leaks,
            "secondUndeployWarnings": second_warnings,
            "secondUndeployLeakWarnings": second_leaks,
            "secondUndeployThreadLeakWarnings": second_thread_leaks,
            "protocolValidation": protocol_validation,
            "redeployProtocolValidation": redeploy_validation,
            "workload": workload,
            "redeployWorkload": redeploy_workload,
        }
        cycles.append(cycle)
        print(
            f"{benchmark_name} cycle {cycle_no}/{CYCLES}: "
            f"{workload['operationsPerSecond']:.0f} ops/s; "
            f"redeploy semantic gate={'passed' if redeploy_validation['passed'] else 'failed'}"
        )
    logs = docker_logs()
    provider_log_lines = appended_log_lines(provider_log_baseline, logs)
    warning_lines, leak_lines, thread_leak_lines = classified_warnings(provider_log_lines)
    diagnostic_file(benchmark_name, "tomcat-log", "\n".join(provider_log_lines) + "\n")
    diagnostic_signal_observed = any(
        not cycle["protocolValidation"]["passed"]
        or not cycle["redeployProtocolValidation"]["passed"]
        or not cycle["redeployReady"]
        or cycle["tomcatFindLeaksTargetContextObservedAfterFirstUndeploy"]
        or cycle["tomcatFindLeaksTargetContextObservedAfterFinalUndeploy"]
        or bool(cycle["finalUndeployThreadEvidenceFinal"]["jcsThreadSignatures"])
        for cycle in cycles
    ) or bool(thread_leak_lines)
    heap_dump = maybe_final_heap_dump(benchmark_name, provider, diagnostic_signal_observed)
    return {
        "processRunId": benchmark_name,
        "provider": provider,
        "engineProvider": provider,
        "fork": fork,
        "block": block,
        "orderPosition": order_position,
        "configuration": request,
        "scheduleSeed": SCHEDULE_SEED,
        "startedAt": started_at.isoformat(),
        "finishedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "environment": run_environment,
        "processBaseline": baseline,
        "cycles": cycles,
        "warnings": warning_lines,
        "leakWarnings": leak_lines,
        "threadLeakWarnings": thread_leak_lines,
        "finalHeapDump": heap_dump,
    }


def median_cycle(provider: dict, path: tuple[str, ...], cycles: list[dict] | None = None) -> float:
    values = []
    for cycle in cycles if cycles is not None else provider["cycles"]:
        value = cycle
        for key in path:
            value = value[key]
        values.append(float(value))
    return statistics.median(values)


def linear_slope(values: list[float | int | None]) -> float | None:
    points = [(float(index + 1), float(value)) for index, value in enumerate(values)
              if value is not None]
    if not points:
        return None
    if len(points) == 1:
        return 0.0
    xbar = statistics.mean(x for x, _ in points)
    ybar = statistics.mean(y for _, y in points)
    denominator = sum((x - xbar) ** 2 for x, _ in points)
    if not denominator:
        return 0.0
    return sum((x - xbar) * (y - ybar) for x, y in points) / denominator


PERFORMANCE_FIELDS = {
    "operationsPerSecond": "operationsPerSecond",
    "readOperationsPerSecond": "readOperationsPerSecond",
    "fillOperationsPerSecond": "fillOperationsPerSecond",
    "latencyP50Nanos": "latencyP50Nanos",
    "latencyP95Nanos": "latencyP95Nanos",
    "latencyP99Nanos": "latencyP99Nanos",
    "measuredLatencySamples": "measuredLatencySamples",
}


def phase_observation(process_run: dict, cycle: dict, phase: str) -> dict:
    redeploy = phase == "redeploy"
    workload = cycle["redeployWorkload"] if redeploy else cycle["workload"]
    validation = (
        cycle["redeployProtocolValidation"] if redeploy else cycle["protocolValidation"]
    )
    final = cycle["afterFinalUndeploy"] if redeploy else cycle["afterUndeploy"]
    early = cycle["afterFinalUndeployEarly"] if redeploy else cycle["afterUndeployEarly"]
    diagnostic_timing = (
        cycle.get("finalUndeployTiming", {})
        if redeploy else cycle.get("firstUndeployTiming", {})
    )
    metrics_after_workload, metrics_after_write_probe = provider_metric_checkpoints(workload)
    warning_key = "secondUndeployThreadLeakWarnings" if redeploy else "firstUndeployThreadLeakWarnings"
    target_context = f"/{process_run['provider']}"
    row = {
        "processRunId": process_run["processRunId"],
        "scenario": process_run.get("scenario", "default"),
        "provider": process_run["provider"],
        "fork": process_run["fork"],
        "block": process_run["block"],
        "orderPosition": process_run["orderPosition"],
        "cycle": cycle["cycle"],
        "phase": phase,
        "requestSeed": cycle["requestSeed"],
        "semanticGateType": validation["gateType"],
        "semanticGatePassed": validation["passed"],
        "performanceComparisonEligible": validation["performanceComparisonEligible"],
        "observedHitRate": float(metrics_after_workload.get("hitRate", 0.0)),
        "observedEntriesAfterWorkload": int(
            metrics_after_workload.get("currentEntries", 0)
        ),
        "observedEntriesAfterWriteProbe": int(
            metrics_after_write_probe.get("currentEntries", 0)
        ),
        # Compatibility alias retained with its historical post-write meaning.
        "observedEntries": int(metrics_after_write_probe.get("currentEntries", 0)),
        "singleFlightPassed": bool(workload.get("singleFlightPassed", False)),
        "postUndeployHeapUsedBytes": final.get("heapUsedBytes"),
        "postUndeployNativeCommittedBytes": final.get("nativeCommittedBytes"),
        "postUndeployWebappClassloaderCount": final.get("webappClassloaderCount"),
        "postUndeployLiveThreadCount": final.get("liveThreadCount"),
        "earlyJcsThreadSignatureCount": len(early.get("jcsThreadSignatures", [])),
        "finalJcsThreadSignatureCount": len(final.get("jcsThreadSignatures", [])),
        "tomcatFindLeaksOccurrenceCount": final.get("tomcatFindLeaksOccurrenceCount", 0),
        "tomcatFindLeaksTargetContextCount": final.get(
            "tomcatFindLeaksOccurrenceCountsByContext", {}
        ).get(target_context, 0),
        "threadLeakWarningCount": len(cycle.get(warning_key, [])),
    }
    for timing_field in (
        "earlyThreadTargetSecondsAfterUndeploy",
        "finalDiagnosticTargetSecondsAfterUndeploy",
        "earlyThreadStartedSecondsAfterUndeploy",
        "earlyThreadCompletedSecondsAfterUndeploy",
        "finalDiagnosticStartedSecondsAfterUndeploy",
        "findLeaksCompletedSecondsAfterUndeploy",
        "finalSnapshotCompletedSecondsAfterUndeploy",
    ):
        row[timing_field] = diagnostic_timing.get(timing_field)
    for output_name, source_name in PERFORMANCE_FIELDS.items():
        value = workload.get(source_name)
        row[output_name] = float(value) if value is not None else None
    write_probe = workload.get("writeProbeOperationsPerSecond")
    row["writeProbeOperationsPerSecond"] = (
        float(write_probe) if write_probe is not None else None
    )
    return row


def absolute_final_slopes(process_run: dict) -> dict:
    finals = [cycle["afterFinalUndeploy"] for cycle in process_run["cycles"]]
    return {
        "absoluteFinalHeapSlopeBytesPerCycle": linear_slope(
            [item.get("heapUsedBytes") for item in finals]
        ),
        "absoluteFinalNativeCommittedSlopeBytesPerCycle": linear_slope(
            [item.get("nativeCommittedBytes") for item in finals]
        ),
        "absoluteFinalWebappClassloaderSlopePerCycle": linear_slope(
            [item.get("webappClassloaderCount") for item in finals]
        ),
        "absoluteFinalLiveThreadSlopePerCycle": linear_slope(
            [item.get("liveThreadCount") for item in finals]
        ),
        "absoluteFinalHeapFirstBytes": finals[0].get("heapUsedBytes") if finals else None,
        "absoluteFinalHeapLastBytes": finals[-1].get("heapUsedBytes") if finals else None,
        "absoluteFinalNativeCommittedFirstBytes": (
            finals[0].get("nativeCommittedBytes") if finals else None
        ),
        "absoluteFinalNativeCommittedLastBytes": (
            finals[-1].get("nativeCommittedBytes") if finals else None
        ),
        "absoluteFinalWebappClassloaderFirst": (
            finals[0].get("webappClassloaderCount") if finals else None
        ),
        "absoluteFinalWebappClassloaderLast": (
            finals[-1].get("webappClassloaderCount") if finals else None
        ),
        "absoluteFinalLiveThreadFirst": finals[0].get("liveThreadCount") if finals else None,
        "absoluteFinalLiveThreadLast": finals[-1].get("liveThreadCount") if finals else None,
    }


def fork_analysis_rows(process_run: dict, observations: list[dict],
                       block_valid: bool = True) -> list[dict]:
    rows = []
    for analysis_set, omit_cycle_one in (("primary-all-cycles", False),
                                          ("sensitivity-without-cycle-1", True)):
        for phase in ("initial", "redeploy"):
            selected = [
                observation for observation in observations
                if observation["processRunId"] == process_run["processRunId"]
                and observation["phase"] == phase
                and (not omit_cycle_one or observation["cycle"] != 1)
            ]
            semantic_passed = bool(selected) and all(
                observation["semanticGatePassed"] for observation in selected
            )
            comparison_eligible = bool(selected) and all(
                observation["performanceComparisonEligible"] for observation in selected
            )
            row = {
                "processRunId": process_run["processRunId"],
                "scenario": process_run.get("scenario", "default"),
                "provider": process_run["provider"],
                "fork": process_run["fork"],
                "block": process_run["block"],
                "orderPosition": process_run["orderPosition"],
                "phase": phase,
                "analysisSet": analysis_set,
                "cycleObservationCount": len(selected),
                "blockValid": block_valid,
                "semanticGatePassed": semantic_passed,
                "performanceComparisonEligible": comparison_eligible,
                "includedInPerformanceSummary": (
                    block_valid and semantic_passed and comparison_eligible
                ),
                "redeployReadyAllCycles": all(
                    cycle.get("redeployReady", False) for cycle in process_run["cycles"]
                ),
            }
            for field in PERFORMANCE_FIELDS:
                observed_values = [
                    float(observation[field]) for observation in selected
                    if observation.get(field) is not None
                ]
                observed_median = statistics.median(observed_values) if observed_values else None
                row[f"observedMedian_{field}"] = observed_median
                row[f"comparisonMedian_{field}"] = (
                    observed_median if row["includedInPerformanceSummary"] else None
                )
            rows.append(row)
    return rows


def lifecycle_analysis_row(process_run: dict, block_valid: bool = True) -> dict:
    target_context = f"/{process_run['provider']}"
    first_target_observations = sum(
        int(target_context in cycle["afterUndeploy"].get("tomcatFindLeaksContexts", []))
        for cycle in process_run["cycles"]
    )
    final_target_observations = sum(
        int(target_context in cycle["afterFinalUndeploy"].get("tomcatFindLeaksContexts", []))
        for cycle in process_run["cycles"]
    )
    first_warning_count = sum(
        len(cycle.get("firstUndeployThreadLeakWarnings", []))
        for cycle in process_run["cycles"]
    )
    final_warning_count = sum(
        len(cycle.get("secondUndeployThreadLeakWarnings", []))
        for cycle in process_run["cycles"]
    )
    signature_count = sum(
        len(cycle[evidence].get("jcsThreadSignatures", []))
        for cycle in process_run["cycles"]
        for evidence in (
            "firstUndeployThreadEvidenceEarly",
            "firstUndeployThreadEvidenceFinal",
            "finalUndeployThreadEvidenceEarly",
            "finalUndeployThreadEvidenceFinal",
        )
    )
    corroborated_intervals = []
    for cycle in process_run["cycles"]:
        for phase, early_evidence, final_evidence, warnings_key in (
            (
                "first-undeploy",
                "firstUndeployThreadEvidenceEarly",
                "firstUndeployThreadEvidenceFinal",
                "firstUndeployThreadLeakWarnings",
            ),
            (
                "final-undeploy",
                "finalUndeployThreadEvidenceEarly",
                "finalUndeployThreadEvidenceFinal",
                "secondUndeployThreadLeakWarnings",
            ),
        ):
            signatures = (
                cycle[early_evidence].get("jcsThreadSignatures", [])
                + cycle[final_evidence].get("jcsThreadSignatures", [])
            )
            warnings = cycle.get(warnings_key, [])
            if signatures and warnings:
                corroborated_intervals.append({
                    "cycle": cycle["cycle"],
                    "phase": phase,
                    "signatureObservationCount": len(signatures),
                    "threadLeakWarningCount": len(warnings),
                })
    return {
        "processRunId": process_run["processRunId"],
        "scenario": process_run.get("scenario", "default"),
        "provider": process_run["provider"],
        "fork": process_run["fork"],
        "block": process_run["block"],
        "orderPosition": process_run["orderPosition"],
        "blockValid": block_valid,
        "cycleCount": len(process_run["cycles"]),
        "redeployReadyAllCycles": all(
            cycle.get("redeployReady", False) for cycle in process_run["cycles"]
        ),
        "firstUndeployTargetFindleaksObservationCount": first_target_observations,
        "finalUndeployTargetFindleaksObservationCount": final_target_observations,
        "targetFindleaksObservationCount": (
            first_target_observations + final_target_observations
        ),
        "firstUndeployThreadLeakWarningCount": first_warning_count,
        "finalUndeployThreadLeakWarningCount": final_warning_count,
        "threadLeakWarningCount": first_warning_count + final_warning_count,
        "jcsThreadSignatureObservationCount": signature_count,
        "jcsThreadSignatureObserved": signature_count > 0,
        "jcs248CorroboratedUndeployCount": len(corroborated_intervals),
        "jcs248CorroboratedIntervals": corroborated_intervals,
        "jcs248CorroboratedSignalObserved": bool(corroborated_intervals),
        **absolute_final_slopes(process_run),
    }


def interpolated_quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def descriptive(values: list[float], prefix: str) -> dict:
    if not values:
        return {
            f"{prefix}N": 0, f"{prefix}Median": None, f"{prefix}Mean": None,
            f"{prefix}SampleStandardDeviation": None,
            f"{prefix}FirstQuartile": None, f"{prefix}ThirdQuartile": None,
            f"{prefix}Minimum": None, f"{prefix}Maximum": None,
        }
    return {
        f"{prefix}N": len(values),
        f"{prefix}Median": statistics.median(values),
        f"{prefix}Mean": statistics.mean(values),
        f"{prefix}SampleStandardDeviation": statistics.stdev(values)
        if len(values) > 1 else None,
        f"{prefix}FirstQuartile": interpolated_quantile(values, 0.25),
        f"{prefix}ThirdQuartile": interpolated_quantile(values, 0.75),
        f"{prefix}Minimum": min(values),
        f"{prefix}Maximum": max(values),
    }


def detect_invalid_blocks(raw: dict) -> list[dict]:
    """Identify Williams blocks that cannot contribute to any analysis."""
    reasons: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for failure in raw.get("infrastructureFailures", []):
        key = (failure.get("scenario", "default"), int(failure["block"]))
        reasons[key].append({
            "type": "infrastructure-failure",
            "processRunId": failure.get("processRunId"),
            "message": failure.get("message"),
        })

    execution_plan = raw.get("executionPlan", [])
    if execution_plan:
        planned: dict[tuple[str, int], set[str]] = collections.defaultdict(set)
        completed: dict[tuple[str, int], set[str]] = collections.defaultdict(set)
        for item in execution_plan:
            planned[(item.get("scenario", "default"), int(item["block"]))].add(
                item["processRunId"]
            )
        for item in raw.get("processRuns", []):
            completed[(item.get("scenario", "default"), int(item["block"]))].add(
                item["processRunId"]
            )
        for key, planned_ids in planned.items():
            missing = sorted(planned_ids - completed.get(key, set()))
            unexpected = sorted(completed.get(key, set()) - planned_ids)
            if missing:
                reasons[key].append({"type": "missing-process-runs", "ids": missing})
            if unexpected:
                reasons[key].append({"type": "unexpected-process-runs", "ids": unexpected})

    return [
        {"scenario": scenario, "block": block, "reasons": block_reasons}
        for (scenario, block), block_reasons in sorted(reasons.items())
    ]


def analyse(raw: dict) -> dict:
    process_runs = raw.get("processRuns", raw.get("providers", []))
    invalid_blocks = detect_invalid_blocks(raw)
    invalid_block_keys = {
        (item["scenario"], item["block"]) for item in invalid_blocks
    }
    observations = [
        phase_observation(process_run, cycle, phase)
        for process_run in process_runs
        for cycle in process_run["cycles"]
        for phase in ("initial", "redeploy")
    ]
    forks = [
        row for process_run in process_runs
        for row in fork_analysis_rows(
            process_run,
            observations,
            (process_run.get("scenario", "default"), process_run["block"])
            not in invalid_block_keys,
        )
    ]
    lifecycle_forks = [
        lifecycle_analysis_row(
            process_run,
            (process_run.get("scenario", "default"), process_run["block"])
            not in invalid_block_keys,
        )
        for process_run in process_runs
    ]
    for observation in observations:
        observation["blockValid"] = (
            observation["scenario"], observation["block"]
        ) not in invalid_block_keys
    group_keys = sorted({
        (row["scenario"], row["provider"], row["phase"], row["analysisSet"])
        for row in forks
    })
    summaries = []
    for scenario, provider, phase, analysis_set in group_keys:
        rows = [
            row for row in forks
            if (row["scenario"], row["provider"], row["phase"], row["analysisSet"])
            == (scenario, provider, phase, analysis_set)
        ]
        valid_rows = [row for row in rows if row["blockValid"]]
        included = [row for row in valid_rows if row["includedInPerformanceSummary"]]
        summary = {
            "scenario": scenario,
            "provider": provider,
            "phase": phase,
            "analysisSet": analysis_set,
            "statisticalUnit": "independent-process-run-fork",
            "forkCount": len(valid_rows),
            "observedForkCount": len(rows),
            "invalidBlockForkCount": len(rows) - len(valid_rows),
            "semanticGatePassForkCount": sum(
                row["semanticGatePassed"] for row in valid_rows
            ),
            "studyRole": ({
                "jcs321": "JCS-248-positive-control",
                "nostore": "lifecycle-negative-control",
            }).get(provider, "current-provider-primary-comparison"),
            "performanceComparisonEligible": provider in PRIMARY_PERFORMANCE_PROVIDERS,
            "performanceIncludedForkCount": len(included),
        }
        for field in PERFORMANCE_FIELDS:
            values = [
                float(row[f"comparisonMedian_{field}"]) for row in included
                if row.get(f"comparisonMedian_{field}") is not None
            ]
            summary.update(descriptive(values, field))
        summaries.append(summary)
    lifecycle_summaries = []
    lifecycle_group_keys = sorted({
        (row["scenario"], row["provider"]) for row in lifecycle_forks
    })
    for scenario, provider in lifecycle_group_keys:
        observed_rows = [
            row for row in lifecycle_forks
            if (row["scenario"], row["provider"]) == (scenario, provider)
        ]
        valid_rows = [row for row in observed_rows if row["blockValid"]]
        summary = {
            "scenario": scenario,
            "provider": provider,
            "statisticalUnit": "independent-process-run-fork",
            "forkCount": len(valid_rows),
            "observedForkCount": len(observed_rows),
            "invalidBlockForkCount": len(observed_rows) - len(valid_rows),
            "studyRole": ({
                "jcs321": "JCS-248-positive-control",
                "nostore": "lifecycle-negative-control",
            }).get(provider, "current-provider-primary-comparison"),
            "redeployReadyForkCount": sum(
                row["redeployReadyAllCycles"] for row in valid_rows
            ),
            "forksWithTargetFindleaksObservation": sum(
                row["targetFindleaksObservationCount"] > 0 for row in valid_rows
            ),
            "forksWithThreadLeakWarning": sum(
                row["threadLeakWarningCount"] > 0 for row in valid_rows
            ),
            "forksWithJcsThreadSignature": sum(
                row["jcsThreadSignatureObserved"] for row in valid_rows
            ),
            "forksWithJcs248CorroboratedSignal": sum(
                row["jcs248CorroboratedSignalObserved"] for row in valid_rows
            ),
        }
        summary["jcs248PositiveControlCriterionMet"] = (
            provider == "jcs321"
            and len(valid_rows) == 6
            and summary["forksWithJcs248CorroboratedSignal"] >= 5
        )
        for field in (
            "targetFindleaksObservationCount",
            "threadLeakWarningCount",
            "jcsThreadSignatureObservationCount",
            "absoluteFinalHeapSlopeBytesPerCycle",
            "absoluteFinalNativeCommittedSlopeBytesPerCycle",
            "absoluteFinalWebappClassloaderSlopePerCycle",
            "absoluteFinalLiveThreadSlopePerCycle",
        ):
            values = [
                float(row[field]) for row in valid_rows if row.get(field) is not None
            ]
            summary.update(descriptive(values, field))
        lifecycle_summaries.append(summary)
    paired_ratios = []
    reference_rows = {
        (row["scenario"], row["block"], row["phase"], row["analysisSet"]): row
        for row in forks
        if row["provider"] == "jcs4" and row["includedInPerformanceSummary"]
    }
    ratio_groups: dict[tuple[str, str, str, str], list[dict]] = collections.defaultdict(list)
    for row in forks:
        if (row["provider"] not in PRIMARY_PERFORMANCE_PROVIDERS
                or row["provider"] == "jcs4"
                or not row["includedInPerformanceSummary"]):
            continue
        reference = reference_rows.get((
            row["scenario"], row["block"], row["phase"], row["analysisSet"]
        ))
        numerator = row.get("comparisonMedian_operationsPerSecond")
        denominator = reference.get("comparisonMedian_operationsPerSecond") if reference else None
        if numerator is None or denominator in {None, 0}:
            continue
        ratio_groups[(row["scenario"], row["provider"], row["phase"],
                      row["analysisSet"])].append({
            "block": row["block"],
            "ratioToJcs4": float(numerator) / float(denominator),
        })
    for (scenario, provider, phase, analysis_set), values in sorted(ratio_groups.items()):
        ratios = [value["ratioToJcs4"] for value in values]
        paired_ratios.append({
            "scenario": scenario,
            "provider": provider,
            "referenceProvider": "jcs4",
            "phase": phase,
            "analysisSet": analysis_set,
            "pairingUnit": "Williams block",
            "ratioMetric": "operationsPerSecond",
            "valuesByBlock": values,
            **descriptive(ratios, "ratioToJcs4"),
        })
    return {
        "schemaVersion": 4,
        "protocolVersion": PROTOCOL_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "statisticalUnit": "independent process run (fork); cycles are repeated observations",
        "primaryAnalysis": "all configured cycles, including cycle 1",
        "sensitivityAnalysis": "same fork-level summaries after omitting cycle 1",
        "performanceExclusions": {
            "jcs321": "JCS-248 positive control; analysed separately from current providers",
            "nostore": "negative lifecycle control; no cache semantics and no performance comparison",
            "semanticGateFailure": "run retained in observations but excluded from performance summary",
            "invalidBlock": "all runs in a Williams block are retained but excluded after an infrastructure failure or incomplete block",
        },
        "invalidBlocks": invalid_blocks,
        "rankingProduced": False,
        "summaries": summaries,
        "forks": forks,
        "lifecycleSummaries": lifecycle_summaries,
        "lifecycleForks": lifecycle_forks,
        "observations": observations,
        "pairedRatios": paired_ratios,
    }


def atomic_write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        atomic_write_text(path, "")
        return
    fields = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_text(path, "\ufeff" + buffer.getvalue())


def write_csv(analysis: dict) -> None:
    for suffix, key in (("summary", "summaries"), ("forks", "forks"),
                        ("observations", "observations"),
                        ("lifecycle-summary", "lifecycleSummaries"),
                        ("lifecycle-forks", "lifecycleForks")):
        atomic_write_csv(OUT / f"{RESULT_PREFIX}-{suffix}.csv", analysis[key])


def request_variants() -> list[tuple[str, dict]]:
    variants = []
    expanded = len(THREAD_MATRIX) * len(HIT_MATRIX) * len(WORKLOADS) * len(JCS_MODES) > 1
    for mode in JCS_MODES:
        for threads in THREAD_MATRIX:
            for hit_percent in HIT_MATRIX:
                for workload in WORKLOADS:
                    request = dict(REQUEST)
                    request.update({
                        "threads": threads,
                        "hitPercent": hit_percent,
                        "workload": workload,
                        "jcsMemoryMode": mode,
                    })
                    name = "default" if not expanded else (
                        f"{mode}-t{threads}-h{hit_percent}-{workload}"
                    )
                    variants.append((name, request))
    return variants


def benchmark_matrix() -> list[tuple[str, str, dict]]:
    """Compatibility view of the configured treatments before Williams ordering."""
    return [
        (provider, provider if scenario == "default" else f"{provider}-{scenario}", request)
        for scenario, request in request_variants()
        for provider in PROVIDERS
    ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if EARLY_DIAGNOSTIC_SECONDS > FINAL_DIAGNOSTIC_SECONDS:
        raise ValueError(
            "early diagnostic delay must not exceed the final diagnostic delay"
        )
    try:
        preflight = preflight_environment()
    except Exception as failure:
        failure_record = {
            "schemaVersion": 4,
            "protocolVersion": PROTOCOL_VERSION,
            "campaignLabel": RESULT_PREFIX,
            "failedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stage": "campaign-preflight",
            "errorType": type(failure).__name__,
            "message": str(failure),
            "configuration": REQUEST,
        }
        if DIAGNOSTIC_DIRECTORY.exists():
            temporary_base = OUT / f".{RESULT_PREFIX}-preflight-diagnostics-{os.getpid()}"
            temporary_archive = Path(shutil.make_archive(
                str(temporary_base), "zip", root_dir=DIAGNOSTIC_DIRECTORY
            ))
            final_archive = OUT / f"{RESULT_PREFIX}-preflight-diagnostics.zip"
            os.replace(temporary_archive, final_archive)
            failure_record["diagnosticArchive"] = {
                "file": final_archive.name,
                "sha256": sha256_file(final_archive),
                "sizeBytes": final_archive.stat().st_size,
            }
        atomic_write_json(
            OUT / f"{RESULT_PREFIX}-preflight-failure.json", failure_record
        )
        print(f"campaign preflight failure: {failure}")
        return 2
    schedule = williams_schedule()
    variants = request_variants()
    execution_plan = []
    for scenario, _ in variants:
        for row in schedule:
            for position, provider in enumerate(row["order"], 1):
                run_id = f"{RESULT_PREFIX}-{scenario}-f{row['fork']:02d}-p{position}-{provider}"
                execution_plan.append({
                    "processRunId": run_id,
                    "scenario": scenario,
                    "provider": provider,
                    "fork": row["fork"],
                    "block": row["block"],
                    "williamsRow": row["williamsRow"],
                    "orderPosition": position,
                    "pairedRequestSeedsByCycle": {
                        str(cycle): paired_request_seed(
                            int(REQUEST["seed"]), SCHEDULE_SEED, row["block"], cycle
                        )
                        for cycle in range(1, CYCLES + 1)
                    },
                })
    frozen_design = PROVIDERS == CANONICAL_PROVIDERS
    raw = {
        "schemaVersion": 4,
        "protocolVersion": PROTOCOL_VERSION,
        "campaignStartedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "configuration": REQUEST,
        "matrix": {"threads": THREAD_MATRIX, "hitPercent": HIT_MATRIX,
                   "workloads": WORKLOADS, "jcsMemoryModes": JCS_MODES},
        "providers": list(PROVIDERS),
        "forks": FORKS,
        "cyclesPerProcessRun": CYCLES,
        "schedule": {
            "design": ("frozen canonical Williams 6x6" if frozen_design
                       else "cyclic subset (diagnostic only)"),
            "canonicalProviderMapping": dict(zip("ABCDEF", CANONICAL_PROVIDERS)),
            "canonicalRows": [
                [CANONICAL_PROVIDERS[index] for index in row] for row in WILLIAMS_ROWS
            ],
            "selectedProviders": list(PROVIDERS),
            "rowsAreShuffled": False,
            "scheduleSeed": SCHEDULE_SEED,
            "workloadBaseSeed": int(REQUEST["seed"]),
            "scheduleSeedPurpose": (
                "campaign pairing salt and manifest identity; "
                "the frozen row order is not shuffled"
            ),
            "forkRows": schedule,
        },
        "executionPlan": execution_plan,
        "lifecycleProtocol": {
            "freshContainerPerProcessRun": True,
            "composeRecreateFlag": "--force-recreate",
            "redeployExecutesSameSeededFullWorkload": True,
            "earlyThreadObservationSeconds": EARLY_DIAGNOSTIC_SECONDS,
            "finalObservationAndFindleaksSeconds": FINAL_DIAGNOSTIC_SECONDS,
            "earlyThreadTargetSecondsAfterUndeploy": EARLY_DIAGNOSTIC_SECONDS,
            "finalDiagnosticTargetSecondsAfterUndeploy": FINAL_DIAGNOSTIC_SECONDS,
            "finalDiagnosticTargetIsMinimumStart": True,
            "diagnosticTimingOrigin": (
                "monotonic elapsed time starting immediately after undeploy returned"
            ),
            "forcedGcCountPerFinalSnapshot": 2,
            "forcedGcAtBaselineIdleOrLoadedSnapshots": False,
            "findleaksOccurrencesPreserved": True,
            "finalHeapDumpPolicy": FINAL_HEAP_DUMP_POLICY,
            "archivedAfterEveryUndeploy": [
                "early Thread.print", "early Tomcat log",
                "Tomcat Manager findleaks",
                "GC.heap_info (after two forced GC.run commands)",
                "VM.classloader_stats", "final Thread.print",
                "VM.native_memory summary", "GC.class_histogram",
            ],
            "finalDiagnosticCommandOrder": [
                "Tomcat Manager findleaks", "GC.run", "GC.run",
                "GC.heap_info", "VM.classloader_stats", "Thread.print",
                "VM.native_memory summary", "GC.class_histogram",
            ],
        },
        "campaignPreflight": preflight,
        "sourceProvenance": source_provenance(),
        "processRuns": [],
        "infrastructureFailures": [],
    }
    partial_path = OUT / f"{RESULT_PREFIX}-raw.partial.json"
    atomic_write_json(partial_path, raw)
    requests_by_scenario = dict(variants)
    for planned in execution_plan:
        request = requests_by_scenario[planned["scenario"]]
        try:
            result = benchmark_provider(
                planned["provider"], planned["processRunId"], request,
                fork=planned["fork"], block=planned["block"],
                order_position=planned["orderPosition"],
            )
            result["scenario"] = planned["scenario"]
            result["williamsRow"] = planned["williamsRow"]
            raw["processRuns"].append(result)
        except Exception as failure:
            raw["infrastructureFailures"].append({
                **planned,
                "failedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "errorType": type(failure).__name__,
                "message": str(failure),
            })
            print(f"infrastructure failure in {planned['processRunId']}: {failure}")
        raw["lastCheckpointAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_write_json(partial_path, raw)
    temporary_base = OUT / f".{RESULT_PREFIX}-diagnostics-{os.getpid()}"
    temporary_archive = Path(shutil.make_archive(
        str(temporary_base), "zip", root_dir=DIAGNOSTIC_DIRECTORY
    ))
    final_archive = OUT / f"{RESULT_PREFIX}-diagnostics.zip"
    os.replace(temporary_archive, final_archive)
    raw["diagnosticArchive"] = {
        "file": final_archive.name,
        "sha256": sha256_file(final_archive),
        "sizeBytes": final_archive.stat().st_size,
    }
    raw["campaignFinishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    raw["invalidBlocks"] = detect_invalid_blocks(raw)
    analysis = analyse(raw)
    analysis_path = OUT / f"{RESULT_PREFIX}-analysis.json"
    atomic_write_json(analysis_path, analysis)
    raw["analysisFile"] = analysis_path.name
    raw["analysisSha256"] = sha256_file(analysis_path)
    atomic_write_json(OUT / f"{RESULT_PREFIX}-results.json", raw)
    write_csv(analysis)
    print(
        f"Completed {len(raw['processRuns'])}/{len(execution_plan)} independent process runs; "
        f"infrastructure failures: {len(raw['infrastructureFailures'])}"
    )
    return 1 if raw["infrastructureFailures"] else 0


if __name__ == "__main__":
    sys.exit(main())

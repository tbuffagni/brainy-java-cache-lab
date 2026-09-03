[CmdletBinding()]
param(
    [ValidateSet('all', 'caffeine', 'ehcache', 'cache2k', 'jcs4', 'jcs321', 'nostore')]
    [string]$Provider = 'all',

    [ValidateRange(1, 100)]
    [int]$Cycles = 5,

    [ValidateRange(1, 30)]
    [int]$Forks = 6,

    [ValidateRange(0.25, 64.0)]
    [double]$DockerCpus = 4.0,

    [ValidatePattern('^[0-9]+[kKmMgG]$')]
    [string]$DockerMemory = '1536m',

    [string]$TomcatImage = 'tomcat:11.0.24-jdk25-temurin-noble@sha256:6d673ad42da6498f05755cae67f85f2128bdfd88943c9bdb22e0965f8d4c3182',
    [string]$BuildImage = 'maven:3.9.11-eclipse-temurin-25@sha256:407c4423cec0cf2981055bc2c6c0dc211d9605b6669279b95997f2d1c7e91e2c',
    [string]$JvmOptions = '-Xms256m -Xmx768m -XX:+UseG1GC -XX:NativeMemoryTracking=summary -Djava.awt.headless=true',

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$CampaignLabel = 'article1-unified-v4-2',

    # Retained only to give users of the v3 command an actionable error.
    [Parameter(DontShow)]
    [string]$JcsLine,

    [ValidateRange(100, 100000)]
    [int]$Entries = 10000,

    # Size of the deterministic operation plan, replayed for the timed window.
    [ValidateRange(1000, 10000000)]
    [int]$Operations = 400000,

    [ValidateRange(1, 128)]
    [int]$Threads = 8,

    [ValidateRange(0, 100)]
    [int]$HitPercent = 95,

    [ValidateRange(16, 65536)]
    [int]$PayloadBytes = 512,

    [ValidateRange(0.1, 60.0)]
    [double]$WarmupSeconds = 3.0,

    [ValidateRange(0.1, 60.0)]
    [double]$MeasurementSeconds = 5.0,

    [ValidateRange(1, 3600)]
    [int]$TtlSeconds = 300,

    [ValidateSet('uniform', 'zipf', 'scan', 'mixed', 'expiry')]
    [string]$Workload = 'uniform',

    [ValidateRange(0, 100)]
    [int]$WritePercent = 10,

    [long]$Seed = 24301,
    [long]$ScheduleSeed = 2482026,

    [ValidateRange(1, 65536)]
    [int]$LatencySampleRate = 64,

    [ValidateRange(0, 300)]
    [double]$EarlyDiagnosticSettleSeconds = 2.0,

    [ValidateRange(0, 900)]
    [double]$FinalDiagnosticSettleSeconds = 10.0,

    [ValidateSet('none', 'jcs', 'all')]
    [string]$HeapDumpPolicy = 'jcs',

    [string]$PythonExecutable,

    [switch]$SkipBuild,
    [switch]$NoBuildCache,
    [switch]$KeepContainer
)

$ErrorActionPreference = 'Stop'

if ($PSBoundParameters.ContainsKey('JcsLine')) {
    throw '-JcsLine was retired in protocol v4.2. The unified WAR contains both implementations; use -Provider jcs4 or -Provider jcs321.'
}
if ($SkipBuild -and $NoBuildCache) {
    throw '-SkipBuild and -NoBuildCache cannot be used together.'
}
if ($SkipBuild) {
    throw '-SkipBuild is disabled for protocol v4.2 because an image label cannot prove that the current harness sources produced the WAR. Docker build caching remains available.'
}
if ($EarlyDiagnosticSettleSeconds -gt $FinalDiagnosticSettleSeconds) {
    throw '-EarlyDiagnosticSettleSeconds must be less than or equal to -FinalDiagnosticSettleSeconds.'
}

$invariantCulture = [System.Globalization.CultureInfo]::InvariantCulture
$pressDirectory = $PSScriptRoot
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $pressDirectory '..')).Path
$composeFile = (Resolve-Path -LiteralPath (Join-Path $pressDirectory 'benchmark\docker-compose.yml')).Path
$resultDirectory = Join-Path $pressDirectory 'results\raw'
$outputDirectory = Join-Path $repositoryRoot 'output\data'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$jcs4Version = '4.0.0-SNAPSHOT'
$jcs4Coordinates = 'org.apache.commons:commons-jcs4-core:4.0.0-SNAPSHOT'
$jcs321Version = '3.2.1'
$jcs321Coordinates = 'org.apache.commons:commons-jcs3-core:3.2.1'
$jcs321Sha256 = '12c6fe08223820089f60969b6088e6ac5d358aa872de78357585cdacb6c61049'
$expectedJcsRevision = 'fb3f101b87709b713468e8d827b8612e6e65f29b'
$jcsSourceDirectory = (Resolve-Path -LiteralPath (Join-Path $repositoryRoot 'vendor\commons-jcs4-main')).Path
$jcsSafeDirectory = $jcsSourceDirectory.Replace('\', '/')

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required to identify the vendored JCS 4 revision.'
}
$jcsRevisionOutput = & git -c "safe.directory=$jcsSafeDirectory" -C $jcsSourceDirectory rev-parse HEAD
$gitRevisionExitCode = $LASTEXITCODE
$jcsRevision = if ($null -eq $jcsRevisionOutput) { '' } else { "$jcsRevisionOutput".Trim() }
if ($gitRevisionExitCode -ne 0 -or $jcsRevision -notmatch '^[0-9a-f]{40}$') {
    throw 'Unable to determine the pinned JCS 4 source commit.'
}
if ($jcsRevision -ne $expectedJcsRevision) {
    throw "The frozen v4.2 protocol requires JCS 4 commit '$expectedJcsRevision'; the checkout is '$jcsRevision'."
}
$jcsChanges = @(& git -c "safe.directory=$jcsSafeDirectory" -C $jcsSourceDirectory status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to determine whether the vendored JCS 4 source tree is clean.'
}
if ($jcsChanges.Count -gt 0) {
    throw "vendor/commons-jcs4-main has uncommitted or untracked files. A publication run requires an exact, clean revision.`n$($jcsChanges -join [Environment]::NewLine)"
}

$revisionLabel = $jcsRevision.Substring(0, 8)
$resultPrefix = "$CampaignLabel-$revisionLabel-$timestamp"
$buildLog = Join-Path $outputDirectory "$resultPrefix-build.log"
$benchmarkImage = if ($env:CACHE_BENCH_IMAGE) {
    $env:CACHE_BENCH_IMAGE
} else {
    'testcache-benchmark:v4'
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)][string[]]$ComposeArguments,
        [string]$LogPath
    )

    # Windows PowerShell 5 converts native stderr records into non-terminating
    # errors. Docker BuildKit normally writes progress there, so temporarily
    # keep those records flowing to Tee-Object and decide from the native exit
    # code instead of treating ordinary progress as a script failure.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($script:composeKind -eq 'legacy') {
            if ($LogPath) {
                & $script:composeExecutable -f $composeFile @ComposeArguments 2>&1 |
                    Tee-Object -FilePath $LogPath
            } else {
                & $script:composeExecutable -f $composeFile @ComposeArguments
            }
        } else {
            if ($LogPath) {
                & $script:composeExecutable compose -f $composeFile @ComposeArguments 2>&1 |
                    Tee-Object -FilePath $LogPath
            } else {
                & $script:composeExecutable compose -f $composeFile @ComposeArguments
            }
        }
        $composeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($composeExitCode -ne 0) {
        throw "Docker Compose failed with exit code $composeExitCode."
    }
}

function Copy-CampaignArtifacts {
    Get-ChildItem -LiteralPath $outputDirectory -Filter "$resultPrefix*" -File -ErrorAction SilentlyContinue |
        Copy-Item -Destination $resultDirectory -Force
}

function Assert-BenchmarkImageProvenance {
    $imageInspectOutput = & docker image inspect $benchmarkImage
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect benchmark image '$benchmarkImage'."
    }
    $imageInspect = @($imageInspectOutput | ConvertFrom-Json)
    if ($imageInspect.Count -ne 1) {
        throw "Docker returned an unexpected image inspection result for '$benchmarkImage'."
    }
    $imageRevision = $imageInspect[0].Config.Labels.'org.opencontainers.image.revision.jcs4'
    if ($imageRevision -ne $jcsRevision) {
        throw "Benchmark image '$benchmarkImage' contains JCS 4 commit '$imageRevision', expected '$jcsRevision'. Rebuild it without -SkipBuild."
    }
}

function Import-And-InspectPinnedBaseImage {
    param(
        [Parameter(Mandatory = $true)][string]$Reference,
        [Parameter(Mandatory = $true)][string]$Role
    )

    if ($Reference -notmatch '@sha256:[0-9a-fA-F]{64}$') {
        throw "$Role base image '$Reference' is not pinned by an immutable sha256 digest."
    }

    # BuildKit can consume a remote base image without importing it into the
    # Docker image store queried by `docker image inspect`.  Prefer an existing
    # local object; otherwise pull the exact digest before any build or run.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $inspectOutput = & docker image inspect $Reference 2>$null
        $inspectExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($inspectExitCode -ne 0) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & docker pull $Reference
            $pullExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($pullExitCode -ne 0) {
            throw "Unable to pull the pinned $Role base image '$Reference'."
        }

        $inspectOutput = & docker image inspect $Reference
        $inspectExitCode = $LASTEXITCODE
    }

    if ($inspectExitCode -ne 0) {
        throw "Unable to inspect the pinned $Role base image '$Reference' after pulling it."
    }
    $inspect = @($inspectOutput | ConvertFrom-Json)
    if ($inspect.Count -ne 1) {
        throw "Docker returned an unexpected inspection result for the pinned $Role base image '$Reference'."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required but was not found on PATH.'
}

$legacyCompose = Get-Command docker-compose -ErrorAction SilentlyContinue
if ($legacyCompose) {
    $script:composeKind = 'legacy'
    $script:composeExecutable = $legacyCompose.Source
    $env:CACHE_BENCH_COMPOSE_CMD = 'docker-compose'
} else {
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose is required (`docker compose` or `docker-compose`).'
    }
    $script:composeKind = 'plugin'
    $script:composeExecutable = (Get-Command docker).Source
    $env:CACHE_BENCH_COMPOSE_CMD = 'docker compose'
}

$pythonLauncher = $null
$pythonArguments = @()
if ($PythonExecutable) {
    $pythonLauncher = (Resolve-Path -LiteralPath $PythonExecutable).Path
} else {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        & $pyCommand.Source -3 --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $pythonLauncher = $pyCommand.Source
            $pythonArguments = @('-3')
        }
    }
    if (-not $pythonLauncher) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            & $pythonCommand.Source --version 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $pythonLauncher = $pythonCommand.Source
            }
        }
    }
    if (-not $pythonLauncher) {
        throw 'A working Python 3 interpreter is required. Install Python or pass -PythonExecutable with its full path.'
    }
}

$env:COMPOSE_FILE = $composeFile
$env:CACHE_BENCH_COMPOSE_FILE = $composeFile
$env:CACHE_BENCH_DOCKER_CPUS = $DockerCpus.ToString($invariantCulture)
$env:CACHE_BENCH_DOCKER_MEMORY = $DockerMemory
$env:CACHE_BENCH_TOMCAT_IMAGE = $TomcatImage
$env:CACHE_BENCH_BUILD_IMAGE = $BuildImage
$env:CACHE_BENCH_DOCKERFILE = 'press/benchmark/Dockerfile'
$env:CACHE_BENCH_JCS4_VERSION = $jcs4Version
$env:CACHE_BENCH_JCS4_COMMIT = $jcsRevision
$env:CACHE_BENCH_JCS4_COORDINATES = $jcs4Coordinates
$env:CACHE_BENCH_JCS321_VERSION = $jcs321Version
$env:CACHE_BENCH_JCS321_COORDINATES = $jcs321Coordinates
$env:CACHE_BENCH_JCS321_SHA256 = $jcs321Sha256
# Compatibility metadata for v3 readers. Protocol v4 records both explicit lines above.
$env:CACHE_BENCH_JCS_VERSION = $jcs4Version
$env:CACHE_BENCH_JCS_COMMIT = $jcsRevision
$env:CACHE_BENCH_JCS_COORDINATES = $jcs4Coordinates
$env:CACHE_BENCH_JAVA_OPTS = $JvmOptions
$env:CACHE_BENCH_PROVIDERS = if ($Provider -eq 'all') {
    'caffeine,ehcache,cache2k,jcs4,jcs321,nostore'
} else {
    $Provider
}
$env:CACHE_BENCH_CYCLES = $Cycles.ToString($invariantCulture)
$env:CACHE_BENCH_FORKS = $Forks.ToString($invariantCulture)
$env:CACHE_BENCH_RESULT_PREFIX = $resultPrefix
$env:CACHE_BENCH_JCS_MODE = 'strict'
$env:CACHE_BENCH_ENTRIES = $Entries.ToString($invariantCulture)
$env:CACHE_BENCH_OPERATIONS = $Operations.ToString($invariantCulture)
$env:CACHE_BENCH_THREADS = $Threads.ToString($invariantCulture)
$env:CACHE_BENCH_WARMUP_OPERATIONS = '50000'
$env:CACHE_BENCH_HIT_PERCENT = $HitPercent.ToString($invariantCulture)
$env:CACHE_BENCH_PAYLOAD_BYTES = $PayloadBytes.ToString($invariantCulture)
$env:CACHE_BENCH_WARMUP_SECONDS = $WarmupSeconds.ToString($invariantCulture)
$env:CACHE_BENCH_MEASUREMENT_SECONDS = $MeasurementSeconds.ToString($invariantCulture)
$env:CACHE_BENCH_TTL_SECONDS = $TtlSeconds.ToString($invariantCulture)
$env:CACHE_BENCH_WORKLOAD = $Workload
$env:CACHE_BENCH_WRITE_PERCENT = $WritePercent.ToString($invariantCulture)
$env:CACHE_BENCH_SEED = $Seed.ToString($invariantCulture)
$env:CACHE_BENCH_SCHEDULE_SEED = $ScheduleSeed.ToString($invariantCulture)
$env:CACHE_BENCH_LATENCY_SAMPLE_RATE = $LatencySampleRate.ToString($invariantCulture)
$env:CACHE_BENCH_EARLY_DIAGNOSTIC_SETTLE_SECONDS = $EarlyDiagnosticSettleSeconds.ToString($invariantCulture)
$env:CACHE_BENCH_FINAL_DIAGNOSTIC_SETTLE_SECONDS = $FinalDiagnosticSettleSeconds.ToString($invariantCulture)
$env:CACHE_BENCH_HEAP_DUMP_POLICY = $HeapDumpPolicy
# Pin the single-condition matrix explicitly so inherited CACHE_BENCH_* variables
# cannot silently expand or alter a publication run.
$env:CACHE_BENCH_THREAD_MATRIX = $Threads.ToString($invariantCulture)
$env:CACHE_BENCH_HIT_MATRIX = $HitPercent.ToString($invariantCulture)
$env:CACHE_BENCH_WORKLOADS = $Workload
$env:CACHE_BENCH_JCS_MODES = 'strict'
# Allows the v4 Python runner to recreate every JVM without invoking a hidden build.
$env:CACHE_BENCH_COMPOSE_UP_ARGS = '--no-build --force-recreate'

$env:DOCKER_BUILDKIT = '1'
$env:BUILDKIT_PROGRESS = 'plain'

New-Item -ItemType Directory -Force -Path $resultDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

Push-Location $repositoryRoot
try {
    Import-And-InspectPinnedBaseImage -Reference $TomcatImage -Role 'runtime'
    Import-And-InspectPinnedBaseImage -Reference $BuildImage -Role 'build'

    if (-not $SkipBuild) {
        $buildArguments = @('build')
        if ($NoBuildCache) {
            $buildArguments += '--no-cache'
        }
        Invoke-Compose -ComposeArguments $buildArguments -LogPath $buildLog
        Copy-CampaignArtifacts
    } else {
        "Build skipped by -SkipBuild at $(Get-Date -Format o)." |
            Set-Content -LiteralPath $buildLog -Encoding utf8
    }

    Assert-BenchmarkImageProvenance

    # The runner repeats this form before every fork, guaranteeing a new JVM
    # while preventing Compose from rebuilding between measured processes.
    Invoke-Compose -ComposeArguments @('up', '-d', '--no-build', '--force-recreate')

    & $pythonLauncher @pythonArguments 'scripts\run_benchmark.py'
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark runner failed with exit code $LASTEXITCODE."
    }

    Copy-CampaignArtifacts
    Write-Host "Completed. Results copied to $resultDirectory" -ForegroundColor Green
} finally {
    Copy-CampaignArtifacts
    if (-not $KeepContainer) {
        Invoke-Compose -ComposeArguments @('stop')
    }
    Pop-Location
}

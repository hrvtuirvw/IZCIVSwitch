# run-p4-once.ps1 -- one P4 attempt: restore save -> start engine -> send bridge -> wait -> summarize.
# Usage (run from this kit directory):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-p4-once.ps1 -ConsoleIp <S2-IP> -PcIp <PC-IP> [-SkipRestore] [-FirmwareDump] [-SdProbe <probe.cjs>] [-CanaryRetry] [-LaunchExperiment -LaunchTitle <0x…> [-LaunchStart]]
#
# Standard cycle (see README.md §6):
#   1) loader online -> run WITHOUT -SkipRestore (rewrites trigger save)
#   2) hard power-cycle the console, Load Game, back to Awaiting payload
#   3) run WITH -SkipRestore  (and -FirmwareDump if you want the system dump)
#
# -SdProbe <script.cjs>: while the engine runs, watch the run's fs-execution-current.json
#   and the incremental reserved-gap report; when memoryControl.ready becomes true,
#   run the probe against its socketPath once. Probe results land in <root>\sd-probe-results\.
param(
  [Parameter(Mandatory = $true)][string]$ConsoleIp,
  [Parameter(Mandatory = $true)][string]$PcIp,
  [string]$Backup = '',
  [switch]$SkipRestore,
  [switch]$FirmwareDump,
  [switch]$CanaryRetry,
  [string]$SdProbe = '',
  [switch]$LaunchExperiment,
  [string]$LaunchTitle = '',
  [switch]$LaunchStart
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$port = Join-Path $root 'port'
$send = Join-Path $root 'save-tools\send_js.py'
$restore = Join-Path $root 'save-tools\restore_save.py'
$bridge = Join-Path $port 'civ_bridge.js'
if (-not $Backup) { $Backup = Join-Path $root 'save-tools\trigger-recreate' }

$node = (Get-Command node -ErrorAction Stop).Source
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction Stop).Source }

# RUN 92: send_js.py crashed while printing loader text containing non-ANSI characters (the
# traceback hit $ErrorActionPreference='Stop' and killed this script right after the bridge
# was sent, so the engine was left unsupervised). Force UTF-8 stdio for python tools.
$env:PYTHONIOENCODING = 'utf-8'

# Persistent run log (the engine stdout/stderr go to GUID temp files that are lost after the
# run, and the sd-probe step output only lived in the job transcript -- RUN 90 could not be
# reconstructed because neither was kept).
$runLog = Join-Path $root ('run-logs\p4-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.log')
function Write-RunLog([string]$message) {
  try {
    $dir = Split-Path -Parent $runLog
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    ('{0} {1}' -f (Get-Date -Format 'HH:mm:ss'), $message) | Add-Content -Path $runLog -Encoding UTF8
  } catch { }
}

# make sure the bridge knows where to dial out
$bridgeText = Get-Content $bridge -Raw
if ($bridgeText -match "'<PC_IP>'") {
  throw "civ_bridge.js PC_IP not set yet -- run: .\set-pc-ip.ps1 -PcIp $PcIp"
}

Write-Output '=== 1/3 restore save ==='
if ($SkipRestore) {
  Write-Output '(skipped: -SkipRestore)'
} else {
  & $python -u $restore $Backup $ConsoleIp 2>&1 | Select-Object -Last 3
}

Write-Output '=== 2/3 start engine ==='
if ($CanaryRetry) {
  $env:CANARY_MISS_RETRY = '1'
  Write-Output '(canary-miss same-boot retry: ENABLED)'
}
# PROCESS-ESCAPE-PLAN stage A (opt-in): launch-title override experiment.
if ($LaunchExperiment) {
  if (-not ($LaunchTitle -match '^0x[0-9a-fA-F]{16}$')) {
    throw '-LaunchExperiment requires -LaunchTitle <0x + 16 hex digits>'
  }
  $env:NS2_LAUNCH_TITLE = $LaunchTitle
  $env:NS2_LAUNCH_EXPERIMENT = '1'
  if ($LaunchStart) { $env:NS2_LAUNCH_START = '1' }
  Write-Output "(launch experiment: title=$LaunchTitle start=$($LaunchStart -as [bool]))"
}
if ($FirmwareDump) {
  $env:NS2_FIRMWARE_DUMP_DIR = Join-Path $port 'engine\dumps'
  Write-Output "(firmware dump dir: $env:NS2_FIRMWARE_DUMP_DIR)"
  $engineArgs = @('engine\run.cjs', '--dump-firmware', $PcIp)
} else {
  $engineArgs = @('engine\run.cjs', $PcIp)
}
$outLog = Join-Path $env:TEMP ('p4-engine-out-' + [guid]::NewGuid().ToString('N') + '.log')
$errLog = Join-Path $env:TEMP ('p4-engine-err-' + [guid]::NewGuid().ToString('N') + '.log')
$engine = Start-Process -FilePath $node -ArgumentList $engineArgs -WorkingDirectory $port `
  -PassThru -NoNewWindow -RedirectStandardOutput $outLog -RedirectStandardError $errLog

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 250
  if ((Test-Path $outLog) -and (Select-String -Path $outLog -Pattern 'Run folder:' -Quiet -ErrorAction SilentlyContinue)) { break }
  if ($engine.HasExited) { break }
}
Get-Content $outLog -ErrorAction SilentlyContinue | Select-Object -Last 3

Write-Output '=== 3/3 send bridge ==='
$sendLines = @()
$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
  $sendLines = @(& $python -u $send $ConsoleIp $bridge 2>&1 | Select-Object -Last 6)
} catch {
  $sendLines = @('send_js.py threw: ' + $_.Exception.Message)
} finally {
  $ErrorActionPreference = $previousEap
}
$sendLines | ForEach-Object { Write-Output ([string]$_) }
foreach ($line in $sendLines) { Write-RunLog ('bridge send: ' + [string]$line) }

Write-Output '=== engine waiting ==='
if ($SdProbe) {
  $probeOut = Join-Path $root 'sd-probe-results'
  $probeDone = $false
  $runDir = ''
  while (-not $engine.HasExited) {
    Start-Sleep -Milliseconds 1000
    if ($probeDone) { continue }
    $m = Get-Content $outLog -ErrorAction SilentlyContinue | Select-String -Pattern 'Run folder: (.+)$' | Select-Object -Last 1
    if ($m) { $runDir = $m.Matches[0].Groups[1].Value.Trim() }
    if (-not $runDir) { continue }
    $sock = ''
    $fsExec = Join-Path $runDir 'switch2\fs-execution-current.json'
    if (Test-Path $fsExec) {
      try {
        $fsj = Get-Content $fsExec -Raw | ConvertFrom-Json
        if ($fsj.memoryControl.ready -and $fsj.memoryControl.socketPath) { $sock = [string]$fsj.memoryControl.socketPath }
      } catch { }
    }
    if (-not $sock) {
      # RUN 90 fix: current-acquisition.json carries the live TCP socketPath as soon as
      # acquisition reaches phase=retained. On a clean run the reserved-gap report is only
      # rewritten at the end (memoryControl.ready is false by then) and fs-execution-current.json
      # has no memoryControl section, so without this source the probe never fires.
      $acq = Join-Path $runDir 'switch2\current-acquisition.json'
      if (Test-Path $acq) {
        try {
          $aj = Get-Content $acq -Raw | ConvertFrom-Json
          $candidate = [string]$aj.socketPath
          if ($candidate -match '^127\.0\.0\.1:\d+$') { $sock = $candidate }
        } catch { }
      }
    }
    if (-not $sock) {
      # slapah pipeline writes fs-execution-current.json only on --hold-rpc / final release,
      # so poll the incremental reserved-gap report instead (it carries memoryControl while
      # the memory socket is live during 3/4 find-metadata).
      $memDir = Join-Path $runDir 'switch2\memory'
      $reports = Get-ChildItem $memDir -Filter 'reserved-gap-*.json' -ErrorAction SilentlyContinue |
                 Where-Object { $_.Name -notmatch '\.tmp$' } |
                 Sort-Object LastWriteTime -Descending
      foreach ($rp in $reports) {
        try {
          $rj = Get-Content $rp.FullName -Raw | ConvertFrom-Json
          if ($rj.memoryControl -and $rj.memoryControl.ready -and $rj.memoryControl.socketPath) {
            $sock = [string]$rj.memoryControl.socketPath
            break
          }
        } catch { }
      }
    }
    if ($sock) {
      # Gate: only probe once ro/install-retained has COMPLETED (RUN 67 fix).
      #  (1) the root clone handle that sd-probe needs only exists after ro/install-retained
      #      (RUN 62: gating on find-metadata fired the probe too early -> 'no root clone handle');
      #  (2) find-metadata completes BEFORE install-retained, so the old find-metadata gate fired
      #      the probe straight into install-retained's memory activity (RUN 67: probe's 3s busy
      #      window exhausted 0.126s before install-retained finished -> 'Another memory request
      #      is active'). The probe's busy window is now 120s (sd-probe.cjs) to ride out any
      #      residual contention from the 4/4 FS demo.
      $stageOk = $false
      $pj = Join-Path $runDir 'switch2\pipeline.json'
      if (Test-Path $pj) {
        try {
          $pjo = Get-Content $pj -Raw | ConvertFrom-Json
          foreach ($st in $pjo.stages) {
            if ($st.name -eq 'ro/install-retained' -and ($st.status -eq 'complete' -or ($st.result -and $st.result.verified))) { $stageOk = $true }
          }
        } catch { }
      }
      if (-not $stageOk) { continue }
      Write-RunLog ('probe firing: sock=' + $sock + ' runDir=' + $runDir)
      Write-Output '=== sd probe (install-retained complete) ==='
      Start-Sleep -Seconds 2
      $probeLines = & $node $SdProbe $sock $probeOut 2>&1 | Select-Object -Last 8
      $probeLines
      foreach ($pl in $probeLines) { Write-RunLog ('probe: ' + [string]$pl) }
      Write-RunLog 'probe finished'
      $probeDone = $true
    }
  }
} else {
  $engine.WaitForExit()
}
Write-Output ('engine exit=' + $engine.ExitCode)
if ($SdProbe) {
  if ($probeDone) { Write-RunLog 'probe ran during this attempt' } else { Write-RunLog 'probe never fired before engine exit' }
}
Get-Content $outLog -ErrorAction SilentlyContinue | Select-Object -Last 12
$errText = Get-Content $errLog -ErrorAction SilentlyContinue
if ($errText) { Write-Output '--- stderr ---'; $errText | Select-Object -Last 6 }

Write-Output '=== summary ==='
$run = (Get-Content $outLog -ErrorAction SilentlyContinue | Select-String -Pattern 'Run folder: (.+)$' | Select-Object -Last 1)
if ($run) {
  $runDir = $run.Matches[0].Groups[1].Value.Trim()
  Write-Output ('run=' + $runDir)
  $res = Join-Path $runDir 'result.json'
  if (Test-Path $res) {
    $r = Get-Content $res -Raw | ConvertFrom-Json
    Write-Output ('verified=' + $r.verified + ' error=' + $r.error)
  }
  $pipe = Join-Path $runDir 'switch2\pipeline.json'
  if (Test-Path $pipe) {
    $p = Get-Content $pipe -Raw | ConvertFrom-Json
    foreach ($s in $p.stages) { Write-Output ('stage ' + $s.name + ' : ' + $s.status) }
  }
}

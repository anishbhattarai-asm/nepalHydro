# CLI smoke test for Windows: runs the Solu Khola commands from the Step 6 check
# and fails (exit 1) on any mismatch. Works in PowerShell 7 (pwsh) and Windows
# PowerShell 5.1 (powershell), so: no &&, no ternaries, ASCII only.
#
#   pwsh -File scripts/cli_smoke.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/cli_smoke.ps1

# Native commands write warnings to stderr; that must not stop the script.
$ErrorActionPreference = 'Continue'
$script:failures = 0

function Check([bool]$ok, [string]$what) {
    if ($ok) { Write-Host "ok    $what" }
    else { Write-Host "FAIL  $what"; $script:failures++ }
}

Write-Host "PowerShell $($PSVersionTable.PSVersion) ($($PSVersionTable.PSEdition))"
$solu = @('--area', '330', '--a5000', '308.5', '--a3000', '97.7', '--mwi', '1500',
          '--region', '3', '--q', '2.8', '--month', '4')
$warny = @('--area', '2', '--a5000', '2', '--a3000', '1', '--mwi', '1500',
           '--region', '4', '--q', '1', '--month', '4')

# 1. Table output
$table = nepal-hydro all @solu | Out-String
Check ($LASTEXITCODE -eq 0) 'table: exit code 0'
foreach ($v in @('426.06', '98.45', '2.03', '43.86', '16.68', '70.00', '21.12', 'm3/s', 'licensed engineer')) {
    Check ($table.Contains($v)) "table: contains $v"
}
Write-Host $table

# 2. JSON piped into Python, rebuilt with result_from_dict
#    Windows PowerShell 5.1 puts a UTF-8 BOM in front of text it pipes into another
#    program (seen in CI: b'\xef\xbb\xbf{...', whatever $OutputEncoding says), so the
#    reader decodes with utf-8-sig, which drops a BOM if present. pwsh 7 adds none.
$py = 'import json,sys; from nepal_hydro import result_from_dict as r; d=json.loads(sys.stdin.buffer.read().decode(''utf-8-sig'')); print(sorted(type(r(v)).__name__ for v in d.values()))'
$peek = 'import sys; print(repr(sys.stdin.buffer.read()[:8]))'
$raw = nepal-hydro all @solu --format json 2>$null | python -c $peek | Out-String
Write-Host "first bytes Python receives through the pipe: $($raw.Trim())"
$types = nepal-hydro all @solu --format json 2>$null | python -c $py | Out-String
Check ($LASTEXITCODE -eq 0) 'json pipe: python exit code 0'
Check ($types.Trim() -eq "['FloodPeaks', 'FlowDurationCurve', 'MonthlyComparison', 'MonthlyFlows', 'MonthlyFlows']") "json pipe: five results rebuilt ($($types.Trim()))"

# 3. PYTHONIOENCODING=cp1252, with warnings on stderr too
$env:PYTHONIOENCODING = 'cp1252'
$t = nepal-hydro all @solu | Out-String
Check ($LASTEXITCODE -eq 0) 'cp1252: table exit code 0'
Check ($t.Contains('426.06')) 'cp1252: table contains 426.06'
$both = nepal-hydro all @warny 2>&1 | ForEach-Object { "$_" } | Out-String
Check ($LASTEXITCODE -eq 0) 'cp1252: run with warnings exit code 0'
Check ($both.Contains('km2')) 'cp1252: warning text uses km2'
Remove-Item Env:PYTHONIOENCODING

# 4. chcp 437 + csv. In CI stdout is a pipe, where Python does not use the console
#    code page, so the run is repeated with PYTHONIOENCODING=cp437 to force it.
chcp 437 | Out-Null
foreach ($forced in @($false, $true)) {
    if ($forced) { $env:PYTHONIOENCODING = 'cp437' }
    $csv = nepal-hydro all @warny --format csv 2>$null | Out-String
    Check ($LASTEXITCODE -eq 0) "cp437 (forced=$forced): csv exit code 0"
    Check ($csv.Contains('month,wecs_m3s,mip_m3s,ratio_mip_over_wecs')) "cp437 (forced=$forced): csv has the comparison header"
    Check ($csv.Contains('# flood_peaks')) "cp437 (forced=$forced): csv has sections"
    if ($forced) { Remove-Item Env:PYTHONIOENCODING }
}
chcp 65001 | Out-Null

# 5. Warnings go to stderr only
nepal-hydro mip --region 4 --q 1 --month 4 --format csv > out.csv
Check ($LASTEXITCODE -eq 0) 'stderr-only: exit code 0'
$lines = @(Get-Content out.csv)
Check ($lines[0] -eq 'month,q_m3s') 'stderr-only: file starts with the CSV header'
Check ($lines.Count -eq 13) "stderr-only: file has 13 lines ($($lines.Count))"
Check (-not (($lines -join "`n") -match 'warning')) 'stderr-only: no warning text in the file'
Remove-Item out.csv
#    ...and byte-exact, without PowerShell in between:
$exe = (Get-Command nepal-hydro).Source
$p = Start-Process -FilePath $exe -ArgumentList 'mip', '--region', '4', '--q', '1', '--month', '4', '--format', 'csv' `
    -NoNewWindow -Wait -PassThru -RedirectStandardOutput o.txt -RedirectStandardError e.txt
$o = [IO.File]::ReadAllText((Resolve-Path o.txt))
$e = [IO.File]::ReadAllText((Resolve-Path e.txt))
Check ($p.ExitCode -eq 0) 'stderr-only (raw): exit code 0'
Check ($o.StartsWith('month,q_m3s')) 'stderr-only (raw): stdout is CSV'
Check (-not $o.Contains('warning')) 'stderr-only (raw): no warning on stdout'
Check ($e.StartsWith('nepal-hydro: warning: MIP 1982 monthly hydrograph: region 4')) 'stderr-only (raw): warning on stderr'
Remove-Item o.txt, e.txt

# 6. Exit codes
nepal-hydro mip --region 9 --q 1 --month 4 2>$null
Check ($LASTEXITCODE -eq 1) "exit code 1 for invalid input (got $LASTEXITCODE)"
nepal-hydro flood --a3000 x 2>$null
Check ($LASTEXITCODE -eq 2) "exit code 2 for a usage error (got $LASTEXITCODE)"
nepal-hydro all 2>$null
Check ($LASTEXITCODE -eq 1) "exit code 1 when all has nothing to run (got $LASTEXITCODE)"
nepal-hydro all --a3000 97.7 2>$null | Out-Null
Check ($LASTEXITCODE -eq 0) "exit code 0 for a desk study (got $LASTEXITCODE)"

if ($script:failures -gt 0) {
    Write-Host "$($script:failures) check(s) failed"
    exit 1
}
Write-Host 'all CLI checks passed'
exit 0

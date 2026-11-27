<# FRAMATEX sur PostgreSQL 17 local (Windows). Le mode normal utilise la base définitive configurée.
   -Demo utilise obligatoirement une base et un stockage distincts. Aucun Docker, aucun repli SQLite. #>
[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$Demo, [switch]$NoBrowser, [switch]$CheckOnly, [switch]$Reload
)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$configured = Import-FramatexEnv
$database = $configured['FRAMATEX_PG_DATABASE']
$dataDir = $configured['FRAMATEX_DATA_DIR']
if ($Demo) {
    $database = $configured['FRAMATEX_PG_DEMO_DATABASE']
    $dataDir = $configured['FRAMATEX_DEMO_DATA_DIR']
    if (-not $database -or -not $dataDir) {
        throw '-Demo exige FRAMATEX_PG_DEMO_DATABASE et FRAMATEX_DEMO_DATA_DIR dans .env.'
    }
    if ($database -eq $configured['FRAMATEX_PG_DATABASE'] -or $dataDir -eq $configured['FRAMATEX_DATA_DIR']) {
        throw '-Demo refuse la base ou le stockage définitif. Configurez des valeurs de démonstration distinctes.'
    }
}
$values = Import-FramatexEnv -DatabaseOverride $database -DataDirOverride $dataDir
$python = Get-FramatexPython
Start-FramatexPostgres $values
Wait-FramatexPostgres $python
Invoke-FramatexChecked $python @('-m','app.db','upgrade')
Invoke-FramatexChecked $python @('-m','app.db','check')
Write-Host "FRAMATEX démarre sur PostgreSQL (${env:FRAMATEX_PG_HOST}:${env:FRAMATEX_PG_PORT}/${env:FRAMATEX_PG_DATABASE}) ; stockage ${env:FRAMATEX_DATA_DIR}."
$start = @{ Port = $Port }
if ($Demo) { $start.Demo = $true }
if ($NoBrowser) { $start.NoBrowser = $true }
if ($CheckOnly) { $start.CheckOnly = $true }
if ($Reload) { $start.Reload = $true }
& (Join-Path $PSScriptRoot 'start_windows.ps1') @start
exit $LASTEXITCODE

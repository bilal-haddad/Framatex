<# Migration de la base SQLite locale vers PostgreSQL, en trois étapes, jamais automatique :
   1. simulation (aucune écriture) ; 2. transfert après confirmation explicite ; 3. vérification
   complète (données, relations, fichiers, empreintes). La base SQLite d'origine n'est jamais modifiée.
   Arrêter FRAMATEX (Ctrl+C) avant de lancer ce script : aucune écriture ne doit avoir lieu pendant
   le transfert. #>
param([string]$Sqlite = '', [switch]$Replace)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
$python = Get-FramatexPython
if (-not $Sqlite) { $Sqlite = Join-Path $Root 'data\framat.db' }
if (-not (Test-Path -LiteralPath $Sqlite)) { throw "Base SQLite introuvable : $Sqlite" }
$dataDir = if ($env:FRAMATEX_DATA_DIR) { $env:FRAMATEX_DATA_DIR } else { Join-Path $Root 'data' }
Start-FramatexPostgres $values
Wait-FramatexPostgres $python
Write-Host '--- 1/3 Simulation (aucune écriture dans PostgreSQL)'
& $python (Join-Path $PSScriptRoot 'migrate_sqlite_to_postgresql.py') --sqlite $Sqlite --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Simulation : anomalies à traiter (voir le rapport dans data\migration-reports). Aucun transfert effectué.' }
$answer = Read-Host 'Lancer le transfert réel vers PostgreSQL ? Tapez OUI pour confirmer'
if ($answer -cne 'OUI') { Write-Host 'Transfert annulé.'; exit 1 }
Write-Host '--- 2/3 Transfert'
$transfer = @((Join-Path $PSScriptRoot 'migrate_sqlite_to_postgresql.py'), '--sqlite', $Sqlite)
if ($Replace) { $transfer += '--replace' }
& $python @transfer
if ($LASTEXITCODE -ne 0) { throw 'Transfert refusé ou en échec : PostgreSQL inchangé (voir le rapport).' }
Write-Host '--- 3/3 Vérification d''intégrité'
& $python (Join-Path $PSScriptRoot 'verify_postgresql_migration.py') --sqlite $Sqlite --files-dir $dataDir
if ($LASTEXITCODE -ne 0) { throw 'Vérification : anomalies détectées. Ne pas utiliser PostgreSQL avant analyse ; SQLite reste intact.' }
Write-Host 'Migration vérifiée. Démarrer désormais avec scripts\start_postgresql_windows.cmd.'

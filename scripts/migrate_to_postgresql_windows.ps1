<# Bascule définitive et non destructive SQLite -> PostgreSQL 17 local.
   La configuration active n'est modifiée qu'après sauvegarde, simulation, confirmation,
   transfert transactionnel, vérification complète et sauvegarde PostgreSQL restaurée avec succès. #>
[CmdletBinding()]
param(
    [string]$Sqlite = 'D:\Bilal\Downloads\bilaaaal\Framatex\data\framat.db',
    [string]$SourceData = 'D:\Bilal\Downloads\bilaaaal\Framatex\data',
    [string]$TargetData = 'D:\Bilal\Downloads\bilaaaal\Framatex-pg-data',
    [string]$BackupDest = 'D:\Bilal\Downloads\bilaaaal\Framatex-pre-cutover-backups',
    [string]$TargetDatabase = 'framatex'
)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$python = Get-FramatexPython
if (-not (Test-Path -LiteralPath $Sqlite)) { throw "Base SQLite introuvable : $Sqlite" }
if (-not (Test-Path -LiteralPath $SourceData -PathType Container)) { throw "Stockage source introuvable : $SourceData" }
if ($TargetDatabase -eq 'framatex_test') { throw 'La base framatex_test est réservée à la démonstration.' }
if ([IO.Path]::GetFullPath($SourceData) -eq [IO.Path]::GetFullPath($TargetData)) { throw 'Le stockage cible doit être distinct du stockage SQLite source.' }
if (Test-Path -LiteralPath $TargetData) { throw "Le stockage cible existe déjà : $TargetData. Aucun écrasement automatique." }
$cutover = Join-Path $PSScriptRoot 'postgresql_cutover.py'
$reports = Join-Path $Root 'data\migration-reports'

Write-Host '--- 1/10 Vérification que FRAMATEX est arrêté'
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'assert-server-stopped')

Write-Host '--- 2/10 Contrôle intégral de la source en lecture seule'
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'source-check','--sqlite',$Sqlite,'--source-data',$SourceData)

Write-Host '--- 3/10 Sauvegarde vérifiée de SQLite et des documents'
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'backup-source','--sqlite',$Sqlite,'--source-data',$SourceData,'--dest',$BackupDest)

Write-Host '--- 4/10 Démarrage du service PostgreSQL local'
$configured = Import-FramatexEnv
$maintenanceDatabase = $configured['FRAMATEX_PG_MAINTENANCE_DATABASE']
if (-not $maintenanceDatabase) { $maintenanceDatabase = 'postgres' }
$maintenanceValues = Import-FramatexEnv -DatabaseOverride $maintenanceDatabase
Start-FramatexPostgres $maintenanceValues
Wait-FramatexPostgres $python

Write-Host "--- 5/10 Préparation non destructive de la base vide $TargetDatabase"
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'prepare-target','--database',$TargetDatabase)
$targetValues = Import-FramatexEnv -DatabaseOverride $TargetDatabase
Wait-FramatexPostgres $python

Write-Host '--- 6/10 Simulation (aucune écriture PostgreSQL)'
Invoke-FramatexChecked $python @((Join-Path $PSScriptRoot 'migrate_sqlite_to_postgresql.py'),'--sqlite',$Sqlite,'--dry-run','--report-dir',$reports)
Write-Host "Source : $Sqlite"
Write-Host "Cible  : PostgreSQL/$TargetDatabase"
Write-Host "Fichiers : $SourceData -> $TargetData"
$answer = Read-Host 'Pour lancer la bascule, tapez exactement BASCULER VERS POSTGRESQL'
if ($answer -cne 'BASCULER VERS POSTGRESQL') { throw 'Bascule annulée. La configuration active est inchangée.' }

Write-Host '--- 7/10 Copie vérifiée du stockage vers un dossier neuf'
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'copy-storage','--source-data',$SourceData,'--target-data',$TargetData)
$targetValues = Import-FramatexEnv -DatabaseOverride $TargetDatabase -DataDirOverride $TargetData

Write-Host '--- 8/10 Transfert transactionnel de toutes les tables'
Invoke-FramatexChecked $python @((Join-Path $PSScriptRoot 'migrate_sqlite_to_postgresql.py'),'--sqlite',$Sqlite,'--report-dir',$reports)

Write-Host '--- 9/10 Vérification ligne par ligne, relations, fichiers et SHA-256'
$verifyStarted = Get-Date
Invoke-FramatexChecked $python @((Join-Path $PSScriptRoot 'verify_postgresql_migration.py'),'--sqlite',$Sqlite,'--files-dir',$TargetData,'--report-dir',$reports)
$verification = Get-ChildItem -LiteralPath $reports -Filter 'verification-*.json' |
    Where-Object { $_.LastWriteTime -ge $verifyStarted.AddSeconds(-2) } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $verification) { throw 'Rapport de vérification conforme introuvable : configuration non activée.' }

Write-Host '--- 10/10 Sauvegarde PostgreSQL vérifiée puis activation atomique de .env'
$pgBackup = Join-Path $BackupDest 'postgresql-after-cutover'
Invoke-FramatexChecked $python @((Join-Path $PSScriptRoot 'backup_framatex.py'),'backup','--data-dir',$TargetData,'--dest',$pgBackup,'--keep','14')
Invoke-FramatexChecked $python @($cutover,'--report-dir',$reports,'activate-config','--env-file',(Join-Path $Root '.env'),
    '--database',$TargetDatabase,'--data-dir',$TargetData,'--verification-report',$verification.FullName)
Invoke-FramatexChecked $python @('-m','app.db','check')

Write-Host 'BASCULE VALIDÉE. SQLite reste intacte. Démarrez désormais avec .\scripts\start_windows.cmd.' -ForegroundColor Green

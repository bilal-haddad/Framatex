<# Sauvegarde PostgreSQL + documents, vérifiée par restauration dans une base temporaire.
   pg_dump/pg_restore proviennent de PostgreSQL 17 local ; aucun Docker et aucun repli SQLite. #>
param([string]$Dest = '', [int]$Keep = 14)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
$python = Get-FramatexPython
Start-FramatexPostgres $values
Wait-FramatexPostgres $python
if (-not $Dest) { $Dest = Join-Path $Root 'data\backups' }
$dataDir = if ($env:FRAMATEX_DATA_DIR) { $env:FRAMATEX_DATA_DIR } else { Join-Path $Root 'data' }
& $python (Join-Path $PSScriptRoot 'backup_framatex.py') backup --data-dir $dataDir --dest $Dest --keep $Keep
exit $LASTEXITCODE

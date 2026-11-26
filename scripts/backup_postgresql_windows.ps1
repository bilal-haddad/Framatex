<# Sauvegarde PostgreSQL + documents (scripts/backup_framatex.py), vérifiée par restauration dans une
   base temporaire. pg_dump/pg_restore : ceux du PATH, sinon ceux du conteneur Docker. #>
param([string]$Dest = '', [int]$Keep = 14)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
$python = Get-FramatexPython
if (-not $Dest) { $Dest = Join-Path $Root 'data\backups' }
$dataDir = if ($env:FRAMATEX_DATA_DIR) { $env:FRAMATEX_DATA_DIR } else { Join-Path $Root 'data' }
& $python (Join-Path $PSScriptRoot 'backup_framatex.py') backup --data-dir $dataDir --dest $Dest --keep $Keep
exit $LASTEXITCODE

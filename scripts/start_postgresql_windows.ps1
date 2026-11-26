<# FRAMATEX sur PostgreSQL (Windows). Démarre PostgreSQL (Docker Desktop ou service Windows), attend
   qu'il réponde, applique les migrations de façon contrôlée (un seul processus), puis lance la
   plateforme avec le démarrage habituel (start_windows.ps1, mêmes options : -Demo, -Port, -NoBrowser…).
   La base SQLite existante n'est ni lue ni modifiée : la migration des données est une étape à part
   (migrate_to_postgresql_windows.cmd). #>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$StartArgs)
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
$python = Get-FramatexPython
Start-FramatexPostgres $values
Wait-FramatexPostgres $python
& $python -m app.db upgrade
if ($LASTEXITCODE -ne 0) { throw 'Migration du schéma PostgreSQL en échec (rien n''a été démarré).' }
& $python -m app.db check
if ($LASTEXITCODE -ne 0) { throw 'Vérification du schéma PostgreSQL en échec.' }
Write-Host "FRAMATEX démarre sur PostgreSQL (${env:FRAMATEX_PG_HOST}:${env:FRAMATEX_PG_PORT}/${env:FRAMATEX_PG_DATABASE})."
& (Join-Path $PSScriptRoot 'start_windows.ps1') @StartArgs
exit $LASTEXITCODE

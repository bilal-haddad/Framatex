<# Arrête le conteneur PostgreSQL de FRAMATEX (Docker). Les données restent dans le volume
   « framatex_pgdata ». Mode « local » : le service Windows n'est pas arrêté automatiquement. #>
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
if ($values['FRAMATEX_PG_MODE'] -eq 'docker') {
    & docker compose -f $ComposeFile stop postgres
    if ($LASTEXITCODE -ne 0) { throw 'Arrêt du conteneur impossible.' }
    Write-Host 'PostgreSQL arrêté (données conservées dans le volume framatex_pgdata).'
} else {
    Write-Host 'Mode local : arrêter le service PostgreSQL depuis services.msc si nécessaire.'
}

<# FRAMATEX utilise le service PostgreSQL Windows local. Par sécurité, ce script ne coupe pas
   automatiquement un service qui peut être partagé avec d'autres applications. #>
. (Join-Path $PSScriptRoot 'postgresql_windows_common.ps1')
$values = Import-FramatexEnv
Write-Host "Le service $($values['FRAMATEX_PG_SERVICE']) n'a pas été arrêté. Utilisez services.msc si un arrêt explicite est nécessaire."

<# Fonctions communes PostgreSQL pour Windows PowerShell 5.1+.
   Aucun repli SQLite et aucune dépendance Docker. Le mot de passe reste dans le processus courant. #>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'

function Invoke-FramatexNative([string]$File, [string[]]$Arguments, [switch]$Quiet) {
    # Sous Windows PowerShell 5.1, stderr d'une commande native peut devenir une
    # exception NativeCommandError lorsque ErrorActionPreference vaut Stop.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) { & $File @Arguments 2>$null | Out-Null }
        else { & $File @Arguments | Out-Host }
        $script:FramatexNativeExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return $script:FramatexNativeExit
}

function Invoke-FramatexChecked([string]$File, [string[]]$Arguments) {
    $code = Invoke-FramatexNative $File $Arguments
    if ($code -ne 0) { throw "Commande en echec (code $code). Voir la sortie ci-dessus." }
}

function Import-FramatexEnv([string]$DatabaseOverride = '', [string]$DataDirOverride = '') {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw ".env introuvable. Copier .env.example en .env puis renseigner FRAMATEX_PG_PASSWORD."
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$') { $values[$Matches[1]] = $Matches[2].Trim('"') }
    }
    foreach ($name in 'FRAMATEX_PG_HOST','FRAMATEX_PG_PORT','FRAMATEX_PG_DATABASE','FRAMATEX_PG_USER') {
        if (-not $values[$name]) { throw "$name manquant dans .env" }
    }
    if (-not $values['FRAMATEX_PG_PASSWORD']) { throw 'FRAMATEX_PG_PASSWORD vide dans .env (mot de passe local, au moins 20 caractères).' }
    if (-not $values['FRAMATEX_PG_MODE']) { $values['FRAMATEX_PG_MODE'] = 'local' }
    if ($values['FRAMATEX_PG_MODE'] -ne 'local') {
        throw 'FRAMATEX_PG_MODE doit valoir local. Le demarrage definitif ne depend pas de Docker.'
    }
    if (-not $values['FRAMATEX_PG_SERVICE']) { $values['FRAMATEX_PG_SERVICE'] = 'postgresql-x64-17' }
    if ($DatabaseOverride) { $values['FRAMATEX_PG_DATABASE'] = $DatabaseOverride }
    if ($DataDirOverride) { $values['FRAMATEX_DATA_DIR'] = $DataDirOverride }
    foreach ($key in $values.Keys) {
        if ($key -ne 'FRAMATEX_PG_PASSWORD') { Set-Item -Path "Env:$key" -Value $values[$key] }
    }
    # Mot de passe : variable du processus uniquement, jamais dans l'URL ni dans un journal.
    $env:PGPASSWORD = $values['FRAMATEX_PG_PASSWORD']
    $env:DATABASE_URL = "postgresql+psycopg://$($values['FRAMATEX_PG_USER'])@$($values['FRAMATEX_PG_HOST']):$($values['FRAMATEX_PG_PORT'])/$($values['FRAMATEX_PG_DATABASE'])"
    return $values
}

function Get-FramatexPython {
    $python = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'Creation de l environnement Python local (.venv)...'
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) { Invoke-FramatexChecked $launcher.Source @('-3','-m','venv',(Join-Path $Root '.venv')) }
        else {
            $launcher = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $launcher) { throw 'Python 3.11+ introuvable. Installer Python depuis python.org (option Add to PATH).' }
            Invoke-FramatexChecked $launcher.Source @('-m','venv',(Join-Path $Root '.venv'))
        }
    }
    $probe = Invoke-FramatexNative $python @('-c','import psycopg, alembic') -Quiet
    if ($probe -ne 0) {
        Write-Host 'Installation des dépendances PostgreSQL (psycopg, alembic)...'
        Invoke-FramatexChecked $python @('-m','pip','install','--disable-pip-version-check','-r',(Join-Path $Root 'requirements.txt'))
    }
    Invoke-FramatexChecked $python @('-c','import psycopg, alembic; print("Dependances PostgreSQL : OK")')
    return $python
}

function Start-FramatexPostgres([hashtable]$Values) {
    $serviceName = $Values['FRAMATEX_PG_SERVICE']
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $service) {
        throw "Service PostgreSQL $serviceName introuvable. Verifier PostgreSQL 17 et la valeur FRAMATEX_PG_SERVICE dans .env."
    }
    if ($service.Status -ne 'Running') {
        Write-Host "Demarrage du service $serviceName (droits administrateur parfois necessaires)..."
        Start-Service -Name $serviceName
        $service = Get-Service -Name $serviceName
        if ($service.Status -ne 'Running') { throw "Le service $serviceName n est pas demarre." }
    }
    $pgBin = $Values['FRAMATEX_PG_BIN']
    if (-not $pgBin) {
        $details = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction SilentlyContinue
        if ($details -and $details.PathName -match '"([^\"]+\\pg_ctl\.exe)"') { $pgBin = Split-Path -Parent $Matches[1] }
        elseif ($details -and $details.PathName -match '^(\S+\\pg_ctl\.exe)') { $pgBin = Split-Path -Parent $Matches[1] }
    }
    if ($pgBin -and (Test-Path -LiteralPath $pgBin)) {
        $env:PATH = "$pgBin;$env:PATH"
    }
    Write-Host "Service PostgreSQL : $serviceName ($($service.Status))."
}

function Wait-FramatexPostgres([string]$Python) {
    Invoke-FramatexChecked $Python @((Join-Path $Root 'scripts\wait_for_postgresql.py'),'--timeout','90')
}

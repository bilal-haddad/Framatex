<# Fonctions communes aux scripts PostgreSQL Windows de FRAMATEX (Windows PowerShell 5.1+).
   Lit .env (jamais versionné), prépare DATABASE_URL SANS mot de passe et PGPASSWORD pour le seul
   processus courant, démarre PostgreSQL (Docker Desktop) ou vérifie le service Windows. #>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root 'docker-compose.postgresql.yml'
$EnvFile = Join-Path $Root '.env'

function Import-FramatexEnv {
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
    if (-not $values['FRAMATEX_PG_MODE']) { $values['FRAMATEX_PG_MODE'] = 'docker' }
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
        throw 'Environnement Python absent : lancer une première fois scripts\start_windows.cmd (création de .venv), puis réessayer.'
    }
    & $python -c "import psycopg, alembic" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installation des dépendances PostgreSQL (psycopg, alembic)...'
        & $python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Installation des dépendances impossible.' }
    }
    return $python
}

function Start-FramatexPostgres([hashtable]$Values) {
    if ($Values['FRAMATEX_PG_MODE'] -eq 'docker') {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw 'Docker introuvable. Installer Docker Desktop (voir docs/POSTGRESQL_MIGRATION_REPORT.md) ou passer FRAMATEX_PG_MODE=local.'
        }
        & docker info *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop n''est pas démarré. Lancer Docker Desktop puis réessayer.' }
        $env:FRAMATEX_PG_PASSWORD = $env:PGPASSWORD      # lu par docker compose pour créer la base au premier démarrage
        try { & docker compose -f $ComposeFile up -d postgres } finally { Remove-Item Env:FRAMATEX_PG_PASSWORD -ErrorAction SilentlyContinue }
        if ($LASTEXITCODE -ne 0) { throw 'Démarrage du conteneur PostgreSQL impossible (voir ci-dessus).' }
    } else {
        $service = Get-Service -Name 'postgresql*' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $service) { throw 'Service PostgreSQL introuvable. Installer PostgreSQL 16 pour Windows ou passer FRAMATEX_PG_MODE=docker.' }
        if ($service.Status -ne 'Running') {
            Write-Host "Démarrage du service $($service.Name) (droits administrateur nécessaires)..."
            Start-Service -Name $service.Name
        }
    }
}

function Wait-FramatexPostgres([string]$Python) {
    & $Python (Join-Path $Root 'scripts\wait_for_postgresql.py') --timeout 90
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL ne répond pas.' }
}

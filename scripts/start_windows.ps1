<#
.SYNOPSIS
    Démarre FRAMATEX en local sous Windows et le garde actif, après vérifications.

.DESCRIPTION
    1. Code        : branche Git, commit, présence de final/platform-review, syntaxe Python.
    2. Python      : environnement virtuel .venv (créé si besoin), dépendances.
    3. Réseau      : variables de proxy, proxy système, fichier hosts, localhost.
    4. Port        : anciens serveurs FRAMATEX arrêtés ; tout autre programme est
                     laissé intact et le port libre suivant (8001, 8002…) est utilisé.
    5. Données     : dossier data, verrou SQLite, sauvegarde du jour, migrations.
    6. Comptes     : administrateurs et comptes Client ; en mode -Demo, compte
                     admin.test@framatex.com (mot de passe saisi, jamais enregistré)
                     et dossiers de démonstration A–E (sans doublon).
    7. Serveur     : Uvicorn sans --reload, journaux dans data\logs, lié à cette fenêtre.
    8. Vérifications HTTP réelles : santé, pages, CSS/JS, connexion admin (-Demo).
    9. Navigateur  : Chrome (ou le navigateur par défaut) sur la landing ; le serveur
                     reste actif jusqu'à Ctrl+C ou la fermeture de la fenêtre.

    En cas d'échec : ÉTAPE, CAUSE, SOLUTION, et journal complet sans mot de passe
    dans data\logs\start-windows-AAAAMMJJ-HHMMSS.log.

.EXAMPLE
    scripts\start_windows.cmd -Demo
.EXAMPLE
    scripts\start_windows.cmd -Port 8010 -NoBrowser
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Demo,
    [switch]$Reload,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$BindHost = '127.0.0.1'
$DemoEmail = 'admin.test@framatex.com'
$Root = Split-Path -Parent $PSScriptRoot
$OnWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogDir = [System.IO.Path]::Combine($Root, 'data', 'logs')
$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:Actions = New-Object System.Collections.Generic.List[string]
$script:Server = $null
$script:ServerReady = $false
$script:Step = 'Initialisation'
$script:Tails = @()
$script:Interrupted = $false

# Mot de passe de démonstration éventuellement fourni par variable temporaire :
# converti en SecureString puis retiré de l'environnement (jamais transmis au serveur).
$script:DemoSecret = $null
if ($env:FRAMATEX_DEMO_PASSWORD) {
    $script:DemoSecret = ConvertTo-SecureString -String $env:FRAMATEX_DEMO_PASSWORD -AsPlainText -Force
}
Remove-Item Env:FRAMATEX_DEMO_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue

# --------------------------------------------------------------------------- affichage
function Write-Step([string]$Text) { $script:Step = $Text; Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "  [..]   $Text" }
function Write-Warn([string]$Text) { Write-Host "  [!]    $Text" -ForegroundColor Yellow; $script:Warnings.Add($Text) }
function Write-Action([string]$Text) { Write-Host "  [FAIT] $Text" -ForegroundColor Magenta; $script:Actions.Add($Text) }

function Write-Diagnosis([string]$Cause, [string]$Solution, [string]$Color = 'Yellow') {
    Write-Host "  ÉTAPE    : $script:Step" -ForegroundColor $Color
    Write-Host "  CAUSE    : $Cause" -ForegroundColor $Color
    Write-Host "  SOLUTION : $Solution" -ForegroundColor $Color
}

# Problème non bloquant : diagnostic affiché, le lanceur continue.
function Write-Problem([string]$Cause, [string]$Solution) {
    Write-Diagnosis $Cause $Solution
    $script:Warnings.Add("$($script:Step) : $Cause")
}

# Problème bloquant : diagnostic puis arrêt du lanceur.
function Stop-Launcher([string]$Cause, [string]$Solution) {
    Write-Host ''
    Write-Host '  [ÉCHEC]' -ForegroundColor Red
    Write-Diagnosis $Cause $Solution 'Red'
    throw 'FRAMATEX_STOP'
}

# Exécute un programme externe sans que sa sortie d'erreur ne devienne une
# exception PowerShell (comportement de Windows PowerShell 5.1).
function Invoke-Native {
    param([string]$File, [string[]]$Arguments = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $File @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } catch {
        $output = @("$_"); $code = -1
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Code = $code; Output = @($output) }
}

function Join-RootPath([string[]]$Parts) { return [System.IO.Path]::Combine([string[]](@($Root) + $Parts)) }

function ConvertTo-PlainText([System.Security.SecureString]$Secure) {
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

# --------------------------------------------------------------------------- 1. code
function Test-Code {
    Write-Step '1. Code'
    Write-Info "Dossier : $Root"
    if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) {
        $branch = (Invoke-Native -File 'git' -Arguments @('-C', $Root, 'rev-parse', '--abbrev-ref', 'HEAD')).Output | Select-Object -First 1
        $commit = (Invoke-Native -File 'git' -Arguments @('-C', $Root, 'rev-parse', '--short', 'HEAD')).Output | Select-Object -First 1
        $changes = @((Invoke-Native -File 'git' -Arguments @('-C', $Root, 'status', '--porcelain', '--untracked-files=no')).Output | Where-Object { $_ }).Count
        Write-Info "Branche $branch · commit $commit · $changes fichier(s) suivi(s) modifié(s) localement"
        $reference = Invoke-Native -File 'git' -Arguments @('-C', $Root, 'rev-parse', '--verify', '--quiet', 'origin/final/platform-review')
        if ($reference.Code -eq 0) {
            $contains = Invoke-Native -File 'git' -Arguments @('-C', $Root, 'merge-base', '--is-ancestor', 'origin/final/platform-review', 'HEAD')
            if ($contains.Code -eq 0) { Write-Ok 'La branche contient tout final/platform-review' }
            else { Write-Problem 'La branche ne contient pas tout final/platform-review' 'git fetch origin puis git checkout fix/windows-demo-final' }
        }
    } else {
        Write-Info 'Git introuvable dans le PATH : branche non vérifiée'
    }
    Write-Info ("PowerShell {0} · {1}" -f $PSVersionTable.PSVersion, [System.Environment]::OSVersion.VersionString)
}

# --------------------------------------------------------------------------- 2. python
function Get-PythonInfo([string]$Candidate, [string[]]$Prefix = @()) {
    $probe = Invoke-Native -File $Candidate -Arguments ($Prefix + @('-c', 'import sys; print(sys.executable); print(sys.prefix != sys.base_prefix); print(sys.version_info >= (3, 11)); print(sys.version.split()[0])'))
    if ($probe.Code -eq 0 -and $probe.Output.Count -ge 4 -and (Test-Path -LiteralPath $probe.Output[0])) {
        return [pscustomobject]@{ Exe = $probe.Output[0]; IsVenv = ($probe.Output[1] -eq 'True')
                                  Supported = ($probe.Output[2] -eq 'True'); Version = $probe.Output[3] }
    }
    return $null
}

function Find-BasePython {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:VIRTUAL_ENV) {
        $candidates.Add([System.IO.Path]::Combine($env:VIRTUAL_ENV, 'Scripts', 'python.exe'))
        $candidates.Add([System.IO.Path]::Combine($env:VIRTUAL_ENV, 'bin', 'python'))
    }
    foreach ($name in 'python', 'python3') {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidates.Add($command.Source) }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $info = Get-PythonInfo $candidate   # l'alias Microsoft Store (WindowsApps) échoue ici et est ignoré
        if ($info -and $info.Supported) { return $info }
    }
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        $info = Get-PythonInfo $launcher.Source @('-3')
        if ($info -and $info.Supported) { return $info }
    }
    return $null
}

function Test-Dependencies($Python) {
    $deps = Invoke-Native -File $Python.Exe -Arguments @((Join-RootPath @('scripts', 'windows_preflight.py')), 'deps')
    $deps.Output | ForEach-Object { Write-Host $_ }
    return ($deps.Code -eq 0)
}

function Initialize-Python {
    Write-Step '2. Python et environnement virtuel (.venv)'
    $venvDir = Join-RootPath @('.venv')
    $venvPython = Join-RootPath @('.venv', 'Scripts', 'python.exe')
    if (-not $OnWindows) { $venvPython = Join-RootPath @('.venv', 'bin', 'python') }
    $python = $null
    if (Test-Path -LiteralPath $venvPython) { $python = Get-PythonInfo $venvPython }
    if ($python -and -not $python.Supported) {
        Write-Warn ".venv utilise Python $($python.Version) : 3.11 ou plus récent est requis"
        $python = $null
    }
    if (-not $python) {
        $base = Find-BasePython
        if (-not $base) {
            Stop-Launcher 'Aucun Python 3.11 ou plus récent trouvé (python, py -3).' 'Installez Python depuis python.org en cochant « Add python.exe to PATH », puis relancez.'
        }
        Write-Action "Environnement virtuel .venv préparé avec Python $($base.Version) ($($base.Exe))"
        $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        & $base.Exe -m venv --clear $venvDir | Out-Host
        $code = $LASTEXITCODE
        $ErrorActionPreference = $previous
        if ($code -eq 0) { $python = Get-PythonInfo $venvPython }
        if (-not $python) {
            if (Test-Dependencies $base) {
                Write-Problem ".venv n'a pas pu être créé dans $venvDir" 'Python global utilisé à la place (dépendances présentes) ; vérifiez les droits du dossier.'
                return $base
            }
            Stop-Launcher ".venv n'a pas pu être créé dans $venvDir." "Vérifiez les droits d'écriture du dossier (antivirus, OneDrive), puis relancez."
        }
    }
    Write-Info "Python $($python.Version) : $($python.Exe)"
    if (Test-Dependencies $python) { return $python }

    Write-Action 'Installation des dépendances de requirements.txt dans .venv'
    $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $python.Exe -m pip install --disable-pip-version-check -r (Join-RootPath @('requirements.txt')) | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) {
        $base = Find-BasePython
        if ($base -and $base.Exe -ne $python.Exe -and (Test-Dependencies $base)) {
            Write-Problem 'pip install a échoué dans .venv (réseau ou proxy).' "Python global $($base.Version) utilisé à la place : ses dépendances sont complètes."
            return $base
        }
        Stop-Launcher 'pip install a échoué (réseau, proxy ou droits).' 'Vérifiez la connexion Internet ou la variable HTTPS_PROXY de votre réseau, puis relancez. Détail dans le journal.'
    }
    if (-not (Test-Dependencies $python)) {
        Stop-Launcher 'Dépendances toujours manquantes après installation.' 'Supprimez le dossier .venv puis relancez : il sera recréé.'
    }
    return $python
}

# --------------------------------------------------------------------------- 3. réseau
function Add-ListEntries([string]$Current, [string[]]$Entries) {
    $items = @()
    if ($Current) { $items = @($Current -split '[,;\s]+' | Where-Object { $_ }) }
    $missing = @($Entries | Where-Object { $items -notcontains $_ })
    return [pscustomobject]@{ Value = (@($items) + $missing) -join ','; Missing = $missing }
}

function Test-LocalNetwork {
    Write-Step '3. Réseau local et proxy'
    $loopback = @('localhost', '127.0.0.1', '::1')
    $proxyVariables = @()
    foreach ($name in 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy') {
        $value = [System.Environment]::GetEnvironmentVariable($name)
        if ($value -and ($proxyVariables -notcontains $name.ToUpper())) {
            $proxyVariables += $name.ToUpper()
            Write-Info ("{0} = {1}" -f $name.ToUpper(), ($value -replace '//[^/@]*@', '//***@'))
        }
    }
    if ($proxyVariables.Count) {
        $merged = Add-ListEntries ([System.Environment]::GetEnvironmentVariable('NO_PROXY')) $loopback
        if ($merged.Missing.Count) {
            $env:NO_PROXY = $merged.Value
            if ($OnWindows) {
                $user = Add-ListEntries ([System.Environment]::GetEnvironmentVariable('NO_PROXY', 'User')) (@($merged.Value -split ','))
                [System.Environment]::SetEnvironmentVariable('NO_PROXY', $user.Value, 'User')
            }
            Write-Action ("NO_PROXY complété avec {0} : les requêtes locales ne passent plus par le proxy (Internet inchangé)" -f ($merged.Missing -join ', '))
        } else {
            Write-Ok 'NO_PROXY exclut déjà localhost, 127.0.0.1 et ::1'
        }
    } else {
        Write-Ok 'Aucune variable HTTP_PROXY / HTTPS_PROXY / ALL_PROXY'
    }

    if ($OnWindows) {
        $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        $settings = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        $enabled = $false; $pac = $null; $server = $null; $override = $null
        if ($settings) {
            if ($settings.PSObject.Properties['ProxyEnable']) { $enabled = ($settings.ProxyEnable -eq 1) }
            if ($settings.PSObject.Properties['AutoConfigURL']) { $pac = $settings.AutoConfigURL }
            if ($settings.PSObject.Properties['ProxyServer']) { $server = $settings.ProxyServer }
            if ($settings.PSObject.Properties['ProxyOverride']) { $override = $settings.ProxyOverride }
        }
        if ($enabled -or $pac) {
            Write-Info ('Proxy système : {0} {1}' -f $server, $pac)
            $bypassed = $true
            try { $bypassed = [System.Net.WebRequest]::GetSystemWebProxy().IsBypassed([uri]"http://${BindHost}:$Port/") } catch { $bypassed = $true }
            if ($bypassed) {
                Write-Ok 'Le proxy système laisse passer 127.0.0.1 en direct'
            } elseif ($enabled) {
                $merged = Add-ListEntries ($override -replace ';', ',') @('<local>', 'localhost', '127.0.0.1', '[::1]')
                Set-ItemProperty -Path $key -Name ProxyOverride -Value ($merged.Value -replace ',', ';')
                Write-Action ("Proxy système : exceptions ajoutées pour {0} (adresses locales uniquement)" -f ($merged.Missing -join ', '))
            } else {
                Write-Problem "Le script de configuration proxy ($pac) envoie 127.0.0.1 au proxy." "Demandez au service informatique d'exclure les adresses locales ; Chrome les contourne de toute façon."
            }
        } else {
            Write-Ok 'Pas de proxy système (paramètres Internet de Windows)'
        }
        $hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
        if (Test-Path -LiteralPath $hosts) {
            $redirects = @(Select-String -LiteralPath $hosts -Pattern '^\s*([^#\s]+)\s+(.*\s)?localhost(\s|$)' -ErrorAction SilentlyContinue |
                Where-Object { @('127.0.0.1', '::1') -notcontains $_.Matches[0].Groups[1].Value })
            if ($redirects.Count) {
                Write-Problem ("Fichier hosts : localhost redirigé ({0})." -f $redirects[0].Line.Trim()) "Utilisez http://127.0.0.1:$Port/ (adresse ouverte automatiquement)."
            }
        }
    }
    try {
        $addresses = @([System.Net.Dns]::GetHostAddresses('localhost') | ForEach-Object { $_.IPAddressToString })
        Write-Info ("localhost → {0} ; le serveur écoute sur $BindHost (IPv4)" -f ($addresses -join ', '))
    } catch {
        Write-Info "localhost ne se résout pas : l'adresse 127.0.0.1 sera utilisée"
    }
}

# --------------------------------------------------------------------------- 4. port
function ConvertFrom-Netstat([string[]]$Lines, [int]$Port) {
    # Indépendant de la langue de Windows : un socket en écoute a une adresse
    # distante 0.0.0.0:0 ou [::]:0, quel que soit le libellé de l'état.
    $owners = @()
    foreach ($line in $Lines) {
        $parts = @($line.Trim() -split '\s+')
        if ($parts.Count -lt 5 -or $parts[0] -ne 'TCP') { continue }
        if ($parts[1] -notmatch ':(\d+)$' -or [int]$Matches[1] -ne $Port) { continue }
        if ($parts[2] -notmatch '^(0\.0\.0\.0|\[::\]):0$') { continue }
        $owners += [pscustomobject]@{ Address = ($parts[1] -replace ':\d+$', ''); ProcessId = [int]$parts[-1] }
    }
    return $owners
}

function Get-PortOwners([int]$Port) {
    if (-not $OnWindows) { return @() }
    $owners = @()
    try {
        $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { [pscustomobject]@{ Address = $_.LocalAddress; ProcessId = [int]$_.OwningProcess } })
    } catch { $owners = @() }
    if (-not $owners.Count) {
        $lines = (Invoke-Native -File 'netstat.exe' -Arguments @('-ano')).Output
        $owners = @(ConvertFrom-Netstat $lines $Port)
    }
    return @($owners | Sort-Object ProcessId, Address -Unique)
}

function Test-PortBindable([int]$Port) {
    $listener = New-Object System.Net.Sockets.TcpListener ([System.Net.IPAddress]::Parse($BindHost)), $Port
    # SO_EXCLUSIVEADDRUSE : échoue aussi face à un serveur lancé en --reload (SO_REUSEADDR).
    try { $listener.ExclusiveAddressUse = $true } catch { Write-Verbose 'ExclusiveAddressUse indisponible' }
    try { $listener.Start(); return $true } catch { return $false } finally { try { $listener.Stop() } catch { Write-Verbose 'arrêt du test de port' } }
}

function Get-ProcessDetails([int]$ProcessId) {
    try { return Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop } catch { return $null }
}

function Test-FramatexServer($Process) {
    if (-not $Process) { return $false }
    $name = [string]$Process.Name
    $command = [string]$Process.CommandLine
    $isPython = $name -match '^(python|pythonw|py|uvicorn)[\d.]*\.exe$'
    $isServer = ($command -match 'uvicorn') -or ($command -match 'spawn_main') -or ($command -match 'app[.:]main')
    return ($isPython -and $isServer)
}

function Stop-ProcessTree([int]$ProcessId, [string]$Reason) {
    $result = Invoke-Native -File 'taskkill.exe' -Arguments @('/PID', "$ProcessId", '/T', '/F')
    if ($result.Code -eq 0) { Write-Action "$Reason (PID $ProcessId arrêté avec ses processus enfants)" }
    else { Write-Warn ("Arrêt impossible du PID {0} : {1}" -f $ProcessId, ($result.Output -join ' ')) }
}

# Serveurs FRAMATEX de ce dossier encore actifs, quel que soit leur port
# (identifiés par l'exécutable Python de .venv et la commande Uvicorn app.main).
function Stop-RepositoryServers {
    if (-not $OnWindows) { return }
    $venv = (Join-RootPath @('.venv')) + [System.IO.Path]::DirectorySeparatorChar
    $servers = @(Get-CimInstance -ClassName Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { ([string]$_.ExecutablePath).StartsWith($venv, [System.StringComparison]::OrdinalIgnoreCase) -and
                       ([string]$_.CommandLine) -match 'uvicorn' -and ([string]$_.CommandLine) -match 'app[.:]main' })
    foreach ($server in $servers) { Stop-ProcessTree $server.ProcessId 'Ancien serveur FRAMATEX de ce dossier' }
}

function Show-ExcludedRanges([int]$Port) {
    $ranges = (Invoke-Native -File 'netsh.exe' -Arguments @('interface', 'ipv4', 'show', 'excludedportrange', 'protocol=tcp')).Output
    foreach ($line in $ranges) {
        if ($line -match '^\s*(\d+)\s+(\d+)' -and $Port -ge [int]$Matches[1] -and $Port -le [int]$Matches[2]) {
            Write-Warn "Le port $Port est réservé par Windows (plage $($Matches[1])-$($Matches[2]), Hyper-V / WSL / Docker)."
        }
    }
}

function Select-Port([int]$Port) {
    Write-Step "4. Port $Port"
    Stop-RepositoryServers
    if ($OnWindows) {
        $lines = @((Invoke-Native -File 'netstat.exe' -Arguments @('-ano')).Output | Where-Object { $_ -match ":$Port\s" })
        Write-Info "netstat -ano | findstr :$Port"
        if ($lines.Count) { $lines | ForEach-Object { Write-Host "         $($_.Trim())" } } else { Write-Host '         (aucune ligne)' }
    }
    $foreign = @()
    foreach ($owner in @(Get-PortOwners $Port)) {
        $process = Get-ProcessDetails $owner.ProcessId
        if (-not $process) {
            # Processus parent disparu : un worker Uvicorn (--reload) a hérité du socket et le garde ouvert.
            $orphans = @(Get-CimInstance -ClassName Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
                Where-Object { $_.ParentProcessId -eq $owner.ProcessId -or ([string]$_.CommandLine) -match "parent_pid=$($owner.ProcessId)\b" })
            if ($orphans.Count) {
                foreach ($orphan in $orphans) { Stop-ProcessTree $orphan.ProcessId "Worker Uvicorn orphelin qui gardait le port $Port (PID d'origine $($owner.ProcessId) disparu)" }
            } else {
                $foreign += "PID $($owner.ProcessId) (processus introuvable)"
            }
        } elseif (Test-FramatexServer $process) {
            $parent = Get-ProcessDetails $process.ParentProcessId
            $command = ([string]$process.CommandLine)
            if ($command.Length -gt 110) { $command = $command.Substring(0, 110) + '…' }
            if (Test-FramatexServer $parent) { Stop-ProcessTree $parent.ProcessId 'Ancien superviseur Uvicorn --reload' }
            Stop-ProcessTree $process.ProcessId "Ancien serveur Uvicorn sur le port $Port : $($process.Name) $command"
        } else {
            $foreign += "$($process.Name) (PID $($process.ProcessId))"
        }
    }
    for ($i = 0; $i -lt 30; $i++) {
        if (-not @(Get-PortOwners $Port).Count -and (Test-PortBindable $Port)) {
            Write-Ok "Port $Port libre pour FRAMATEX"
            return $Port
        }
        if ($foreign.Count) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($foreign.Count) {
        Write-Info ("Le port {0} est utilisé par {1} : ce programme n'est pas FRAMATEX, il n'est pas arrêté." -f $Port, ($foreign -join ', '))
    } else {
        Write-Info "Le port $Port ne peut pas être réservé."
        if ($OnWindows) { Show-ExcludedRanges $Port }
    }
    for ($candidate = $Port + 1; $candidate -le $Port + 20; $candidate++) {
        if (-not @(Get-PortOwners $candidate).Count -and (Test-PortBindable $candidate)) {
            Write-Action "FRAMATEX utilisera le port $candidate"
            return $candidate
        }
    }
    Stop-Launcher "Aucun port libre entre $Port et $($Port + 20)." 'Fermez les programmes qui occupent ces ports ou relancez avec -Port 9000.'
}

# --------------------------------------------------------------------------- 5-6. données et comptes
function Invoke-Preflight($Python, [string[]]$Arguments) {
    $result = Invoke-Native -File $Python.Exe -Arguments (@((Join-RootPath @('scripts', 'windows_preflight.py'))) + $Arguments)
    $result.Output | ForEach-Object { Write-Host $_ }
    return $result.Code
}

function Initialize-Data($Python) {
    Write-Step '5. Données (data, SQLite, sauvegarde, migrations)'
    switch (Invoke-Preflight $Python @('db')) {
        0 { return }
        2 { Stop-Launcher 'Base SQLite verrouillée par un autre programme.' 'Fermez DB Browser for SQLite, un autre serveur FRAMATEX ou la synchronisation de fichiers, puis relancez.' }
        3 { Stop-Launcher 'Dossier data non accessible en écriture.' "Vérifiez les droits du dossier, l'antivirus ou OneDrive, puis relancez." }
        default { Stop-Launcher 'Contrôle des données ou migration en échec (voir le message ci-dessus).' 'Restaurez la sauvegarde de data\backups si nécessaire et envoyez le journal.' }
    }
}

function Read-NewSecret {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $first = Read-Host "  Mot de passe à définir pour $DemoEmail (12 caractères minimum)" -AsSecureString
        $second = Read-Host '  Confirmez ce mot de passe' -AsSecureString
        $a = ConvertTo-PlainText $first
        $b = ConvertTo-PlainText $second
        $valid = ($a.Length -ge 12) -and ($a -ceq $b)
        $tooShort = $a.Length -lt 12
        $a = $null; $b = $null
        if ($valid) { return $first }
        if ($tooShort) { Write-Host '  Mot de passe trop court (12 caractères minimum).' -ForegroundColor Yellow }
        else { Write-Host '  Les deux saisies diffèrent.' -ForegroundColor Yellow }
    }
    return $null
}

function Invoke-PreflightWithSecret($Python, [string[]]$Arguments, [System.Security.SecureString]$Secret) {
    # Le mot de passe passe par une variable propre au processus enfant, retirée aussitôt :
    # ni argument de commande, ni fichier, ni journal.
    $env:FRAMATEX_SECRET_INPUT = ConvertTo-PlainText $Secret
    try { return Invoke-Preflight $Python $Arguments }
    finally { Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue }
}

function Initialize-Accounts($Python) {
    Write-Step '6. Comptes'
    if (-not $Demo) {
        if ((Invoke-Preflight $Python @('accounts')) -eq 12) {
            Write-Problem "Aucun administrateur actif : l'Espace FRAMATEX n'est pas utilisable." 'Relancez avec -Demo pour créer admin.test@framatex.com (mot de passe demandé).'
        }
        return
    }
    $status = Invoke-Preflight $Python @('accounts', '--email', $DemoEmail)
    if ($status -eq 10) {
        $create = $true
        if (-not $script:DemoSecret) {
            $answer = Read-Host "  Créer le compte administrateur de test $DemoEmail ? (O/n)"
            $create = ($answer -notmatch '^\s*[nN]')
            if ($create) { $script:DemoSecret = Read-NewSecret }
        }
        if (-not $create) {
            Write-Problem "Compte $DemoEmail non créé : démonstration A–E non chargée." 'Relancez avec -Demo et répondez O, ou créez un administrateur avec python -m app.bootstrap_admin.'
            return
        }
        if (-not $script:DemoSecret) { Stop-Launcher 'Mot de passe non défini après trois essais.' 'Relancez la commande et saisissez deux fois le même mot de passe de 12 caractères minimum.' }
        if ((Invoke-PreflightWithSecret $Python @('create-admin', '--email', $DemoEmail) $script:DemoSecret) -ne 0) {
            Stop-Launcher "Création du compte $DemoEmail refusée (voir ci-dessus)." 'Choisissez un mot de passe de 12 à 256 caractères, puis relancez.'
        }
        Write-Action "Compte administrateur de test $DemoEmail créé"
    } elseif ($status -eq 11) {
        Write-Problem "$DemoEmail existe mais n'est pas un administrateur actif." "Réactivez-le ou donnez-lui le rôle Administrateur depuis l'écran Administration."
        return
    }
    if ((Invoke-Preflight $Python @('seed', '--email', $DemoEmail)) -ne 0) {
        Write-Problem 'Dossiers de démonstration A–E non chargés (voir ci-dessus).' 'Relancez la commande ; le chargement ne crée jamais de doublon.'
    }
}

# --------------------------------------------------------------------------- 7. serveur
function Add-ServerToJob($Process) {
    # Lie le serveur à cette fenêtre : si PowerShell se termine (Ctrl+C, fermeture,
    # erreur), Windows arrête aussi Uvicorn. Aucun serveur orphelin ne garde le port.
    if (-not $OnWindows) { return }
    try {
        if (-not ('FramatexJob.Guard' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace FramatexJob {
    public static class Guard {
        [StructLayout(LayoutKind.Sequential)] struct BasicLimits { public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags; public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass; }
        [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong ReadOperationCount; public ulong WriteOperationCount; public ulong OtherOperationCount; public ulong ReadTransferCount; public ulong WriteTransferCount; public ulong OtherTransferCount; }
        [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits { public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemoryLimit; public UIntPtr JobMemoryLimit; public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed; }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref ExtendedLimits info, uint length);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        static IntPtr job = IntPtr.Zero;
        public static bool Attach(IntPtr process) {
            if (job == IntPtr.Zero) {
                IntPtr created = CreateJobObject(IntPtr.Zero, null);
                if (created == IntPtr.Zero) return false;
                ExtendedLimits limits = new ExtendedLimits();
                limits.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if (!SetInformationJobObject(created, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits)))) return false;
                job = created;
            }
            return AssignProcessToJobObject(job, process);
        }
    }
}
'@
        }
        if ([FramatexJob.Guard]::Attach($Process.Handle)) { Write-Ok "Serveur lié à cette fenêtre : il s'arrête avec elle, sans laisser de processus orphelin" }
        else { Write-Info 'Liaison du serveur à la fenêtre indisponible : un ancien serveur sera nettoyé au prochain lancement' }
    } catch {
        Write-Info "Liaison du serveur à la fenêtre indisponible ($($_.Exception.Message))"
    }
}

function New-LogTail([string]$Path) { return [pscustomobject]@{ Path = $Path; Position = [long]0; Rest = '' } }

function Show-LogTail($Tail) {
    try {
        if (-not (Test-Path -LiteralPath $Tail.Path)) { return }
        $stream = [System.IO.File]::Open($Tail.Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            if ($stream.Length -le $Tail.Position) { return }
            $null = $stream.Seek($Tail.Position, [System.IO.SeekOrigin]::Begin)
            $buffer = New-Object byte[] ($stream.Length - $Tail.Position)
            $read = $stream.Read($buffer, 0, $buffer.Length)
            $Tail.Position += $read
        } finally { $stream.Dispose() }
        $lines = ($Tail.Rest + [System.Text.Encoding]::UTF8.GetString($buffer, 0, $read)) -split "`r?`n"
        $Tail.Rest = $lines[-1]
        for ($i = 0; $i -lt $lines.Count - 1; $i++) {
            if ($lines[$i]) { Write-Host "  | $($lines[$i])" -ForegroundColor DarkGray }
        }
    } catch {
        Write-Verbose "Lecture du journal serveur : $($_.Exception.Message)"
    }
}

function Show-ServerLogs { foreach ($tail in $script:Tails) { Show-LogTail $tail } }

function Get-ServerFailure {
    $text = ''
    foreach ($tail in $script:Tails) {
        try { $text += (Get-Content -LiteralPath $tail.Path -Tail 40 -ErrorAction Stop | Out-String) } catch { Write-Verbose 'journal absent' }
    }
    $code = 'inconnu'
    try { $code = $script:Server.ExitCode } catch { Write-Verbose 'code de sortie indisponible' }
    $cause = "Uvicorn s'est arrêté (code $code)."
    $solution = "Consultez $($script:Tails[0].Path) et envoyez-le avec le journal du lanceur."
    $lastError = @($text -split "`r?`n" | Where-Object { $_ -match 'Error|error|Exception|refus|denied' }) | Select-Object -Last 1
    if ($lastError) { $cause += " Dernière erreur : $($lastError.Trim())" }
    if ($text -match '10048|10013|address already in use|only one usage') {
        $solution = 'Un autre programme a pris le port : relancez la commande, un port libre sera choisi.'
    } elseif ($text -match 'database is locked') {
        $solution = 'Fermez le programme qui utilise data\framat.db (DB Browser, autre serveur), puis relancez.'
    } elseif ($text -match 'ModuleNotFoundError|ImportError') {
        $solution = 'Supprimez le dossier .venv puis relancez : les dépendances seront réinstallées.'
    } elseif ($text -match 'PermissionError|Access is denied|Accès refusé') {
        $solution = "Droits insuffisants sur le dossier : vérifiez l'antivirus ou OneDrive, puis relancez."
    }
    return [pscustomobject]@{ Cause = $cause; Solution = $solution }
}

function Invoke-Http([string]$Url, [int]$TimeoutSeconds = 10) {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [System.TimeSpan]::FromSeconds($TimeoutSeconds)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $type = ''
        if ($response.Content.Headers.ContentType) { $type = $response.Content.Headers.ContentType.MediaType }
        return [pscustomobject]@{ Ok = $true; Status = [int]$response.StatusCode; Ms = $watch.ElapsedMilliseconds; Type = $type
                                  Bytes = $bytes.Length; Text = [System.Text.Encoding]::UTF8.GetString($bytes); Error = '' }
    } catch {
        return [pscustomobject]@{ Ok = $false; Status = 0; Ms = $watch.ElapsedMilliseconds; Type = ''; Bytes = 0; Text = ''
                                  Error = $_.Exception.GetBaseException().Message }
    } finally {
        $client.Dispose()
    }
}

function Start-Server($Python, [int]$Port) {
    Write-Step '7. Démarrage du serveur'
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $out = [System.IO.Path]::Combine($LogDir, "uvicorn-$Stamp.out.log")
    $err = [System.IO.Path]::Combine($LogDir, "uvicorn-$Stamp.err.log")
    $script:Tails = @((New-LogTail $err), (New-LogTail $out))
    $arguments = @('-m', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', "$Port")
    if ($Reload) { $arguments += '--reload'; Write-Info 'Mode --reload : port vérifié en accès exclusif avant démarrage.' }
    Write-Info ("{0} {1}" -f $Python.Exe, ($arguments -join ' '))
    Write-Info "Journaux du serveur : $err"
    Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue
    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    # Sorties redirigées vers des fichiers : une sélection dans la console (Édition rapide)
    # ne peut plus bloquer le serveur, et la cause d'un arrêt reste lisible.
    $script:Server = Start-Process -FilePath $Python.Exe -ArgumentList $arguments -WorkingDirectory $Root -NoNewWindow -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $script:Server.Handle   # conserve le code de sortie (Windows PowerShell 5.1)
    Add-ServerToJob $script:Server

    $deadline = (Get-Date).AddSeconds(90)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        Show-ServerLogs
        if ($script:Server.HasExited) {
            Show-ServerLogs
            $failure = Get-ServerFailure
            Stop-Launcher $failure.Cause $failure.Solution
        }
        $health = Invoke-Http "http://${BindHost}:$Port/api/health" 3
        if ($health.Ok -and $health.Status -eq 200) {
            $script:ServerReady = $true
            Write-Ok ("Serveur prêt (PID {0}) : /api/health répond en {1} ms" -f $script:Server.Id, $health.Ms)
            return
        }
        Start-Sleep -Milliseconds 500
    }
    $owners = @(Get-PortOwners $Port | ForEach-Object { $_.ProcessId })
    if ($owners.Count -and $owners -notcontains $script:Server.Id) {
        Stop-Launcher ("Un autre processus ({0}) a pris le port $Port pendant le démarrage." -f ($owners -join ', ')) 'Relancez la commande : un port libre sera choisi.'
    }
    Stop-Launcher "Uvicorn tourne mais /api/health ne répond pas après 90 s ($($health.Error))." "Envoyez les journaux de data\logs ; vérifiez qu'aucun antivirus ne bloque python.exe."
}

# --------------------------------------------------------------------------- 8. vérifications
function Test-Platform([int]$Port) {
    Write-Step '8. Vérifications HTTP réelles (sans proxy)'
    $base = "http://${BindHost}:$Port"
    $failures = 0
    $pages = @(
        @{ Path = '/api/health'; Type = 'application/json'; Marker = '"status":"ok"' },
        @{ Path = '/'; Type = 'text/html'; Marker = 'Choisissez votre espace' },
        @{ Path = '/espace-client'; Type = 'text/html'; Marker = '/assets/client/' },
        @{ Path = '/espace-framatex'; Type = 'text/html'; Marker = '/assets/app.js' }
    )
    $assets = New-Object System.Collections.Generic.List[string]
    foreach ($page in $pages) {
        $r = Invoke-Http ($base + $page.Path)
        if ($r.Ok -and $r.Status -eq 200 -and $r.Type -eq $page.Type -and $r.Text.Contains($page.Marker)) {
            Write-Ok ("{0,-36} {1}  {2,5} ms  {3}" -f $page.Path, $r.Status, $r.Ms, $r.Type)
        } else {
            $failures++
            Write-Problem ("{0} : statut {1}, type '{2}' {3}" -f $page.Path, $r.Status, $r.Type, $r.Error) 'Envoyez les journaux de data\logs.'
        }
        foreach ($match in [regex]::Matches($r.Text, '(?:href|src)="(/assets/[^"?#]+\.(?:css|js))"')) {
            if (-not $assets.Contains($match.Groups[1].Value)) { $assets.Add($match.Groups[1].Value) }
        }
    }
    foreach ($extra in '/assets/landing/logo-framatex.jpg', '/assets/brand/fonts/dm-sans-latin-400-normal.woff2') { $assets.Add($extra) }
    $expected = @{ '.css' = @('text/css'); '.js' = @('text/javascript', 'application/javascript'); '.jpg' = @('image/jpeg'); '.woff2' = @('font/woff2') }
    $assetFailures = 0
    foreach ($asset in $assets) {
        $r = Invoke-Http ($base + $asset)
        $types = $expected[[System.IO.Path]::GetExtension($asset)]
        if (-not ($r.Ok -and $r.Status -eq 200 -and $types -contains $r.Type)) {
            $assetFailures++
            Write-Problem ("{0} : statut {1}, type '{2}' (attendu {3}) {4}" -f $asset, $r.Status, $r.Type, ($types -join ' ou '), $r.Error) 'Envoyez les journaux de data\logs.'
        }
    }
    if (-not $assetFailures) { Write-Ok ("{0} ressources CSS / JS / image / police : 200 avec le bon type" -f $assets.Count) }
    $failures += $assetFailures

    if ($OnWindows -and (Get-Command Test-NetConnection -ErrorAction SilentlyContinue)) {
        $tcp = Test-NetConnection -ComputerName $BindHost -Port $Port -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { Write-Ok "Test-NetConnection ${BindHost}:$Port : port joignable" }
        else { $failures++; Write-Problem "Test-NetConnection ${BindHost}:$Port en échec" 'Un pare-feu ou un antivirus bloque la boucle locale : autorisez python.exe.' }
    }
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $curl) { $curl = Get-Command curl -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if ($curl) {
        $sink = '/dev/null'
        if ($OnWindows) { $sink = 'NUL' }
        # Windows PowerShell transmet « * » tel quel ; PowerShell 7 hors Windows le développerait en noms de fichiers.
        $bypass = '*'
        if (-not $OnWindows) { $bypass = '127.0.0.1,localhost,::1' }
        foreach ($variant in @(@{ Label = 'curl --noproxy'; Extra = @('--noproxy', $bypass) }, @{ Label = 'curl (proxy de la session)'; Extra = @() })) {
            foreach ($hostName in $BindHost, 'localhost') {
                $arguments = $variant.Extra + @('--connect-timeout', '5', '--max-time', '10', '-s', '-o', $sink, '-w', '%{http_code} %{time_total}s', "http://${hostName}:$Port/api/health")
                $result = Invoke-Native -File $curl.Source -Arguments $arguments
                $answer = ($result.Output -join ' ').Trim()
                if ($result.Code -eq 0 -and $answer -like '200 *') { Write-Ok ("{0,-28} http://{1}:{2}/api/health → {3}" -f $variant.Label, $hostName, $Port, $answer) }
                else { $failures++; Write-Problem ("{0} http://{1}:{2}/api/health → code curl {3} {4}" -f $variant.Label, $hostName, $Port, $result.Code, $answer) 'Vérifiez les variables de proxy (étape 3).' }
            }
        }
    }
    return $failures
}

function Test-AdminLogin([int]$Port) {
    if (-not $Demo) { return 0 }
    if (-not $script:DemoSecret -and -not $CheckOnly) {
        $typed = Read-Host "  Mot de passe de $DemoEmail pour vérifier la connexion (Entrée pour passer)" -AsSecureString
        if ($typed.Length) { $script:DemoSecret = $typed }
    }
    if (-not $script:DemoSecret) { Write-Info 'Vérification de la connexion admin passée (aucun mot de passe saisi)'; return 0 }
    $base = "http://${BindHost}:$Port"
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.UseCookies = $true
    $handler.CookieContainer = New-Object System.Net.CookieContainer
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [System.TimeSpan]::FromSeconds(15)
    $client.DefaultRequestHeaders.Add('X-Framatex-Request', '1')
    try {
        $body = @{ email = $DemoEmail; password = (ConvertTo-PlainText $script:DemoSecret) } | ConvertTo-Json -Compress
        $content = New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, 'application/json')
        $body = $null
        $login = $client.PostAsync("$base/api/auth/login", $content).GetAwaiter().GetResult()
        $content.Dispose()
        $status = [int]$login.StatusCode
        if ($status -ne 200) {
            $hint = 'Vérifiez le mot de passe de admin.test@framatex.com, puis relancez.'
            if ($status -eq 429) { $hint = "Trop d'essais : patientez 5 minutes avant de relancer." }
            Write-Problem "POST /api/auth/login → $status pour $DemoEmail." $hint
            return 1
        }
        $me = $client.GetAsync("$base/api/auth/me").GetAwaiter().GetResult()
        $identity = $me.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        $null = $client.PostAsync("$base/api/auth/logout", (New-Object System.Net.Http.StringContent(''))).GetAwaiter().GetResult()
        if ([int]$me.StatusCode -eq 200 -and $identity.email -eq $DemoEmail -and $identity.admin) {
            Write-Ok "Connexion réelle : POST /api/auth/login 200, GET /api/auth/me → $($identity.email) (Administrateur)"
            return 0
        }
        Write-Problem "GET /api/auth/me → $([int]$me.StatusCode) sans le profil administrateur attendu." 'Vérifiez le rôle du compte dans Administration.'
        return 1
    } catch {
        Write-Problem "Connexion admin impossible : $($_.Exception.GetBaseException().Message)" 'Envoyez les journaux de data\logs.'
        return 1
    } finally {
        $client.Dispose()
    }
}

# --------------------------------------------------------------------------- 9. navigateur et serveur actif
function Find-Chrome {
    if (-not $OnWindows) { return $null }
    foreach ($key in 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',
                     'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe',
                     'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') {
        try {
            $path = (Get-ItemProperty -Path $key -ErrorAction Stop).'(default)'
            if ($path -and (Test-Path -LiteralPath $path)) { return $path }
        } catch { Write-Verbose "Chrome absent de $key" }
    }
    foreach ($path in "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
                      "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
                      "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

function Open-Browser([string]$Url) {
    Write-Step '9. Navigateur'
    if ($NoBrowser -or -not $OnWindows) { Write-Info "Ouvrez $Url dans votre navigateur"; return }
    try {
        $chrome = Find-Chrome
        if ($chrome) { Start-Process -FilePath $chrome -ArgumentList $Url; Write-Action "Chrome ouvert sur $Url" }
        else { Start-Process $Url; Write-Action "Navigateur par défaut ouvert sur $Url (Chrome introuvable)" }
    } catch {
        # Ne jamais arrêter le serveur pour un problème de navigateur.
        Write-Problem "Ouverture automatique du navigateur impossible ($($_.Exception.Message))." "Ouvrez $Url à la main : le serveur reste actif."
    }
}

function Show-Guide([string]$Url) {
    Write-Host ''
    Write-Host "  FRAMATEX est en marche : $Url" -ForegroundColor Green
    Write-Host "    Landing          $Url"
    Write-Host "    Espace Client    ${Url}espace-client   (créer un compte, puis l'activer côté FRAMATEX)"
    Write-Host "    Espace FRAMATEX  ${Url}espace-framatex"
    if ($Demo) { Write-Host "                     compte $DemoEmail · dossiers FR-DEMO-2026-0141 à 0145" }
    Write-Host '  Laissez cette fenêtre ouverte. Ctrl+C ou fermeture de la fenêtre = arrêt du serveur.' -ForegroundColor Cyan
    Write-Host ''
}

function Wait-Server {
    $script:Step = 'Serveur actif'
    while (-not $script:Server.HasExited) {
        Show-ServerLogs
        Start-Sleep -Milliseconds 500
    }
    Show-ServerLogs
    $failure = Get-ServerFailure
    Stop-Launcher ("Le serveur s'est arrêté de lui-même. " + $failure.Cause) $failure.Solution
}

# --------------------------------------------------------------------------- programme principal
function Invoke-Launcher {
    Set-Location -LiteralPath $Root
    Add-Type -AssemblyName System.Net.Http
    Test-Code
    $python = Initialize-Python
    if ((Invoke-Preflight $python @('code')) -ne 0) {
        Stop-Launcher 'Erreur de syntaxe dans le code Python (voir ci-dessus).' 'Récupérez la branche à jour : git checkout -- app scripts, puis relancez.'
    }
    Test-LocalNetwork
    $port = Select-Port $Port
    Initialize-Data $python
    Initialize-Accounts $python
    Start-Server $python $port

    # Après le démarrage, plus aucune erreur du lanceur ne doit arrêter le serveur.
    $failures = 0
    try { $failures += Test-Platform $port } catch { $failures++; Write-Problem "Vérifications HTTP interrompues : $($_.Exception.Message)" 'Le serveur reste actif ; envoyez le journal.' }
    try { $failures += Test-AdminLogin $port } catch { $failures++; Write-Problem "Vérification de connexion interrompue : $($_.Exception.Message)" 'Le serveur reste actif.' }
    $script:DemoSecret = $null

    Write-Step 'Résumé'
    if ($script:Actions.Count) { Write-Host '  Corrections effectuées :'; $script:Actions | ForEach-Object { Write-Host "    - $_" } }
    if ($script:Warnings.Count) { Write-Host '  Points signalés :'; $script:Warnings | ForEach-Object { Write-Host "    - $_" } }
    if ($failures) { Write-Host "  $failures vérification(s) en échec." -ForegroundColor Red }
    else { Write-Host '  Toutes les vérifications sont passées.' -ForegroundColor Green }
    $url = "http://${BindHost}:$port/"
    if ($CheckOnly) { Write-Host "  Mode -CheckOnly : arrêt du serveur ($url)."; return $failures }
    Open-Browser $url
    Show-Guide $url
    Wait-Server
    return 0
}

if ($MyInvocation.InvocationName -eq '.') { return }   # chargement des fonctions pour les tests

$transcript = $null
try {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $transcript = [System.IO.Path]::Combine($LogDir, "start-windows-$Stamp.log")
    Start-Transcript -LiteralPath $transcript | Out-Null
} catch {
    $transcript = $null
}

$exitCode = 1
try {
    $exitCode = [int](@(Invoke-Launcher)[-1])
} catch [System.Management.Automation.PipelineStoppedException] {
    $script:Interrupted = $true
    $exitCode = 0
} catch {
    if ("$_" -ne 'FRAMATEX_STOP') {
        Write-Host ''
        Write-Host '  [ÉCHEC]' -ForegroundColor Red
        Write-Diagnosis "Erreur inattendue : $($_.Exception.Message)" "Envoyez le journal $transcript." 'Red'
        Write-Host $_.ScriptStackTrace
    }
    $exitCode = 1
} finally {
    $script:DemoSecret = $null
    Remove-Item Env:FRAMATEX_SECRET_INPUT -ErrorAction SilentlyContinue
    if ($script:Server -and -not $script:Server.HasExited -and $script:Interrupted) {
        $null = $script:Server.WaitForExit(3000)   # Ctrl+C : laisser Uvicorn s'arrêter proprement
    }
    if ($script:Server -and -not $script:Server.HasExited) {
        $null = Invoke-Native -File 'taskkill.exe' -Arguments @('/PID', "$($script:Server.Id)", '/T', '/F')
        if (-not $OnWindows) { try { $script:Server.Kill($true) } catch { Write-Verbose 'serveur déjà arrêté' } }
        if ($script:ServerReady -and -not $CheckOnly) { Write-Host '  Serveur arrêté (Ctrl+C ou fin du lanceur).' -ForegroundColor Cyan }
        else { Write-Host '  Serveur arrêté.' }
    }
    if ($script:Tails.Count) { Write-Host "  Journaux du serveur : $($script:Tails[0].Path)" }
    if ($transcript) {
        try { Stop-Transcript | Out-Null } catch { Write-Verbose 'transcription déjà arrêtée' }
        Write-Host "  Journal du lanceur : $transcript"
    }
}
exit $exitCode

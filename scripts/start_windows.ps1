<#
.SYNOPSIS
    Démarre FRAMATEX en local sous Windows, après diagnostic et nettoyage.

.DESCRIPTION
    1. Contexte : branche Git, commit, Python, environnement virtuel, dépendances.
    2. Réseau : variables de proxy, proxy système, fichier hosts, localhost IPv4/IPv6.
    3. Port : processus en écoute. Seuls les serveurs Python/Uvicorn présents sur ce
       port sont arrêtés, y compris un ancien serveur figé ou un worker « --reload »
       orphelin qui garde le socket. Tout autre programme est laissé intact et
       FRAMATEX prend alors le port libre suivant.
    4. Données : dossier data, verrou SQLite, sauvegarde du jour, migrations.
    5. Démarrage d'Uvicorn SANS --reload (option -Reload pour le développement),
       console protégée contre le gel « Édition rapide » (QuickEdit).
    6. Vérifications HTTP réelles, sans proxy : santé, pages, CSS/JS et leurs types.
    7. Ouverture du navigateur sur la landing. Ctrl+C arrête le serveur.

    Le diagnostic est enregistré dans data\logs\start-windows-<date>.log.

.EXAMPLE
    scripts\start_windows.cmd

.EXAMPLE
    scripts\start_windows.cmd -Port 8010 -NoBrowser
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$BindHost = '127.0.0.1'
$Root = Split-Path -Parent $PSScriptRoot
$OnWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
$script:Warnings = New-Object System.Collections.Generic.List[string]
$script:Actions = New-Object System.Collections.Generic.List[string]
$script:Server = $null

# --------------------------------------------------------------------------- affichage
function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "  [..]   $Text" }
function Write-Warn([string]$Text) { Write-Host "  [!]    $Text" -ForegroundColor Yellow; $script:Warnings.Add($Text) }
function Write-Action([string]$Text) { Write-Host "  [FAIT] $Text" -ForegroundColor Magenta; $script:Actions.Add($Text) }
function Stop-Launcher([string]$Text) {
    Write-Host ''
    Write-Host "  [ÉCHEC] $Text" -ForegroundColor Red
    throw "FRAMATEX_STOP: $Text"
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

# --------------------------------------------------------------------------- 1. contexte
function Show-Context {
    Write-Step '1. Contexte'
    Write-Info "Dossier : $Root"
    if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) {
        $branch = (Invoke-Native -File 'git' -Arguments @('-C', $Root, 'rev-parse', '--abbrev-ref', 'HEAD')).Output | Select-Object -First 1
        $commit = (Invoke-Native -File 'git' -Arguments @('-C', $Root, 'rev-parse', '--short', 'HEAD')).Output | Select-Object -First 1
        $changes = @((Invoke-Native -File 'git' -Arguments @('-C', $Root, 'status', '--porcelain')).Output | Where-Object { $_ }).Count
        Write-Info "Branche $branch · commit $commit · $changes fichier(s) modifié(s) localement"
    } else {
        Write-Info 'Git introuvable dans le PATH : branche non vérifiée'
    }
    Write-Info ("PowerShell {0} · {1}" -f $PSVersionTable.PSVersion, [System.Environment]::OSVersion.VersionString)
}

function Get-PythonInfo([string]$Candidate, [string[]]$Prefix = @()) {
    $probe = Invoke-Native -File $Candidate -Arguments ($Prefix + @('-c', 'import sys; print(sys.executable); print(sys.prefix != sys.base_prefix)'))
    if ($probe.Code -eq 0 -and $probe.Output.Count -ge 2 -and (Test-Path -LiteralPath $probe.Output[0])) {
        return [pscustomobject]@{ Exe = $probe.Output[0]; IsVenv = ($probe.Output[1] -eq 'True') }
    }
    return $null
}

function Resolve-Python {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:VIRTUAL_ENV) {
        $candidates.Add([System.IO.Path]::Combine($env:VIRTUAL_ENV, 'Scripts', 'python.exe'))
        $candidates.Add([System.IO.Path]::Combine($env:VIRTUAL_ENV, 'bin', 'python'))
    }
    $candidates.Add((Join-RootPath @('.venv', 'Scripts', 'python.exe')))
    $candidates.Add((Join-RootPath @('.venv', 'bin', 'python')))
    foreach ($name in 'python', 'python3') {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { $candidates.Add($command.Source) }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $info = Get-PythonInfo $candidate   # l'alias Microsoft Store (WindowsApps) échoue ici et est ignoré
        if ($info) { return $info }
    }
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) { return Get-PythonInfo $launcher.Source @('-3') }
    return $null
}

function Initialize-Python {
    $python = Resolve-Python
    if (-not $python) { Stop-Launcher 'Python introuvable. Installez Python 3.11 ou plus récent depuis python.org (cocher « Add to PATH »).' }
    $kind = 'Python global'
    if ($python.IsVenv) { $kind = 'environnement virtuel' }
    Write-Info "Python : $($python.Exe) ($kind)"
    $preflight = Join-RootPath @('scripts', 'windows_preflight.py')
    $deps = Invoke-Native -File $python.Exe -Arguments @($preflight, 'deps')
    $deps.Output | ForEach-Object { Write-Host $_ }
    if ($deps.Code -eq 0) { return $python }

    if (-not $python.IsVenv) {
        $venv = Join-RootPath @('.venv')
        Write-Action "Création d'un environnement virtuel dédié : $venv"
        & $python.Exe -m venv $venv | Out-Host
        if ($LASTEXITCODE -ne 0) { Stop-Launcher "Impossible de créer l'environnement virtuel $venv" }
        $exe = Join-RootPath @('.venv', 'Scripts', 'python.exe')
        if (-not $OnWindows) { $exe = Join-RootPath @('.venv', 'bin', 'python') }
        $python = [pscustomobject]@{ Exe = $exe; IsVenv = $true }
    }
    Write-Action 'Installation des dépendances de requirements.txt'
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python.Exe -m pip install --disable-pip-version-check -r (Join-RootPath @('requirements.txt')) | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) { Stop-Launcher 'pip install a échoué : vérifiez la connexion Internet ou le proxy de votre réseau.' }
    $deps = Invoke-Native -File $python.Exe -Arguments @($preflight, 'deps')
    $deps.Output | ForEach-Object { Write-Host $_ }
    if ($deps.Code -ne 0) { Stop-Launcher 'Dépendances toujours manquantes après installation.' }
    return $python
}

# --------------------------------------------------------------------------- 2. réseau
function Add-ListEntries([string]$Current, [string[]]$Entries) {
    $items = @()
    if ($Current) { $items = @($Current -split '[,;\s]+' | Where-Object { $_ }) }
    $missing = @($Entries | Where-Object { $items -notcontains $_ })
    return [pscustomobject]@{ Value = (@($items) + $missing) -join ','; Missing = $missing }
}

function Test-LocalNetwork {
    Write-Step '2. Réseau local et proxy'
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
            Write-Action ("NO_PROXY complété avec {0} : curl et Python n'envoient plus les requêtes locales au proxy (le proxy reste utilisé pour Internet)" -f ($merged.Missing -join ', '))
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
            try { $bypassed = [System.Net.WebRequest]::GetSystemWebProxy().IsBypassed([uri]"http://${BindHost}:$Port/") } catch { }
            if ($bypassed) {
                Write-Ok 'Le proxy système laisse passer 127.0.0.1 en direct'
            } elseif ($enabled) {
                $merged = Add-ListEntries ($override -replace ';', ',') @('<local>', 'localhost', '127.0.0.1', '[::1]')
                Set-ItemProperty -Path $key -Name ProxyOverride -Value ($merged.Value -replace ',', ';')
                Write-Action ("Proxy système : exceptions ajoutées pour {0} (adresses locales uniquement)" -f ($merged.Missing -join ', '))
            } else {
                Write-Warn "Le script de configuration proxy ($pac) envoie 127.0.0.1 au proxy : demandez à votre service informatique d'exclure les adresses locales."
            }
            Write-Info 'Chrome contourne de toute façon le proxy pour 127.0.0.1 et localhost.'
        } else {
            Write-Ok 'Pas de proxy système (paramètres Internet de Windows)'
        }
        $hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
        if (Test-Path -LiteralPath $hosts) {
            $redirects = @(Select-String -LiteralPath $hosts -Pattern '^\s*([^#\s]+)\s+(.*\s)?localhost(\s|$)' -ErrorAction SilentlyContinue |
                Where-Object { @('127.0.0.1', '::1') -notcontains $_.Matches[0].Groups[1].Value })
            if ($redirects.Count) { Write-Warn ("Fichier hosts : localhost redirigé ({0}). Utilisez http://127.0.0.1:$Port/" -f $redirects[0].Line.Trim()) }
        }
    }
    try {
        $addresses = @([System.Net.Dns]::GetHostAddresses('localhost') | ForEach-Object { $_.IPAddressToString })
        Write-Info ("localhost → {0} ; le serveur écoute sur $BindHost (IPv4), adresse à utiliser : http://${BindHost}:$Port/" -f ($addresses -join ', '))
    } catch {
        Write-Warn 'localhost ne se résout pas : utilisez http://127.0.0.1'
    }
}

# --------------------------------------------------------------------------- 3. port
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
    try { $listener.ExclusiveAddressUse = $true } catch { }
    try { $listener.Start(); return $true } catch { return $false } finally { try { $listener.Stop() } catch { } }
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

function Show-ExcludedRanges([int]$Port) {
    $ranges = (Invoke-Native -File 'netsh.exe' -Arguments @('interface', 'ipv4', 'show', 'excludedportrange', 'protocol=tcp')).Output
    foreach ($line in $ranges) {
        if ($line -match '^\s*(\d+)\s+(\d+)') {
            if ($Port -ge [int]$Matches[1] -and $Port -le [int]$Matches[2]) {
                Write-Warn "Le port $Port est réservé par Windows (plage $($Matches[1])-$($Matches[2]), Hyper-V / WSL / Docker)."
            }
        }
    }
}

function Clear-Port([int]$Port) {
    Write-Step "3. Port $Port"
    if (-not $OnWindows) {
        Write-Info 'Hors Windows : inventaire des processus non applicable, contrôle par test de réservation du port'
    } else {
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
                foreach ($orphan in $orphans) { Stop-ProcessTree $orphan.ProcessId "Worker Uvicorn orphelin qui gardait le port $Port ouvert (PID d'origine $($owner.ProcessId) disparu)" }
            } else {
                $foreign += "PID $($owner.ProcessId) (processus introuvable)"
            }
        } elseif (Test-FramatexServer $process) {
            $parent = Get-ProcessDetails $process.ParentProcessId
            $command = ([string]$process.CommandLine)
            if ($command.Length -gt 110) { $command = $command.Substring(0, 110) + '…' }
            if (Test-FramatexServer $parent) {
                # Superviseur --reload : l'arrêter aussi, sinon il relancerait un worker.
                Stop-ProcessTree $parent.ProcessId "Ancien superviseur Uvicorn --reload arrêté"
            }
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
        Write-Warn ("Le port {0} est utilisé par {1} : ce programme n'est pas FRAMATEX et n'a pas été arrêté." -f $Port, ($foreign -join ', '))
    } else {
        Write-Warn "Le port $Port ne peut pas être réservé."
        if ($OnWindows) { Show-ExcludedRanges $Port }
    }
    for ($candidate = $Port + 1; $candidate -le $Port + 20; $candidate++) {
        if (-not @(Get-PortOwners $candidate).Count -and (Test-PortBindable $candidate)) {
            Write-Action "FRAMATEX utilisera le port $candidate"
            return $candidate
        }
    }
    Stop-Launcher "Aucun port libre entre $Port et $($Port + 20)."
}

# --------------------------------------------------------------------------- 4. données
function Initialize-Data($Python) {
    Write-Step '4. Données (dossier data, SQLite, sauvegarde, migrations)'
    $result = Invoke-Native -File $Python.Exe -Arguments @((Join-RootPath @('scripts', 'windows_preflight.py')), 'db')
    $result.Output | ForEach-Object { Write-Host $_ }
    switch ($result.Code) {
        0 { return }
        2 { Stop-Launcher 'Base SQLite verrouillée par un autre programme : fermez-le puis relancez cette commande.' }
        3 { Stop-Launcher 'Dossier data non accessible en écriture (droits, antivirus ou synchronisation de fichiers).' }
        default { Stop-Launcher 'Contrôle des données en échec : voir le message ci-dessus.' }
    }
}

# --------------------------------------------------------------------------- 5. démarrage
function Disable-QuickEdit {
    if (-not $OnWindows) { return }
    try {
        if (-not ('FramatexConsole.Mode' -as [type])) {
            Add-Type -Namespace FramatexConsole -Name Mode -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr GetStdHandle(int nStdHandle);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
[DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@
        }
        $handle = [FramatexConsole.Mode]::GetStdHandle(-10)
        $mode = [uint32]0
        if (-not [FramatexConsole.Mode]::GetConsoleMode($handle, [ref]$mode)) { return }
        if ($mode -band 0x40) {
            # 0x40 = ENABLE_QUICK_EDIT_MODE, 0x80 = ENABLE_EXTENDED_FLAGS
            [void][FramatexConsole.Mode]::SetConsoleMode($handle, [uint32](($mode - 0x40) -bor 0x80))
            Write-Action "Édition rapide (QuickEdit) désactivée pour cette fenêtre : un clic dans la console ne peut plus geler le serveur"
        } else {
            Write-Ok 'Édition rapide (QuickEdit) déjà inactive dans cette fenêtre'
        }
    } catch {
        Write-Info "Mode de console non modifiable ici ($($_.Exception.Message))"
    }
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
    Write-Step '5. Démarrage du serveur'
    Disable-QuickEdit
    $arguments = @('-m', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', "$Port")
    if ($Reload) {
        $arguments += '--reload'
        Write-Info 'Mode --reload demandé : le port a été vérifié en accès exclusif avant le démarrage.'
    }
    Write-Info ("{0} {1}" -f $Python.Exe, ($arguments -join ' '))
    $env:PYTHONUNBUFFERED = '1'
    $script:Server = Start-Process -FilePath $Python.Exe -ArgumentList $arguments -WorkingDirectory $Root -NoNewWindow -PassThru
    $null = $script:Server.Handle   # conserve le code de sortie (Windows PowerShell 5.1)

    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if ($script:Server.HasExited) { Stop-Launcher "Uvicorn s'est arrêté (code $($script:Server.ExitCode)) : lisez son message ci-dessus." }
        $health = Invoke-Http "http://${BindHost}:$Port/api/health" 3
        if ($health.Ok -and $health.Status -eq 200) {
            Write-Ok ("Serveur prêt (PID {0}) : /api/health répond en {1} ms" -f $script:Server.Id, $health.Ms)
            return
        }
        Start-Sleep -Milliseconds 500
    }
    $owners = @(Get-PortOwners $Port | ForEach-Object { $_.ProcessId })
    if ($owners.Count -and $owners -notcontains $script:Server.Id) {
        Stop-Launcher ("Un autre processus ({0}) a pris le port $Port pendant le démarrage." -f ($owners -join ', '))
    }
    Stop-Launcher "Uvicorn tourne mais /api/health ne répond pas après 90 s ($($health.Error))."
}

# --------------------------------------------------------------------------- 6. vérifications
function Test-Platform([int]$Port) {
    Write-Step '6. Vérifications HTTP réelles (sans proxy)'
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
        $good = $r.Ok -and $r.Status -eq 200 -and $r.Type -eq $page.Type -and $r.Text.Contains($page.Marker)
        if ($good) {
            Write-Ok ("{0,-34} {1}  {2,5} ms  {3}" -f $page.Path, $r.Status, $r.Ms, $r.Type)
        } else {
            $failures++
            Write-Warn ("{0} : statut {1}, type '{2}' {3}" -f $page.Path, $r.Status, $r.Type, $r.Error)
        }
        foreach ($match in [regex]::Matches($r.Text, '(?:href|src)="(/assets/[^"?#]+\.(?:css|js))"')) {
            if (-not $assets.Contains($match.Groups[1].Value)) { $assets.Add($match.Groups[1].Value) }
        }
    }
    foreach ($extra in '/assets/landing/logo-framatex.jpg', '/assets/brand/fonts/dm-sans-latin-400-normal.woff2') { $assets.Add($extra) }
    $expected = @{ '.css' = @('text/css'); '.js' = @('text/javascript', 'application/javascript'); '.jpg' = @('image/jpeg'); '.woff2' = @('font/woff2') }
    foreach ($asset in $assets) {
        $r = Invoke-Http ($base + $asset)
        $types = $expected[[System.IO.Path]::GetExtension($asset)]
        if ($r.Ok -and $r.Status -eq 200 -and $types -contains $r.Type) {
            Write-Ok ("{0,-34} {1}  {2,5} ms  {3}" -f $asset, $r.Status, $r.Ms, $r.Type)
        } else {
            $failures++
            Write-Warn ("{0} : statut {1}, type '{2}' (attendu {3}) {4}" -f $asset, $r.Status, $r.Type, ($types -join ' ou '), $r.Error)
        }
    }

    if ($OnWindows -and (Get-Command Test-NetConnection -ErrorAction SilentlyContinue)) {
        $tcp = Test-NetConnection -ComputerName $BindHost -Port $Port -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { Write-Ok "Test-NetConnection ${BindHost}:$Port : port joignable" }
        else { $failures++; Write-Warn "Test-NetConnection ${BindHost}:$Port : échec" }
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
                else { $failures++; Write-Warn ("{0} http://{1}:{2}/api/health → code curl {3} {4}" -f $variant.Label, $hostName, $Port, $result.Code, $answer) }
            }
        }
    }
    return $failures
}

# --------------------------------------------------------------------------- programme principal
function Invoke-Launcher {
    Set-Location -LiteralPath $Root
    Add-Type -AssemblyName System.Net.Http
    Show-Context
    $python = Initialize-Python
    Test-LocalNetwork
    $port = Clear-Port $Port
    Initialize-Data $python
    Start-Server $python $port
    $failures = Test-Platform $port

    Write-Step 'Résumé'
    if ($script:Actions.Count) { Write-Host '  Corrections effectuées :'; $script:Actions | ForEach-Object { Write-Host "    - $_" } }
    if ($script:Warnings.Count) { Write-Host '  Points signalés :'; $script:Warnings | ForEach-Object { Write-Host "    - $_" } }
    if ($failures) { Write-Host "  $failures vérification(s) en échec." -ForegroundColor Red }
    else { Write-Host '  Toutes les vérifications sont passées.' -ForegroundColor Green }
    $url = "http://${BindHost}:$port/"
    Write-Host ''
    Write-Host "  FRAMATEX : $url" -ForegroundColor Green

    if ($CheckOnly) { return $failures }
    if (-not $NoBrowser) {
        if ($OnWindows) { Start-Process $url; Write-Action "Navigateur ouvert sur $url" }
        else { Write-Info "Ouvrez $url dans votre navigateur" }
    }
    Write-Host '  Serveur en marche dans cette fenêtre. Ctrl+C pour l''arrêter.' -ForegroundColor Cyan
    Wait-Process -Id $script:Server.Id
    return 0
}

if ($MyInvocation.InvocationName -eq '.') { return }   # chargement des fonctions pour les tests

$transcript = $null
try {
    $logs = Join-RootPath @('data', 'logs')
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $transcript = [System.IO.Path]::Combine($logs, ('start-windows-{0:yyyyMMdd-HHmmss}.log' -f (Get-Date)))
    Start-Transcript -LiteralPath $transcript | Out-Null
} catch {
    $transcript = $null
}

$exitCode = 1
try {
    $exitCode = [int](@(Invoke-Launcher)[-1])
} catch {
    if ("$_" -notlike 'FRAMATEX_STOP:*') {
        Write-Host "  [ÉCHEC] Erreur inattendue : $_" -ForegroundColor Red
        Write-Host $_.ScriptStackTrace
    }
    $exitCode = 1
} finally {
    if ($script:Server -and -not $script:Server.HasExited) {
        if (-not $script:Server.WaitForExit(5000)) {
            $null = Invoke-Native -File 'taskkill.exe' -Arguments @('/PID', "$($script:Server.Id)", '/T', '/F')
            if (-not $OnWindows) { try { $script:Server.Kill($true) } catch { } }
        }
        Write-Host '  Serveur arrêté.'
    }
    if ($transcript) {
        try { Stop-Transcript | Out-Null } catch { }
        Write-Host "  Journal du diagnostic : $transcript"
    }
}
exit $exitCode

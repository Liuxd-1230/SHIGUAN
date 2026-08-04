param(
    [switch]$NoBrowser,
    [switch]$SkipInstall,
    [switch]$ForceRebuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerDir = Join-Path $ProjectRoot "apps\server"
$WebDir = Join-Path $ProjectRoot "apps\web"
$ReaderDir = Join-Path $ProjectRoot "tools\ck3-reader"
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$StateFile = Join-Path $RuntimeDir "shiguan-processes.json"

$ServerPort = 8000
$WebPort = 5173
$ServerUrl = "http://127.0.0.1:$ServerPort"
$WebUrl = "http://127.0.0.1:$WebPort"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Fail([string]$Message) {
    throw $Message
}

function Get-CommandPath([string[]]$Names) {
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $ProjectRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            Fail "命令执行失败（退出码 $LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-FileSha256([string]$Path) {
    if (-not (Test-Path $Path)) { return "" }
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash
}

function Quote-ProcessArg([string]$Arg) {
    if ($Arg -match '[\s"]') {
        return '"' + ($Arg -replace '"', '\"') + '"'
    }
    return $Arg
}

function Start-BackgroundProcess {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [Parameter(Mandatory=$true)][string]$StdOut,
        [Parameter(Mandatory=$true)][string]$StdErr
    )

    $argLine = (($Arguments | ForEach-Object { Quote-ProcessArg $_ }) -join " ")
    return Start-Process `
        -FilePath $FilePath `
        -ArgumentList $argLine `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr `
        -WindowStyle Hidden `
        -PassThru
}

function Get-PortOwnerPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    }
    catch {}

    try {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                return [int]$Matches[1]
            }
        }
    }
    catch {}
    return $null
}

function Test-ServerReady {
    try {
        $response = Invoke-WebRequest -Uri "$ServerUrl/api/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ne 200) { return $false }
        $body = $response.Content | ConvertFrom-Json
        return $body.status -eq "ok"
    }
    catch { return $false }
}

function Test-WebReady {
    try {
        # Vite is considered ready once it answers successfully.
        # Do not require a fixed HTML title: local source changes, an error overlay,
        # or encoding differences must not make the launcher wait forever.
        $response = Invoke-WebRequest `
            -Uri $WebUrl `
            -UseBasicParsing `
            -TimeoutSec 5 `
            -Headers @{ "Cache-Control" = "no-cache" }
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        return $false
    }
}

function Show-LogTail {
    param(
        [string]$Path,
        [string]$Label,
        [int]$Lines = 40
    )
    if (-not $Path -or -not (Test-Path $Path)) {
        return
    }
    Write-Host ""
    Write-Host "----- $Label（最后 $Lines 行）-----" -ForegroundColor Yellow
    try {
        Get-Content -Path $Path -Tail $Lines -ErrorAction Stop | ForEach-Object {
            Write-Host $_
        }
    }
    catch {
        Write-Host "无法读取日志：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

function Wait-UntilReady {
    param(
        [Parameter(Mandatory=$true)][scriptblock]$Probe,
        [Parameter(Mandatory=$true)][string]$Name,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Probe) { return }
        if ($Process -and $Process.HasExited) {
            Fail "$Name 已提前退出（退出码 $($Process.ExitCode)）。请查看 data\runtime\logs。"
        }
        Start-Sleep -Milliseconds 500
    }
    Fail "等待 $Name 就绪超时。请查看 data\runtime\logs。"
}

function Test-ReaderNeedsBuild([string]$ExePath) {
    if ($ForceRebuild -or -not (Test-Path $ExePath)) { return $true }

    $exeTime = (Get-Item $ExePath).LastWriteTimeUtc
    $inputs = @()
    foreach ($path in @(
        (Join-Path $ReaderDir "Cargo.toml"),
        (Join-Path $ReaderDir "Cargo.lock"),
        (Join-Path $ReaderDir "build.rs")
    )) {
        if (Test-Path $path) { $inputs += Get-Item $path }
    }
    foreach ($dir in @((Join-Path $ReaderDir "src"), (Join-Path $ReaderDir "tokens"))) {
        if (Test-Path $dir) { $inputs += Get-ChildItem -Path $dir -Recurse -File }
    }
    foreach ($input in $inputs) {
        if ($input.LastWriteTimeUtc -gt $exeTime) { return $true }
    }
    return $false
}

function Resolve-TokenTable {
    # 与 tools/ck3-reader/build.sh 保持一致的令牌表选择：
    # 优先真实表（tXXXX 占位表会让字段名不可读），缺失时回退占位表并明确警告。
    # 这是"一键启动"的关键：ck3save 的 build.rs 只在环境变量
    # CK3_IRONMAN_TOKENS 指向令牌表时，才把 token-id -> 名称映射编译进二进制；
    # 不带该变量构建会在 melt 真实二进制存档时把未知 key 整段跳过（25 字节 header）。
    $real = Join-Path $ReaderDir "tokens\ck3_tokens_real.txt"
    $placeholder = Join-Path $ReaderDir "tokens\ck3_tokens.txt"
    if (Test-Path $real) { return $real }
    if (Test-Path $placeholder) { return $placeholder }
    return $null
}

function Get-ShiguanWebProcesses {
    # 只匹配严格属于本项目 apps\web 的进程：
    #  - esbuild.exe 的完整路径等于本项目 node_modules 下的那个；
    #  - node.exe 的命令行包含本项目 web 目录（vite dev server）；
    #  - node.exe 是本项目 esbuild.exe 的祖先（相对路径启动的 vite 也命中）。
    # 路径/祖先链不符的任何进程一律不匹配，绝不误停其他项目/程序。
    $webNormalized = [System.IO.Path]::GetFullPath($WebDir).TrimEnd('\')
    $esbuildExe = Join-Path $WebDir "node_modules\@esbuild\win32-x64\esbuild.exe"
    $result = @()

    $all = @()
    try { $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) } catch {}

    $parentById = @{}
    foreach ($p in $all) {
        $parentById[[string]$p.ProcessId] = [int64]$p.ParentProcessId
    }

    foreach ($p in $all) {
        $exe = [string]$p.ExecutablePath
        $cmd = [string]$p.CommandLine

        $isExactEsbuild = $exe -and (
            [System.IO.Path]::GetFullPath($exe).Equals(
                [System.IO.Path]::GetFullPath($esbuildExe),
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
        if ($isExactEsbuild) {
            $result += $p
            # 沿祖先链向上最多 4 跳：把本项目 esbuild 的 node 祖先一并纳入。
            $walker = [string]$p.ProcessId
            for ($hop = 0; $hop -lt 4; $hop++) {
                if (-not $parentById.ContainsKey($walker)) { break }
                $pidParent = $parentById[$walker]
                if ($pidParent -le 0) { break }
                foreach ($q in $all) {
                    if ([int64]$q.ProcessId -ne $pidParent) { continue }
                    if ($q.Name -ieq "node.exe") { $result += $q }
                    $walker = [string]$q.ProcessId
                    break
                }
            }
            continue
        }

        $isProjectNode = (
            $p.Name -ieq "node.exe" -and
            $cmd -and
            $cmd.IndexOf($webNormalized, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        )
        if ($isProjectNode) {
            $result += $p
        }
    }
    return @($result | Select-Object -Unique)
}

function Stop-StaleShiguanWebProcesses {
    $procs = @(Get-ShiguanWebProcesses)
    if ($procs.Count -eq 0) { return }

    Write-Host "发现占用本项目 node_modules 的旧进程，将只停止 SHIGUAN 前端相关进程：" -ForegroundColor Yellow
    foreach ($p in $procs) {
        Write-Host ("  PID {0}  {1}" -f $p.ProcessId, $p.Name)
    }

    # Child esbuild first, then Node.
    foreach ($p in @($procs | Sort-Object @{Expression={ if ($_.Name -ieq "esbuild.exe") { 0 } else { 1 } }})) {
        try {
            Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue
        }
        catch {}
    }
    Start-Sleep -Milliseconds 1000
}

function Test-NpmTree([string]$NpmExe) {
    Push-Location $WebDir
    try {
        & $NpmExe "ls" "--depth=0" "--silent" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
    finally { Pop-Location }
}

$startedServer = $null
$startedWeb = $null

try {
    Write-Host "史官 SHIGUAN - Windows 一键启动（v5）" -ForegroundColor Yellow
    Write-Host "项目目录：$ProjectRoot"

    foreach ($required in @($ServerDir, $WebDir, $ReaderDir)) {
        if (-not (Test-Path $required)) {
            Fail "项目结构不完整，缺少目录：$required`n请把启动脚本放在 SHIGUAN 项目根目录。"
        }
    }

    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    # Detect already-running services before touching dependencies.
    $reuseServer = $false
    $reuseWeb = $false

    $serverOwner = Get-PortOwnerPid $ServerPort
    if ($serverOwner) {
        if (Test-ServerReady) {
            $reuseServer = $true
            Write-Ok "检测到已有 SHIGUAN 后端，稍后直接复用（PID $serverOwner）"
        }
        else {
            Fail "端口 $ServerPort 已被其他程序占用（PID $serverOwner），且不是可识别的 SHIGUAN 后端。"
        }
    }

    $webOwner = Get-PortOwnerPid $WebPort
    if ($webOwner) {
        if (Test-WebReady) {
            $reuseWeb = $true
            Write-Ok "检测到已有 SHIGUAN 前端，跳过依赖更新并直接复用（PID $webOwner）"
        }
        else {
            Fail "端口 $WebPort 已被其他程序占用（PID $webOwner），且不是可识别的 SHIGUAN 前端。"
        }
    }

    # -------------------------------------------------------------------------
    # Python environment
    # -------------------------------------------------------------------------
    if (-not $reuseServer) {
        Write-Step "检查 Python 后端环境"

        $VenvDir = Join-Path $ServerDir ".venv"
        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
        $Requirements = Join-Path $ServerDir "requirements.txt"
        $RequirementsStamp = Join-Path $VenvDir ".shiguan-requirements.sha256"

        if (-not (Test-Path $VenvPython)) {
            if ($SkipInstall) { Fail "未找到后端虚拟环境：$VenvPython" }

            $PyLauncher = Get-CommandPath @("py.exe")
            $PythonExe = Get-CommandPath @("python.exe", "python")
            if ($PyLauncher) {
                Invoke-NativeChecked -FilePath $PyLauncher -Arguments @("-3", "-m", "venv", $VenvDir)
            }
            elseif ($PythonExe) {
                Invoke-NativeChecked -FilePath $PythonExe -Arguments @("-m", "venv", $VenvDir)
            }
            else {
                Fail "未找到 Python 3。请安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。"
            }
        }

        $requirementsHash = Get-FileSha256 $Requirements
        $savedRequirementsHash = ""
        if (Test-Path $RequirementsStamp) {
            $savedRequirementsHash = (Get-Content $RequirementsStamp -Raw).Trim()
        }

        $pythonImportsOk = $false
        try {
            & $VenvPython -c "import fastapi, uvicorn, pydantic, multipart" 2>$null
            $pythonImportsOk = ($LASTEXITCODE -eq 0)
        }
        catch { $pythonImportsOk = $false }

        if (-not $SkipInstall -and (
            -not $pythonImportsOk -or
            $requirementsHash -ne $savedRequirementsHash
        )) {
            $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
            Invoke-NativeChecked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", $Requirements) -WorkingDirectory $ServerDir
            Set-Content -Path $RequirementsStamp -Value $requirementsHash -Encoding ASCII
        }
        Write-Ok "Python 后端环境可用"
    }

    # -------------------------------------------------------------------------
    # Web environment. Do not run npm ci over a healthy existing node_modules.
    # -------------------------------------------------------------------------
    if (-not $reuseWeb) {
        Write-Step "检查 Node.js 前端环境"

        $NodeExe = Get-CommandPath @("node.exe", "node")
        $NpmExe = Get-CommandPath @("npm.cmd", "npm")
        if (-not $NodeExe -or -not $NpmExe) {
            Fail "未找到 Node.js/npm。请安装 Node.js 20 或更高版本。"
        }

        $PackageLock = Join-Path $WebDir "package-lock.json"
        $NodeModules = Join-Path $WebDir "node_modules"
        $ViteJs = Join-Path $NodeModules "vite\bin\vite.js"
        $LockStamp = Join-Path $NodeModules ".shiguan-package-lock.sha256"

        $lockHash = Get-FileSha256 $PackageLock
        $savedLockHash = ""
        if (Test-Path $LockStamp) {
            $savedLockHash = (Get-Content $LockStamp -Raw).Trim()
        }

        $viteExists = Test-Path $ViteJs
        $treeOk = $false
        if ($viteExists) {
            $treeOk = Test-NpmTree $NpmExe
        }

        if ($viteExists -and $treeOk -and -not $savedLockHash) {
            # Existing checkout already has a valid dependency tree. Adopt it instead of
            # destructively running npm ci and trying to unlink a live esbuild.exe.
            Set-Content -Path $LockStamp -Value $lockHash -Encoding ASCII
            $savedLockHash = $lockHash
            Write-Ok "现有 node_modules 可用，已建立依赖版本标记，无需重装"
        }

        $needsInstall = (-not $viteExists) -or (-not $treeOk) -or ($lockHash -ne $savedLockHash)
        if ($needsInstall) {
            if ($SkipInstall) {
                Fail "前端依赖不存在、不完整或 package-lock.json 已变化。请去掉 -SkipInstall 后重试。"
            }

            Stop-StaleShiguanWebProcesses

            if (-not (Test-Path $NodeModules)) {
                Write-Host "首次安装前端依赖（npm ci）..."
                Invoke-NativeChecked -FilePath $NpmExe -Arguments @("ci", "--no-audit", "--no-fund") -WorkingDirectory $WebDir
            }
            else {
                Write-Host "增量更新前端依赖（npm install，避免删除被锁定的 esbuild.exe）..."
                Invoke-NativeChecked -FilePath $NpmExe -Arguments @("install", "--no-audit", "--no-fund") -WorkingDirectory $WebDir
            }

            if (-not (Test-Path $ViteJs)) {
                Fail "npm 完成后仍未找到 Vite：$ViteJs"
            }
            Set-Content -Path $LockStamp -Value $lockHash -Encoding ASCII
        }

        Write-Ok "Node.js 前端环境可用"
    }

    # -------------------------------------------------------------------------
    # Rust reader only needed when starting a new backend.
    # -------------------------------------------------------------------------
    if (-not $reuseServer) {
        Write-Step "检查 CK3 Rust 解析器"

        $ReaderExe = Join-Path $ReaderDir "target\release\ck3-reader.exe"
        if (Test-ReaderNeedsBuild $ReaderExe) {
            $CargoExe = Get-CommandPath @("cargo.exe", "cargo")
            if (-not $CargoExe) {
                Fail "ck3-reader 尚未构建或源码已更新，但未找到 Rust/Cargo。请安装 rustup。"
            }

            $tokenTable = Resolve-TokenTable
            if (-not $tokenTable) {
                Fail "缺少 ck3-reader 令牌表：tools\ck3-reader\tokens\ 下既没有 ck3_tokens_real.txt 也没有 ck3_tokens.txt。"
            }
            if ($tokenTable.EndsWith("ck3_tokens_real.txt", [System.StringComparison]::OrdinalIgnoreCase)) {
                Write-Host "  使用真实令牌表构建（字段名可读）：$tokenTable" -ForegroundColor DarkGray
            }
            else {
                Write-Host "  警告：使用占位令牌表构建（字段名为 tXXXX，真实存档字段名不可读）。" -ForegroundColor Yellow
                Write-Host "  如需真实字段名，请先运行：python tools\ck3-reader\extract_tokens.py --verify" -ForegroundColor Yellow
            }

            # 关键：必须携带 CK3_IRONMAN_TOKENS 构建（与 build.sh 一致）。
            # 否则 ck3save 编译进空 EnvTokens，真实二进制存档 melt 只会输出 25 字节 header。
            $env:CK3_IRONMAN_TOKENS = $tokenTable
            try {
                Invoke-NativeChecked -FilePath $CargoExe -Arguments @("build", "--release") -WorkingDirectory $ReaderDir
            }
            finally {
                Remove-Item Env:\CK3_IRONMAN_TOKENS -ErrorAction SilentlyContinue
            }
        }
        if (-not (Test-Path $ReaderExe)) {
            Fail "ck3-reader 编译后仍未生成：$ReaderExe"
        }
        Write-Ok "CK3 解析器可用"
    }

    # -------------------------------------------------------------------------
    # Start backend
    # -------------------------------------------------------------------------
    if (-not $reuseServer) {
        Write-Step "启动 FastAPI 后端"

        $serverOut = Join-Path $LogDir "server.out.log"
        $serverErr = Join-Path $LogDir "server.err.log"
        Remove-Item $serverOut, $serverErr -Force -ErrorAction SilentlyContinue

        $startedServer = Start-BackgroundProcess `
            -FilePath $VenvPython `
            -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ServerPort") `
            -WorkingDirectory $ServerDir `
            -StdOut $serverOut `
            -StdErr $serverErr

        Wait-UntilReady -Probe ${function:Test-ServerReady} -Name "FastAPI 后端" -Process $startedServer -TimeoutSeconds 60
        Write-Ok "后端已启动：$ServerUrl（PID $($startedServer.Id)）"
    }

    # -------------------------------------------------------------------------
    # Start web
    # -------------------------------------------------------------------------
    if (-not $reuseWeb) {
        Write-Step "启动 Vite 前端"

        $webOut = Join-Path $LogDir "web.out.log"
        $webErr = Join-Path $LogDir "web.err.log"
        Remove-Item $webOut, $webErr -Force -ErrorAction SilentlyContinue

        $startedWeb = Start-BackgroundProcess `
            -FilePath $NodeExe `
            -Arguments @($ViteJs, "--host", "127.0.0.1", "--port", "$WebPort", "--strictPort") `
            -WorkingDirectory $WebDir `
            -StdOut $webOut `
            -StdErr $webErr

        try {
            Wait-UntilReady `
                -Probe ${function:Test-WebReady} `
                -Name "Vite 前端" `
                -Process $startedWeb `
                -TimeoutSeconds 90
        }
        catch {
            Show-LogTail -Path $webOut -Label "web.out.log"
            Show-LogTail -Path $webErr -Label "web.err.log"
            throw
        }
        Write-Ok "前端已启动：$WebUrl（PID $($startedWeb.Id)）"
    }

    $state = [ordered]@{
        projectRoot = $ProjectRoot
        startedAt = (Get-Date).ToString("o")
        server = $null
        web = $null
    }
    if ($startedServer) {
        $state.server = [ordered]@{
            pid = $startedServer.Id
            executable = $VenvPython
            marker = "app.main:app"
            port = $ServerPort
            startedAt = $startedServer.StartTime.ToString("o")
        }
    }
    if ($startedWeb) {
        $state.web = [ordered]@{
            pid = $startedWeb.Id
            executable = $NodeExe
            marker = $ViteJs
            port = $WebPort
            startedAt = $startedWeb.StartTime.ToString("o")
        }
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -Path $StateFile -Encoding UTF8

    Write-Host ""
    Write-Host "史官 SHIGUAN 已就绪：" -ForegroundColor Green
    Write-Host "  前端：$WebUrl"
    Write-Host "  后端：$ServerUrl/api/health"
    Write-Host "  日志：$LogDir"
    Write-Host "  停止：双击 stop.bat"

    if (-not $NoBrowser) {
        Start-Process $WebUrl | Out-Null
    }
}
catch {
    Write-Host ""
    Write-Host "[启动失败] $($_.Exception.Message)" -ForegroundColor Red

    foreach ($proc in @($startedWeb, $startedServer)) {
        if ($proc -and -not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
            catch {}
        }
    }

    if (Test-Path (Join-Path $LogDir "web.out.log")) {
        Show-LogTail -Path (Join-Path $LogDir "web.out.log") -Label "web.out.log"
    }
    if (Test-Path (Join-Path $LogDir "web.err.log")) {
        Show-LogTail -Path (Join-Path $LogDir "web.err.log") -Label "web.err.log"
    }
    if (Test-Path (Join-Path $LogDir "server.err.log")) {
        Show-LogTail -Path (Join-Path $LogDir "server.err.log") -Label "server.err.log"
    }

    Write-Host "详细日志位于：$LogDir" -ForegroundColor Yellow
    exit 1
}

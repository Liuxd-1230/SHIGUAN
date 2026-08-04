$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebDir = Join-Path $ProjectRoot "apps\web"
$StateFile = Join-Path $ProjectRoot "data\runtime\shiguan-processes.json"

function Get-AllProcessInfo {
    # Avoid Win32_Process -Filter because some Windows PowerShell/CIM
    # combinations can report a localized "parameter type mismatch".
    try {
        return @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    }
    catch {
        try {
            return @(Get-WmiObject -Class Win32_Process -ErrorAction Stop)
        }
        catch {
            throw "无法读取 Windows 进程信息：$($_.Exception.Message)"
        }
    }
}

function Get-ProcessInfoByPid {
    param(
        [Parameter(Mandatory=$true)][int]$ProcessId,
        [Parameter(Mandatory=$true)][object[]]$AllProcesses
    )

    return @(
        $AllProcesses |
            Where-Object { [int64]$_.ProcessId -eq [int64]$ProcessId } |
            Select-Object -First 1
    )
}

function Get-DescendantProcessIds {
    param(
        [Parameter(Mandatory=$true)][int]$RootProcessId,
        [Parameter(Mandatory=$true)][object[]]$AllProcesses
    )

    # Iterative breadth-first traversal. Store depth so children are stopped
    # before their parents. This is compatible with Windows PowerShell 5.1.
    $queue = New-Object System.Collections.ArrayList
    $found = New-Object System.Collections.ArrayList
    $seen = @{}

    [void]$queue.Add([pscustomobject]@{
        ProcessId = [int]$RootProcessId
        Depth = 0
    })

    while ($queue.Count -gt 0) {
        $current = $queue[0]
        $queue.RemoveAt(0)

        $parentId = [int]$current.ProcessId
        $nextDepth = [int]$current.Depth + 1

        foreach ($child in @($AllProcesses | Where-Object {
            [int64]$_.ParentProcessId -eq [int64]$parentId
        })) {
            $childId = [int]$child.ProcessId
            $key = [string]$childId

            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                $item = [pscustomobject]@{
                    ProcessId = $childId
                    Depth = $nextDepth
                }
                [void]$found.Add($item)
                [void]$queue.Add($item)
            }
        }
    }

    return @(
        $found |
            Sort-Object -Property @{ Expression = { $_.Depth }; Descending = $true } |
            ForEach-Object { [int]$_.ProcessId }
    )
}

function Stop-RecordedProcess {
    param(
        $Record,
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][object[]]$AllProcesses
    )

    if ($null -eq $Record -or $null -eq $Record.pid) {
        return
    }

    $pidValue = [int]$Record.pid
    $matches = @(Get-ProcessInfoByPid -ProcessId $pidValue -AllProcesses $AllProcesses)

    if ($matches.Count -eq 0) {
        Write-Host "$Name 已停止（PID $pidValue 不存在）。"
        return
    }

    $procInfo = $matches[0]
    $commandLine = [string]$procInfo.CommandLine
    $marker = [string]$Record.marker

    if ([string]::IsNullOrWhiteSpace($marker)) {
        Write-Host "拒绝停止 $Name：进程记录缺少安全校验标记。" -ForegroundColor Yellow
        return
    }

    if (
        [string]::IsNullOrWhiteSpace($commandLine) -or
        $commandLine.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase) -lt 0
    ) {
        Write-Host "拒绝停止 $Name：PID $pidValue 的命令行与启动记录不匹配。" -ForegroundColor Yellow
        Write-Host "这通常表示 PID 已被其他程序复用；不会结束该进程。" -ForegroundColor Yellow
        return
    }

    $descendants = @(
        Get-DescendantProcessIds `
            -RootProcessId $pidValue `
            -AllProcesses $AllProcesses
    )

    foreach ($childId in $descendants) {
        try {
            Stop-Process -Id ([int]$childId) -ErrorAction SilentlyContinue
        }
        catch {
        }
    }

    try {
        Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
    }
    catch {
    }

    Start-Sleep -Milliseconds 800

    # Escalate only for the already verified SHIGUAN root and its descendants.
    foreach ($id in @($descendants + @($pidValue))) {
        if (Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue) {
            try {
                Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue
            }
            catch {
            }
        }
    }

    Write-Host "$Name 已停止。" -ForegroundColor Green
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

function Stop-StrayShiguanWebProcesses {
    # 兜底：清理未被状态记录覆盖的本项目前端进程（例如手动启动的 vite，
    # 或状态文件缺失时的遗留）。只处理上面 Get-ShiguanWebProcesses 已严格
    # 圈定的进程；没有找到时不输出任何干扰信息。
    $procs = @(Get-ShiguanWebProcesses)
    if ($procs.Count -eq 0) { return }

    Write-Host "发现本项目残留的前端进程，正在停止：" -ForegroundColor Yellow
    foreach ($p in $procs) {
        Write-Host ("  PID {0}  {1}" -f $p.ProcessId, $p.Name)
        try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue }
        catch {}
    }
    Start-Sleep -Milliseconds 1000
    foreach ($p in $procs) {
        if (Get-Process -Id ([int]$p.ProcessId) -ErrorAction SilentlyContinue) {
            try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue }
            catch {}
        }
    }
    Write-Host "残留前端进程已清理。" -ForegroundColor Green
}

function Get-ShiguanServerProcesses {
    # 只匹配严格属于本项目后端的进程：命令行含本项目的 uvicorn 应用标记
    # app.main:app 且含项目 apps\server 目录。ExecutablePath 可能因 venv
    # shim 指到基础 Python，故以命令行双条件圈定，绝不误停其他 Python 进程。
    $serverPathMark = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + "\apps\server"
    $result = @()
    try {
        foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $cmd = [string]$p.CommandLine
            if (-not $cmd) { continue }
            $isProjectServer = (
                $cmd.IndexOf("app.main:app", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $cmd.IndexOf($serverPathMark, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
            )
            if ($isProjectServer) { $result += $p }
        }
    }
    catch {}
    return $result
}

function Stop-StrayShiguanServerProcesses {
    # 兜底：清理未被状态记录覆盖的本项目后端进程（手动启动、状态文件缺失、
    # 或 stop 中途失败遗留的 uvicorn）。只处理上面严格圈定的进程。
    $procs = @(Get-ShiguanServerProcesses)
    if ($procs.Count -eq 0) { return }

    Write-Host "发现本项目残留的后端进程，正在停止：" -ForegroundColor Yellow
    foreach ($p in $procs) {
        Write-Host ("  PID {0}  {1}" -f $p.ProcessId, $p.Name)
        try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue }
        catch {}
    }
    Start-Sleep -Milliseconds 1000
    foreach ($p in $procs) {
        if (Get-Process -Id ([int]$p.ProcessId) -ErrorAction SilentlyContinue) {
            try { Stop-Process -Id ([int]$p.ProcessId) -Force -ErrorAction SilentlyContinue }
            catch {}
        }
    }
    Write-Host "残留后端进程已清理。" -ForegroundColor Green
}

$hadState = Test-Path $StateFile
if ($hadState) {
    try {
        $state = Get-Content -Path $StateFile -Raw -ErrorAction Stop | ConvertFrom-Json
        $allProcesses = @(Get-AllProcessInfo)

        Stop-RecordedProcess `
            -Record $state.web `
            -Name "SHIGUAN 前端" `
            -AllProcesses $allProcesses

        # Refresh process information after the frontend has stopped.
        $allProcesses = @(Get-AllProcessInfo)

        Stop-RecordedProcess `
            -Record $state.server `
            -Name "SHIGUAN 后端" `
            -AllProcesses $allProcesses

        Remove-Item -Path $StateFile -Force -ErrorAction SilentlyContinue
    }
    catch {
        Write-Host "[停止失败] $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "进程记录文件：$StateFile" -ForegroundColor Yellow
        exit 1
    }
}
else {
    Write-Host "没有找到本启动器创建的进程记录，改为扫描本项目残留前端进程。" -ForegroundColor Yellow
}

Stop-StrayShiguanWebProcesses
Stop-StrayShiguanServerProcesses
Write-Host "SHIGUAN 已停止。" -ForegroundColor Green

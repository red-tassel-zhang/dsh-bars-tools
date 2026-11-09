<#
.SYNOPSIS
  在本机彻底删除某段会话的数据（归档以 git 仓库为准）。

.DESCRIPTION
  默认只打印将要删除的内容。确认无误后加 -Execute 真删。
  删除前会检查：工作区无未提交改动、HEAD 已推到远端。
  默认先打一个 zip 到桌面，加 -NoBackup 可跳过。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\archive-and-delete.ps1 -SessionId session-0123abcd...
  powershell -ExecutionPolicy Bypass -File tools\archive-and-delete.ps1 -SessionId session-0123abcd... -Execute
#>
param(
  [Parameter(Mandatory = $true)][string]$SessionId,
  [string]$WorkspacePath = (Get-Location).Path,
  [switch]$Execute,
  [switch]$NoBackup
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dshHome = $env:DSH_HOME
if (-not $dshHome) { $dshHome = Join-Path $env:USERPROFILE ".dsh" }
$slug = "--" + ($WorkspacePath.TrimEnd('\') -replace ':\\', '-' -replace '\\', '-') + "--"
$sessionDir = Join-Path $dshHome "sessions\$slug\$SessionId"

Push-Location $repo
try {
  $dirty = git status --porcelain
  if ($dirty) { Write-Error "工作区有未提交改动，先 commit / push：`n$dirty" }
  git fetch --quiet 2>$null
  $local = git rev-parse HEAD
  $remote = git rev-parse "origin/main" 2>$null
  if ($local -ne $remote) { Write-Error "HEAD（$local）与 origin/main（$remote）不一致，先 push。" }
  Write-Host "[ok] 仓库已同步：$local"
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "将删除："
Write-Host "  $sessionDir"
if (-not (Test-Path $sessionDir)) {
  Write-Host "  （不存在，可能已删过）"
  return
}
$size = (Get-ChildItem $sessionDir -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("  大小 {0:N2} MB" -f ($size / 1MB))

if (-not $Execute) {
  Write-Host ""
  Write-Host "以上为预演。确认后加 -Execute："
  Write-Host "  powershell -ExecutionPolicy Bypass -File tools\archive-and-delete.ps1 -SessionId $SessionId -Execute"
  return
}

if (-not $NoBackup) {
  $zip = Join-Path ([Environment]::GetFolderPath("Desktop")) ("dsh-session-{0}.zip" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
  Compress-Archive -Path (Join-Path $sessionDir "*") -DestinationPath $zip -Force
  Write-Host "[ok] 本机备份 -> $zip"
}

Remove-Item -Recurse -Force $sessionDir
Write-Host "[ok] 已删除会话目录"

$parent = Split-Path -Parent $sessionDir
if ((Get-ChildItem $parent -Force | Measure-Object).Count -eq 0) {
  Remove-Item -Force $parent
  Write-Host "[ok] 已删除空的 slug 目录"
}
Write-Host ""
Write-Host "完成。恢复流程见 RESTORE.md。"

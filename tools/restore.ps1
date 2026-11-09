<#
.SYNOPSIS
  把仓库里的会话存档放回 DSH 的会话目录。

.DESCRIPTION
  DSH 用「工作区路径」算出一个 slug 目录，会话文件按 session id 存在里面。
  本脚本算出目录、把存档放回去，可选再把技能装进 %DSH_HOME%\skills。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\restore.ps1 -SessionId session-0123abcd...
  powershell -ExecutionPolicy Bypass -File tools\restore.ps1 -SessionId session-0123abcd... -WorkspacePath "D:\work\my-project"
#>
param(
  [Parameter(Mandatory = $true)][string]$SessionId,
  [string]$WorkspacePath = (Get-Location).Path,
  [string]$Archive,
  [string]$Skill
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dshHome = $env:DSH_HOME
if (-not $dshHome) { $dshHome = Join-Path $env:USERPROFILE ".dsh" }

if (-not $Archive) {
  $Archive = Get-ChildItem (Join-Path $repo "memory\session") -Filter "*.jsonl.zstd" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Archive -or -not (Test-Path $Archive)) {
  Write-Error "找不到会话存档：$Archive"
}

$slug = "--" + ($WorkspacePath.TrimEnd('\') -replace ':\\', '-' -replace '\\', '-') + "--"
$destDir = Join-Path $dshHome "sessions\$slug\$SessionId"

Write-Host "DSH_HOME : $dshHome"
Write-Host "workspace: $WorkspacePath"
Write-Host "slug     : $slug"

New-Item -ItemType Directory -Force -Path $destDir | Out-Null
Copy-Item $Archive (Join-Path $destDir "session.v4.jsonl.zstd") -Force
Write-Host "[ok] 会话存档 -> $destDir"

if ($Skill -and (Test-Path $Skill)) {
  $name = [System.IO.Path]::GetFileNameWithoutExtension($Skill)
  $skillDst = Join-Path $dshHome "skills\$name"
  New-Item -ItemType Directory -Force -Path $skillDst | Out-Null
  Copy-Item $Skill (Join-Path $skillDst "SKILL.md") -Force
  Write-Host "[ok] 技能 -> $skillDst"
}

Write-Host ""
Write-Host "下一步：用 DSH 打开 $WorkspacePath，在会话列表里找 $SessionId。"
Write-Host "定时任务不会自动恢复，打开后手动重挂。"

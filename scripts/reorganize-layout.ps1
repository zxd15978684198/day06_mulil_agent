<#
    reorganize-layout.ps1 —— 按 src 布局整理 mutil_agent 仓库

    默认只「预览」：打印将要做的每一步，不动任何文件。
    真正执行：
        powershell -ExecutionPolicy Bypass -File scripts\reorganize-layout.ps1 -Apply

    设计原则
      * 先搬、后删：搬运与删除分开两段，删除项逐条列出，不用宽通配符扫目录
      * 可重复执行：源不存在就跳过，不会因为跑第二遍而报错
      * 出错即停：$ErrorActionPreference = 'Stop'

    依据：docs/plans/Day06_执行计划_v2.md §5.1（D4 决策：可导入代码全部收进 src/，
    数据目录收在 src/ 下、包外；.env 与构建配置留仓库根）。
#>
[CmdletBinding()]
param(
    [string]$Root = 'E:\projects\mutil_agent',
    [switch]$Apply          # 不加这个开关就是干跑
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Root)) { throw "仓库根不存在：$Root" }
Set-Location -LiteralPath $Root

$mode = if ($Apply) { 'APPLY（真正执行）' } else { 'DRY-RUN（只预览，不改文件）' }
Write-Host "== reorganize-layout.ps1 ==  root=$Root  mode=$mode" -ForegroundColor Cyan
Write-Host ''

function Step([string]$Title) { Write-Host "── $Title" -ForegroundColor Yellow }

function DoMove([string]$From, [string]$To) {
    if (-not (Test-Path -LiteralPath $From)) { Write-Host "   skip (源不存在)  $From"; return }
    Write-Host "   MOVE   $From"
    Write-Host "       -> $To"
    if ($Apply) {
        $dir = Split-Path -Parent $To
        if ($dir -and -not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
        }
        Move-Item -LiteralPath $From -Destination $To -Force
    }
}

# 把一个目录里的条目逐个搬到目标目录（保留每个条目的原名）
function DoMoveChildren([string]$FromDir, [string]$ToDir) {
    if (-not (Test-Path -LiteralPath $FromDir)) { Write-Host "   skip (源目录不存在)  $FromDir"; return }
    $items = @(Get-ChildItem -LiteralPath $FromDir -Force)
    if ($items.Count -eq 0) { Write-Host "   skip (空目录)      $FromDir"; return }
    if ($Apply -and -not (Test-Path -LiteralPath $ToDir)) {
        New-Item -ItemType Directory -Force -Path $ToDir | Out-Null
    }
    foreach ($it in $items) {
        $dest = Join-Path $ToDir $it.Name
        Write-Host "   MOVE   $($it.FullName)"
        Write-Host "       -> $dest"
        if ($Apply) { Move-Item -LiteralPath $it.FullName -Destination $dest -Force }
    }
}

function DoDelete([string]$Path, [string]$Why) {
    if (-not (Test-Path -LiteralPath $Path)) { Write-Host "   skip (不存在)    $Path"; return }
    Write-Host "   DELETE $Path"
    Write-Host "          # $Why"
    if ($Apply) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

# ─────────────────────────────────────────────────────────────
Step '0. 前置检查：两份 day05 初始化 SQL 是否逐字一致'

$a = 'scripts\day05_mysql_setup.sql'
$b = 'src\migrations\sql\day05_mysql_setup.sql'
if ((Test-Path -LiteralPath $a) -and (Test-Path -LiteralPath $b)) {
    $diff = @(Compare-Object (Get-Content -LiteralPath $a) (Get-Content -LiteralPath $b))
    if ($diff.Count -eq 0) {
        Write-Host '   两份内容一致 —— scripts\ 下那份可直接删（下面第 3 段会搬走后再删）' -ForegroundColor Green
    } else {
        Write-Host "   注意：两份不一致，差异 $($diff.Count) 行。先看清楚再决定，本次只搬不删。" -ForegroundColor Red
        $diff | Select-Object -First 20 | Format-Table -AutoSize | Out-String | Write-Host
    }
} else {
    Write-Host '   跳过（有一份不存在，可能已经整理过）'
}

# ─────────────────────────────────────────────────────────────
Step '1. 把「不属于项目源码」的东西搬出仓库根'

# 1.1 周考作业：不是源码、不是包的一部分 —— 收进 docs\（文档/资料区），不进 src\
DoMoveChildren 'exercise' 'docs\exercise'

# 1.2 .tmp\ 里的压测脚本有价值，先救出来再清空 .tmp\
if (Test-Path -LiteralPath '.tmp') {
    $benches = @(Get-ChildItem -LiteralPath '.tmp' -Filter 'bench_*.py' -Force)
    foreach ($f in $benches) {
        DoMove $f.FullName 'scripts\bench'
    }
    if ($benches.Count -eq 0) { Write-Host '   skip (.tmp 里没有 bench_*.py)' }
}

# 1.3 SQL 唯一化：整库快照统一收进 src\migrations\sql\bootstrap\
DoMove 'src\migrations\sql\day05_mysql_setup.sql' 'src\migrations\sql\bootstrap\day05_mysql_setup.sql'
DoMove 'src\migrations\sql\day06_mysql_setup.sql' 'src\migrations\sql\bootstrap\day06_mysql_setup.sql'
DoMove 'scripts\day05_mysql_setup.sql'         'scripts\day05_mysql_setup.sql.keep'

# ─────────────────────────────────────────────────────────────
Step '2. 删除重复的 alembic 环境'

DoDelete 'src\alembic'     'stock 模板：target_metadata=None、sqlalchemy.url 是占位符 driver://user:pass@localhost/dbname、script_location=%(here)s/alembic —— 跑不起来，与根 alembic.ini + src\migrations\ 重复'
DoDelete 'src\alembic.ini' '同上，重复的库存模板配置'

# ─────────────────────────────────────────────────────────────
Step '3. 清掉运行期/工具残留（全部已在 .gitignore 内或零引用）'

DoDelete '__pycache__'                                            '根薄壳 main.py / build_index.py 的字节码'
DoDelete 'v4-h7boeps0'                                            '游离的 checkpoints.sqlite3；全仓库零引用'
DoDelete '.tmp'                                                   '验收日志、一次性备份 json、探测脚本（.gitignore 已忽略）；bench_*.py 已在第 1.2 步搬走'
Get-ChildItem -Path 'src' -Recurse -Directory -Filter '__pycache__' -Force |
    ForEach-Object { DoDelete $_.FullName '包内的字节码缓存（随时会再生）' }

# 确认 day05 一致后再删除保留下来的副本
if (-not $Apply) { Write-Host '   (预览模式：scripts\day05_mysql_setup.sql.keep 保留待你确认后手动删除)' }

# ─────────────────────────────────────────────────────────────
Step '4. 结果'
Write-Host '   顶层内容：'
Get-ChildItem -LiteralPath $Root -Force |
    Sort-Object { -not $_.PSIsContainer }, Name |
    ForEach-Object {
        $tag = if ($_.PSIsContainer) { '[dir] ' } else { '[file]' }
        Write-Host "     $tag $($_.Name)"
    }

if (-not $Apply) {
    Write-Host ''
    Write-Host '这是预览。确认无误后加 -Apply 真正执行：' -ForegroundColor Cyan
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\reorganize-layout.ps1 -Apply" -ForegroundColor Cyan
}

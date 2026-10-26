
param([switch]$Apply)

$ErrorActionPreference = "Stop"
$Root = (Get-Location).Path
$Archive = Join-Path $Root "_old_files"

function Archive-IfUnused {
    param(
        [string]$Name,
        [switch]$RequireEmpty
    )

    $Path = Join-Path $Root $Name

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }

    if ($RequireEmpty -and (Get-Item -LiteralPath $Path).Length -ne 0) {
        Write-Warning "SKIP: $Name is not empty"
        return
    }

    $References = Get-ChildItem -LiteralPath $Root -Filter "*.py" -File |
        Where-Object { $_.Name -ne $Name } |
        Select-String -SimpleMatch -Pattern $Name

    if ($References) {
        Write-Warning "SKIP: $Name is referenced by other Python files"
        return
    }

    if ($Apply) {
        New-Item -ItemType Directory -Force -Path $Archive | Out-Null
        $Destination = Join-Path $Archive $Name

        if (Test-Path -LiteralPath $Destination) {
            Write-Warning "SKIP: $Name already exists in archive"
            return
        }

        Move-Item -LiteralPath $Path -Destination $Destination
        Write-Host "ARCHIVED: $Name" -ForegroundColor Green
    }
    else {
        Write-Host "WOULD ARCHIVE: $Name" -ForegroundColor Cyan
    }
}

# Legacy or diagnostic files
Archive-IfUnused "extract_handshake_links.py"
Archive-IfUnused "test_api.py"
Archive-IfUnused "resume_template_preview.docx"
Archive-IfUnused "job.txt" -RequireEmpty

# Only archive duplicate web app when contents are identical
$Main = Join-Path $Root "web_app.py"
$Copy = Join-Path $Root "web_app_v2.py"

if ((Test-Path $Main) -and (Test-Path $Copy)) {
    $Hash1 = (Get-FileHash $Main -Algorithm SHA256).Hash
    $Hash2 = (Get-FileHash $Copy -Algorithm SHA256).Hash

    if ($Hash1 -eq $Hash2) {
        Archive-IfUnused "web_app_v2.py"
    }
    else {
        Write-Warning "KEEP: web_app_v2.py differs from web_app.py"
    }
}

if ($Apply) {
    Write-Host "Cleanup completed." -ForegroundColor Green
}
else {
    Write-Host "Preview only. No files moved." -ForegroundColor Yellow
}

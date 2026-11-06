<#
.SYNOPSIS
Builds AMA's portable Windows cyanrip from a pinned upstream commit (ADR 0007).

.DESCRIPTION
Needs no admin rights and installs nothing system-wide. It unpacks a pinned
MSYS2 snapshot under -BuildRoot, installs the locked toolchain
(msys2-packages.lock), and runs build.sh in MINGW64. The result is
<BuildRoot>\out\cyanrip-<version>-win64.zip.

  .\tools\cyanrip\build.ps1                 # clean build + zip
  .\tools\cyanrip\build.ps1 -InfoDevice D:  # ...then `cyanrip -I` on a CD in D: (no rip)
  .\tools\cyanrip\build.ps1 -Publish        # ...then publish it as a GitHub Release
  .\tools\cyanrip\build.ps1 -PublishOnly    # publish the last build
  .\tools\cyanrip\build.ps1 -Relock         # update the toolchain and rewrite the lock

-Publish creates the GitHub Release cyanrip-<version> (ADR 0015) with the
logged-in GitHub CLI (gh), tagging this checkout's HEAD. Commit tools\cyanrip
and push HEAD first: the release notes link the build inputs at that tag.
#>
param(
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA "ama-build\cyanrip"),
    [string]$InfoDevice = "",
    [switch]$Publish,
    [switch]$PublishOnly,
    [switch]$Relock,
    [switch]$Fresh
)
$ErrorActionPreference = "Stop"

# The pinned MSYS2 snapshot (https://repo.msys2.org/distrib/x86_64/).
$Snapshot = "msys2-base-x86_64-20260927.sfx.exe"
$SnapshotSha256 = "ad336cccfda47758b5e15cda993fbba421115cb0b126697daef1ee4dfe37209f"
$AmaDriveOffset = 667   # PIONEER BDR-S11JX, as AMA's [cd] config uses

$Here = $PSScriptRoot
$Msys = Join-Path $BuildRoot "msys64"
$Bash = Join-Path $Msys "usr\bin\bash.exe"

function Invoke-Msys([string]$System, [string]$Command) {
    # Native stderr must not count as a PowerShell error; exit codes are checked instead.
    $ErrorActionPreference = "Continue"
    $env:MSYSTEM = $System
    $env:MSYS2_PATH_TYPE = "minimal"   # keep Windows tools (Git for Windows, Python...) off PATH
    $env:CHERE_INVOKING = "1"
    # Output goes to the host, so the function returns only the exit code.
    & $Bash -lc $Command 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    Remove-Item Env:MSYSTEM, Env:MSYS2_PATH_TYPE, Env:CHERE_INVOKING
    return $code
}

# After an msys2-runtime upgrade, leftover processes on the old runtime (gpg-agent,
# a dying shell) break fork() and hold pacman's lock. Stop them between steps.
function Reset-Msys {
    Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($Msys, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Remove-Item (Join-Path $Msys "var\lib\pacman\db.lck") -ErrorAction SilentlyContinue
}

function ConvertTo-MsysPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    return "/" + $full.Substring(0, 1).ToLower() + $full.Substring(2).Replace("\", "/")
}

New-Item -ItemType Directory -Force $BuildRoot | Out-Null
$HereMsys = ConvertTo-MsysPath $Here
$RootMsys = ConvertTo-MsysPath $BuildRoot

if ($Fresh -and (Test-Path $Msys)) { Remove-Item -Recurse -Force $Msys }

# 1. MSYS2 snapshot.
if (-not (Test-Path $Bash)) {
    $sfx = Join-Path $BuildRoot $Snapshot
    if (-not (Test-Path $sfx) -or (Get-FileHash $sfx -Algorithm SHA256).Hash.ToLower() -ne $SnapshotSha256) {
        Invoke-WebRequest -UseBasicParsing "https://repo.msys2.org/distrib/x86_64/$Snapshot" -OutFile "$sfx.part"
        Move-Item -Force "$sfx.part" $sfx
    }
    if ((Get-FileHash $sfx -Algorithm SHA256).Hash.ToLower() -ne $SnapshotSha256) { throw "$Snapshot failed its SHA-256 check" }
    & $sfx -y "-o$BuildRoot" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "unpacking $Snapshot failed" }
    # First login sets up the keyring; then record the snapshot's packages.
    if ((Invoke-Msys "MSYS" "pacman -Q > /var/lib/ama-snapshot-packages.txt") -ne 0) { throw "MSYS2 first run failed" }
}

# 2. Toolchain, pinned by the lock (a stamp skips this when nothing changed).
$Lock = Join-Path $Here "msys2-packages.lock"
$Stamp = Join-Path $Msys "var\lib\ama-lock.sha256"
if ($Relock) {
    # -Syuu can end its own shell after a runtime upgrade; repeat until settled.
    foreach ($i in 1..3) { Reset-Msys; Invoke-Msys "MSYS" "pacman -Syuu --noconfirm" | Out-Null }
    Reset-Msys
    if ((Invoke-Msys "MSYS" "'$HereMsys/msys2.sh' relock") -ne 0) { throw "relock failed" }
} else {
    $lockHash = (Get-FileHash $Lock -Algorithm SHA256).Hash
    if (-not (Test-Path $Stamp) -or (Get-Content $Stamp) -ne $lockHash) {
        Reset-Msys
        Invoke-Msys "MSYS" "'$HereMsys/msys2.sh' core" | Out-Null   # may end its shell; checked below
        Reset-Msys
        if ((Invoke-Msys "MSYS" "'$HereMsys/msys2.sh' core") -ne 0) { throw "installing the locked core packages failed" }
        Reset-Msys
        if ((Invoke-Msys "MSYS" "'$HereMsys/msys2.sh' rest") -ne 0) { throw "installing the locked packages failed" }
        Reset-Msys
        Set-Content -Path $Stamp -Value $lockHash -Encoding ascii
    }
}

# 3. Build, 4. check against a real CD, 5. publish.
$env:AMA_BUILD_ROOT = $RootMsys
try {
    if (-not $PublishOnly) {
        if ((Invoke-Msys "MINGW64" "'$HereMsys/build.sh'") -ne 0) { throw "build failed" }
    }
    $exe = Join-Path $BuildRoot "out\stage\cyanrip.exe"
    if ($InfoDevice) {
        # The same flags AMA's CdRipper uses for its TOC read (src/ama/cyanrip.py):
        # prints the TOC, Disc ID and AccurateRip lookup. -I never rips or ejects.
        $ErrorActionPreference = "Continue"
        & $exe -d $InfoDevice -s $AmaDriveOffset -p 1=track -W -N -U -G -I
        $code = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($code -ne 0) { throw "cyanrip -I exited $code" }
    }
    if ($Publish -or $PublishOnly) {
        $gh = Get-Command gh -ErrorAction SilentlyContinue
        $gh = if ($gh) { $gh.Source } else { Join-Path $env:ProgramFiles "GitHub CLI\gh.exe" }
        if (-not (Test-Path $gh)) { throw "publishing needs the GitHub CLI (gh), logged in" }
        if (git -C $Here status --porcelain -- .) { throw "commit tools\cyanrip first: the release notes link it at the release tag" }
        $env:GH = ConvertTo-MsysPath $gh
        $env:AMA_COMMIT = git -C $Here rev-parse HEAD
        if ((Invoke-Msys "MINGW64" "'$HereMsys/build.sh' publish") -ne 0) { throw "publish failed" }
    }
} finally {
    Remove-Item Env:AMA_BUILD_ROOT, Env:GH, Env:AMA_COMMIT -ErrorAction SilentlyContinue
}

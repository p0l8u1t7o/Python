# Builds CrystalPrintHelper.exe.
# Requires the Crystal Reports .NET runtime (Engine/Shared assemblies registered
# under C:\Windows\assembly\GAC_MSIL) and the .NET Framework 3.5 csc.exe.

$ErrorActionPreference = "Stop"

function Find-GacAssembly($name) {
    $root = "C:\Windows\assembly\GAC_MSIL\$name"
    if (-not (Test-Path $root)) {
        throw "GAC assembly not found: $name (is the Crystal Reports .NET runtime installed?)"
    }
    $dll = Get-ChildItem -Path $root -Filter "$name.dll" -Recurse | Select-Object -First 1
    if (-not $dll) {
        throw "$name.dll not found under $root"
    }
    return $dll.FullName
}

$csc = "C:\Windows\Microsoft.NET\Framework64\v3.5\csc.exe"
if (-not (Test-Path $csc)) {
    throw "NET Framework 3.5 compiler not found: $csc"
}

$engine = Find-GacAssembly "CrystalDecisions.CrystalReports.Engine"
$shared = Find-GacAssembly "CrystalDecisions.Shared"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

& $csc /nologo /platform:x64 /target:exe /out:CrystalPrintHelper.exe `
    /r:$engine /r:$shared /r:System.Data.dll /r:System.Drawing.dll Program.cs

Write-Output "Built: $scriptDir\CrystalPrintHelper.exe"

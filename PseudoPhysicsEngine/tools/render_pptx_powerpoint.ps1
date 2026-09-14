param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$powerPoint = $null
$presentation = $null
try {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Open((Resolve-Path -LiteralPath $InputPath).Path, $true, $true, $false)
    foreach ($slide in $presentation.Slides) {
        $path = Join-Path $OutputDirectory ("slide-{0}.png" -f $slide.SlideNumber)
        $slide.Export($path, 'PNG', 1920, 1080)
    }
} finally {
    if ($presentation) { $presentation.Close() }
    if ($powerPoint) { $powerPoint.Quit() }
    if ($presentation) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($powerPoint) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

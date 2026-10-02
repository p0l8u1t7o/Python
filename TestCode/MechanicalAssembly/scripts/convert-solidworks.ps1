param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
# Uses an existing licensed SolidWorks installation. No mock geometry is produced.
$inputFile = (Resolve-Path -LiteralPath $InputPath).Path
$docType = if ([IO.Path]::GetExtension($inputFile) -ieq '.sldasm') { 2 } else { 1 }
$swApp = New-Object -ComObject SldWorks.Application
$openErrors = 0
$openWarnings = 0
$doc = $null
try {
    $doc = $swApp.OpenDoc6($inputFile, $docType, 1, '', [ref]$openErrors, [ref]$openWarnings)
    if ($null -eq $doc -or $openErrors -ne 0) { throw "OpenDoc6 failed: errors=$openErrors warnings=$openWarnings. Check referenced parts." }
    if ($openWarnings -ne 0) { throw "OpenDoc6 warnings=$openWarnings. Resolve all references and warnings before conversion." }
    $activateErrors = 0
    $activeDoc = $swApp.ActivateDoc3($doc.GetTitle(), $false, 0, [ref]$activateErrors)
    if ($null -eq $activeDoc -or $activateErrors -ne 0) { throw "ActivateDoc3 failed: errors=$activateErrors" }
    $doc.ForceRebuild3($false) | Out-Null
    $doc.ClearSelection2($true)
    $saveErrors = 0
    $saveWarnings = 0
    $ok = $doc.Extension.SaveAs($OutputPath, 0, 1, $null, [ref]$saveErrors, [ref]$saveWarnings)
    if (-not $ok -or $saveErrors -ne 0 -or $saveWarnings -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) { throw "STEP export failed: errors=$saveErrors warnings=$saveWarnings" }
    Write-Output $OutputPath
} finally {
    if ($null -ne $doc) { $swApp.CloseDoc($doc.GetTitle()) }
    if ($null -ne $doc) { [Runtime.InteropServices.Marshal]::ReleaseComObject($doc) | Out-Null }
    [Runtime.InteropServices.Marshal]::ReleaseComObject($swApp) | Out-Null
}

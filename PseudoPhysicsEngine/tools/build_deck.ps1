param(
    [Parameter(Mandatory = $true)][string]$DataPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)
$ErrorActionPreference = 'Stop'
$powerPoint = $null
$presentation = $null
try {
    $data = Get-Content -LiteralPath $DataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Add()
    $presentation.PageSetup.SlideWidth = 960
    $presentation.PageSetup.SlideHeight = 540

    function Add-Text($slide, $text, $left, $top, $width, $height, $size, $bold, $color) {
        $shape = $slide.Shapes.AddTextbox(1, $left, $top, $width, $height)
        $shape.TextFrame.TextRange.Text = $text
        $shape.TextFrame.TextRange.Font.Name = 'Microsoft JhengHei'
        $shape.TextFrame.TextRange.Font.Size = $size
        $shape.TextFrame.TextRange.Font.Bold = [int]$bold
        $shape.TextFrame.TextRange.Font.Color.RGB = $color
        $shape.TextFrame.WordWrap = -1
        $shape.TextFrame.AutoSize = 0
        return $shape
    }
    function Add-Slide($title, $body, $accent) {
        $slide = $presentation.Slides.Add($presentation.Slides.Count + 1, 12)
        $slide.FollowMasterBackground = 0
        $slide.Background.Fill.ForeColor.RGB = 1577227
        $bar = $slide.Shapes.AddShape(1, 0, 0, 18, 540)
        $bar.Fill.ForeColor.RGB = $accent
        $bar.Line.Visible = 0
        Add-Text $slide $title 55 38 850 65 24 $true 16777215 | Out-Null
        Add-Text $slide $body 58 125 830 350 14 $false 14803425 | Out-Null
        Add-Text $slide ('CELLFORGE  |  ' + $data.version) 58 500 820 22 9 $false 8951007 | Out-Null
        return $slide
    }

    $cover = $presentation.Slides.Add(1, 12)
    $cover.FollowMasterBackground = 0
    $cover.Background.Fill.ForeColor.RGB = 1577227
    $cover.Shapes.AddShape(1, 0, 0, 960, 18).Fill.ForeColor.RGB = 14851914
    Add-Text $cover $data.name 65 150 830 100 36 $true 16777215 | Out-Null
    Add-Text $cover 'AUTOMATED QC CELL / ENGINEERING REVIEW' 68 270 760 35 16 $false 14851914 | Out-Null
    Add-Text $cover ($data.customer + '  |  ' + $data.product + '  |  ' + $data.version) 68 330 760 55 14 $false 12566463 | Out-Null
    Add-Text $cover 'Parametric CAD / Motion / L1 checks / SolidWorks delivery' 68 455 800 30 12 $false 8951007 | Out-Null

    $assumptionText = ($data.assumptions | Select-Object -First 8 | ForEach-Object { '- ' + $_ }) -join "`n"
    Add-Slide '01 / Design basis and assumptions' $assumptionText 14851914 | Out-Null
    $stationText = ($data.stations | ForEach-Object { '- ' + $_ }) -join "`n"
    $stationSlide = Add-Slide '02 / Five-station cell architecture' $stationText 14851914
    if (Test-Path -LiteralPath $data.snapshot) {
        $stationSlide.Shapes.AddPicture($data.snapshot, 0, -1, 550, 180, 350, 250) | Out-Null
    }
    $checkText = "Red $($data.checks.red)    Yellow $($data.checks.yellow)    Green $($data.checks.green)`n`n" + (($data.checkItems | ForEach-Object { '- ' + $_ }) -join "`n")
    $checkSlide = Add-Slide '03 / L1 engineering checks' $checkText 5263615
    Add-Slide '04 / Process and takt' ("Animated duration: $($data.duration) s`nTarget takt: $($data.takt) s`nProtective covers animated: $($data.coverage)`n`nThe risk register remains explicit. Presentation work never hides engineering checks.") 14851914 | Out-Null
    Add-Slide '05 / SolidWorks delivery confidence' ("STEP root: CellForge`nTop-level components: $($data.step.top_level_part_count)`nLeaf parts: $($data.step.leaf_part_count)`nNames preserved: $($data.step.all_names_preserved)`nXCAF writer fallback: $($data.step.xcaf_fallback_used)`n`nIndependent OCP readback runs on every build.") 14851914 | Out-Null
    Add-Slide '06 / Getac delivery pack' ("- Named STEP assembly`n- 2D DXF layout`n- BOM CSV`n- Engineering report DOCX`n- Review deck PPTX`n- Single-file HTML review`n- 1080p MP4`n`nOpen risks and inferred values remain traceable to source assumptions.") 14851914 | Out-Null

    $presentation.SaveAs($OutputPath, 24)
} finally {
    if ($presentation) { $presentation.Close() }
    if ($powerPoint) { $powerPoint.Quit() }
    if ($presentation) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($powerPoint) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

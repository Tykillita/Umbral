# Voz local a WAV por frase. No usa red ni reproduce audio en el equipo.
param([string]$Work = (Join-Path $PSScriptRoot '../../.production/video-work'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$story = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'storyboard.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Path (Join-Path $Work 'speech') -Force | Out-Null
foreach ($language in @('es', 'en')) {
    $speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    $speaker.SelectVoice($story.languages.$language.voice)
    $speaker.Rate = 0
    $speaker.Volume = 100
    foreach ($scene in $story.scenes) {
        $name = "$language-$($scene.id)"
        $segments = @()
        $index = 0
        foreach ($caption in $scene.$language.captions) {
            $filename = "$name-$index.wav"
            $stream = [System.IO.File]::Open((Join-Path $Work "speech/$filename"), [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
            $speaker.SetOutputToWaveStream($stream)
            $speaker.Speak($caption)
            $speaker.SetOutputToNull()
            $stream.Dispose()
            $segments += [PSCustomObject]@{text=$caption; file=$filename}
            $index++
        }
        [PSCustomObject]@{voice=$story.languages.$language.voice; locale=$story.languages.$language.locale; rate=0; segments=$segments} |
            ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Work "speech/$name.json") -Encoding utf8
        Write-Output "$name sintetizado"
    }
    $speaker.Dispose()
}

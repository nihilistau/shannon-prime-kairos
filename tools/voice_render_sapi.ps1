# voice_render_sapi.ps1 — P1 corpus render on CPU via Windows SAPI (ADR-KAI4 P1).
# Multi-voice x rate-variation, 16k/16bit/mono, resumable (skips existing wavs).
# CPU-only by construction -> the 2060 keeps serving Gemma. Reads var/voice/corpus.jsonl.
param([string]$Root = "D:\F\shannon-prime-repos\shannon-prime-kairos")
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Speech
$wd = Join-Path $Root "var\voice\wav"
New-Item -ItemType Directory -Force $wd | Out-Null

$voices = @("Microsoft David Desktop","Microsoft Zira Desktop","Microsoft James",
            "Microsoft Catherine","Microsoft Mark","Microsoft Zira")
$rates = @(-2, 0, 2)   # SAPI rate perturbation for acoustic variety
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)

$lines = Get-Content (Join-Path $Root "var\voice\corpus.jsonl")
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$avail = $synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
$done = 0; $skip = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    $text = ($lines[$i] | ConvertFrom-Json).text
    $vi = 0
    foreach ($v in $voices) {
        if ($avail -notcontains $v) { continue }
        foreach ($r in $rates) {
            $out = Join-Path $wd ("s{0:D4}_v{1}_r{2}.wav" -f $i, $vi, ($r + 2))
            if (Test-Path $out) { $skip++; continue }
            try {
                $synth.SelectVoice($v); $synth.Rate = $r
                $synth.SetOutputToWaveFile($out, $fmt)
                $synth.Speak($text)
                $done++
            } catch { "[render] FAIL s$i v$v r$r : $_" }
        }
        $vi++
    }
    if ($i % 10 -eq 0) { "[render] sentence $i/$($lines.Count) done=$done skip=$skip" }
}
$synth.SetOutputToNull(); $synth.Dispose()
"RENDER_DONE done=$done skip=$skip wav=$wd"

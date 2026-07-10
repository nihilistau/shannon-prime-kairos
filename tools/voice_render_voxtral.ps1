# voice_render_voxtral.ps1 — render a corpus SUBSET with OUR voxtral TTS (ADR-KAI4 P1.6).
# Voxtral voices are far more human-like than SAPI -> bridges the SAPI->real gap.
# Voxtral is RTF~4 on the 2060 (the iGPU 'integrated' path panics in cubecl), so this
# is a DAEMON-DOWN bake over a SUBSET, not the whole corpus. Output naming matches
# voice_frames' regex (s{idx}_v{N}_r{N}); voxtral voices use v20+ to avoid SAPI's v0-5.
param(
  [string]$Root = "D:\F\shannon-prime-repos\shannon-prime-kairos",
  [int]$MaxSentences = 250,
  [int]$EulerSteps = 3
)
$ErrorActionPreference = "Continue"
$vx = "D:\F\shannon-prime-repos\voxtral-mini-realtime-rs\target\release\voxtral.exe"
$gguf = "C:\Projects\voxtral-mini-realtime-rs\models\voxtral-tts-q4-gguf\voxtral-tts-q4.gguf"
$vd = "C:\Projects\voxtral-mini-realtime-rs\models\voxtral-tts-q4-gguf\voice_embedding"
$wd = Join-Path $Root "var\voice\wav"
New-Item -ItemType Directory -Force $wd | Out-Null
$voices = @("casual_female","casual_male","cheerful_female","neutral_female","neutral_male")
$lines = Get-Content (Join-Path $Root "var\voice\corpus.jsonl")
$n = [Math]::Min($MaxSentences, $lines.Count)
$done = 0; $skip = 0
Set-Location "D:\F\shannon-prime-repos\voxtral-mini-realtime-rs"   # repo-root cwd for the GPU ctx
for ($i = 0; $i -lt $n; $i++) {
  $text = ($lines[$i] | ConvertFrom-Json).text
  $vi = 20
  foreach ($v in $voices) {
    $out = Join-Path $wd ("s{0:D4}_v{1}_r2.wav" -f $i, $vi)
    if (Test-Path $out) { $skip++; $vi++; continue }
    & $vx speak --gguf $gguf --voices-dir $vd --voice $v --euler-steps $EulerSteps `
        --device discrete --text $text --output $out *> $null
    if (Test-Path $out) { $done++ } else { "[vox] FAIL s$i $v" }
    $vi++
  }
  if ($i % 10 -eq 0) { "[vox] sentence $i/$n done=$done skip=$skip" }
}
"VOX_RENDER_DONE done=$done skip=$skip"

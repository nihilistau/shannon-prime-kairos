# P5 drafter overnight chain: datagen -> train -> restore the daily driver.
cd D:\F\shannon-prime-repos\shannon-prime-kairos
$env:PYTHONPATH = "$pwd"
# 1) wait for datagen to finish (DONE line or 3h cap)
$t = 0
while ($t -lt 10800) {
  $log = Get-Content var\datagen.log -Raw -ErrorAction SilentlyContinue
  if ($log -match "\[datagen\] DONE") { break }
  Start-Sleep 30; $t += 30
}
"chain: datagen phase over after $t s" | Add-Content var\drafter_chain.log
# 2) stop the stack (free the GPU for torch)
python serve.py agent --stop 2>&1 | Add-Content var\drafter_chain.log
Start-Sleep 10
# 3) train
python tools\drafter\fit_drafter.py > var\fit.log 2>&1
"chain: training done (exit $LASTEXITCODE)" | Add-Content var\drafter_chain.log
# 4) restore the daily driver
Start-Process python -ArgumentList "serve.py","agent" -WindowStyle Hidden
"chain: daily driver relaunched $(Get-Date -Format HH:mm:ss)" | Add-Content var\drafter_chain.log

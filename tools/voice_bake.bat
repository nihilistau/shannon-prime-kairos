@echo off
REM voice_bake.bat — the P1 ear bake (ADR-KAI4). CPU-only, 2060 stays serving.
REM corpus -> SAPI multi-voice render -> frames -> CTC train. Resumable render.
cd /d D:\F\shannon-prime-repos\shannon-prime-kairos
set CUDA_VISIBLE_DEVICES=
echo BAKE_START %DATE% %TIME% > var\voice\bake.log
python tools\voice_corpus.py >> var\voice\bake.log 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\voice_render_sapi.ps1 >> var\voice\bake.log 2>&1
python tools\voice_frames.py >> var\voice\bake.log 2>&1
python -u tools\voice_train.py --epochs 600 >> var\voice\bake.log 2>&1
echo BAKE_DONE %DATE% %TIME% >> var\voice\bake.log

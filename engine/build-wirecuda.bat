@echo off
REM ── kairos engine build (G-KAIROS-P1a) ─────────────────────────────────────
REM Builds sp-daemon.exe with the wire_cuda_backend feature (RTX 2060 sm_75).
REM
REM Layout mirrors the staging engine INSIDE engine/ so build.rs runs UNPATCHED
REM (engine_root = manifest/../.. = this directory): tools/sp_daemon (crate),
REM tools/sp_swarm (path dep), include/sp_engine (C headers), src/tokenizer.
REM
REM Toolchain env (VS2019 BT + CUDA pin) is machine-level and stays sourced from
REM the staging repo's scripts/env — it pins compilers, not repo policy.
REM
REM Staging ARTIFACT dependencies (fall away when G-CLEAN-BUILD lands the cmake
REM builds in kairos — MIGRATION-MAP core/ row):
REM   SP_SYSTEM_BUILD_DIR  prebuilt math-core .libs      (build-cpu)
REM   SP_CUDA_BACKEND_DIR  prebuilt sp_cuda_daemon_backend.lib (build-host-cuda-backend)
REM Headers come from the kairos core/ submodule (SP_SYSTEM_INCLUDE).
call "D:\F\shannon-prime-repos\shannon-prime-system-engine\scripts\env\env-cuda.bat"
if errorlevel 1 exit /b 1

set "SP_SYSTEM_INCLUDE=%~dp0..\core\include"
set "SP_SYSTEM_BUILD_DIR=D:\F\shannon-prime-repos\shannon-prime-system-engine\build-cpu\lib\shannon-prime-system"
set "SP_CUDA_BACKEND_DIR=D:\F\shannon-prime-repos\shannon-prime-system-engine\build-host-cuda-backend"

cd /d "%~dp0tools\sp_daemon"
cargo build --release --features wire_cuda_backend --target-dir target-wirecuda --bin sp-daemon
echo EXITCODE=%ERRORLEVEL%
exit /b %ERRORLEVEL%

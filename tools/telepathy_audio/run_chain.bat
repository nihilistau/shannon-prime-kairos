@echo off
cd /d D:\F\shannon-prime-repos\shannon-prime-kairos\tools\telepathy_audio
echo CHAIN_START > _chain.status
python -u distill_real.py >> _chain.status 2>&1
echo DISTILL_DONE >> _chain.status
python -u train_and_decode.py >> _chain.status 2>&1
echo CHAIN_DONE >> _chain.status

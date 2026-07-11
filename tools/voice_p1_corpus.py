"""KAI-4 P1 corpus — grow the ear's vocabulary from V_sub=32 to ~512.

Pipeline (all CPU; the 2060 keeps serving):
  1. ~430 conversational words + project words + digits → templated sentences
     (~2400) + the wake phrase ("hey shannon", oversampled) + per-word isolates.
  2. Tokenize each sentence with the REAL gemma tokenizer (sp_tok_enc.exe);
     greedily keep sentences until the union vocabulary reaches --vmax (512).
  3. Render each kept sentence with EVERY installed SAPI voice × rate jitter
     (multi-voice was the lever that took KAI-3 from 3/7 → 7/8).
  4. Featurize (harness.voice.dsp — the verbatim trainer mel) + write
     var/voice/p1_frames.npz in the KAI-3 trainer format
     (train_X/train_Y/train_flen/train_tlen + eval_* split + vsub_ids).

Usage: python tools/voice_p1_corpus.py [--vmax 512] [--out var/voice]
       [--render-only] [--skip-render]
"""
from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from harness.voice import dsp  # noqa: E402  (verbatim trainer mel)

TOK_ENC = r"D:\F\shannon-prime-repos\shannon-prime-system-engine\build-cpu\tools\sp_tok_dump\sp_tok_enc.exe"
TOKENIZER = r"D:\F\shannon-prime-repos\models\gemma4-12b-b1.sp-tokenizer"

WAKE = "hey shannon"

WORDS = """
the a an and or but so if then what when where why how which who whose can could
would should will shall do does did is are am was were be been being have has had
not no yes okay please
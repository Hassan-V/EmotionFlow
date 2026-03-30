#!/usr/bin/env python3
"""Test 6-7 class audio SER models on IEMOCAP clips."""
import os
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torchaudio
import numpy as np
import torch
from transformers import pipeline

base = "/mnt/d/IEMOCAP_full_release/Session1/sentences/wav/Ses01F_impro01/"
test_files = [
    ("Ses01F_impro01_F000.wav", "neu"),
    ("Ses01F_impro01_F002.wav", "neu"),
    ("Ses01F_impro01_F006.wav", "fru"),
    ("Ses01F_impro01_F007.wav", "fru"),
    ("Ses01F_impro01_F008.wav", "fru"),
]

def load_audio(path):
    waveform, sr = torchaudio.load(path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.transforms.Resample(sr, 16000)(waveform)
    return waveform.squeeze(0).numpy().astype(np.float32)

def test_model(name, desc):
    print(f"\n{'='*70}")
    print(f"Model: {name}")
    print(f"  {desc}")
    print('='*70)
    try:
        pipe = pipeline("audio-classification", model=name, device=0)
        # Show label set
        if hasattr(pipe.model, 'config') and hasattr(pipe.model.config, 'id2label'):
            labels = list(pipe.model.config.id2label.values())
            print(f"  Labels ({len(labels)}): {labels}")
        for wav_name, gt in test_files:
            audio = load_audio(os.path.join(base, wav_name))
            results = pipe({"raw": audio, "sampling_rate": 16000})
            top3 = results[:3]
            labels_str = "  ".join([f"{r['label']}={r['score']:.2f}" for r in top3])
            print(f"  {wav_name}  GT={gt:>3s}  |  {labels_str}")
        del pipe
        torch.cuda.empty_cache()
    except Exception as e:
        print(f"  FAILED: {e}")
        torch.cuda.empty_cache()

# Already proven: 4-class baseline
test_model("superb/wav2vec2-base-superb-er",
           "IEMOCAP 4-class baseline (ang/hap/neu/sad)")

# 6-class candidates
test_model("j-hartmann/emotion-english-distilroberta-base",
           "6 Ekman + neutral — text model for comparison only")

test_model("r-f/wav2vec-english-speech-emotion-recognition",
           "wav2vec2 English SER — multi-class")

test_model("harshit345/xlsr-wav2vec-speech-emotion-recognition",
           "XLSR wav2vec2 SER — multi-class")

test_model("Rajaram1996/Hubert_emotion",
           "HuBERT emotion — multi-class")

test_model("facebook/hubert-large-ls960-ft",
           "HuBERT-large finetuned — check if has emotion head")

test_model("speechbrain/emotion-recognition-wav2vec2-IEMOCAP",
           "SpeechBrain wav2vec2 IEMOCAP")

test_model("xmj2002/hubert-base-ch-speech-emotion-recognition",
           "HuBERT Chinese SER (skip if Chinese only)")

test_model("ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition",
           "RAVDESS/TESS/SAVEE 8-class (tested before, poor)")

test_model("Wiam/wav2vec2-lg-xlsr-en-speech-emotion-recognition-finetuned-ravdess",
           "wav2vec2-xlsr RAVDESS finetuned")

test_model("firdhokk/speech-emotion-recognition",
           "Generic SER model")

print("\n\nAll tests complete!", flush=True)

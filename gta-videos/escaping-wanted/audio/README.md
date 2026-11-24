# Voiceover

- `vo.wav` (not committed, ~47 MB): 48 kHz mono, loudness-normalised to -16 LUFS, 8:06 long.
- `vo_preview.mp3`: the current narration, voiced by Piper TTS with the `en_US-ryan-high` model (free, offline).
- `vo_preview_espeak.mp3`: the earlier, more robotic espeak-ng/MBROLA version, kept for comparison.

The text-to-speech engine reads "Pay 'n' Spray" as "Pay and Spray".

To rebuild `vo.wav`:
1. `pip install piper-tts`, then download `en_US-ryan-high.onnx` and its `.json` file from huggingface.co/rhasspy/piper-voices.
2. Render each paragraph of `script/narration.md` with
   `python -m piper -m en_US-ryan-high.onnx --sentence-silence 0.25 --length-scale 0.95 -f pNN.wav`.
3. Join the paragraphs with 0.7 s silences, then run
   `ffmpeg -af "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11" -ar 48000`.

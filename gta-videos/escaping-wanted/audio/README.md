# Voiceover

- `vo.wav` (not committed, 50 MB): 48 kHz mono, loudness-normalised to -16 LUFS. Regenerate from the script as below.
- `vo_preview.mp3`: the same narration, committed for listening.

Voice: free offline TTS, espeak-ng with the MBROLA `us2` voice, 172 wpm, 0.7 s pause between script sections.
"Pay 'n' Spray" is spoken as "Pay and Spray".
Rebuild: install `espeak-ng mbrola mbrola-us2`, render each paragraph of `script/narration.md` with
`espeak-ng -v mb-us2 -s 172 -g 2`, join them with 0.7 s silences, then run
`ffmpeg -af "highpass=f=70,alimiter=limit=0.89,loudnorm=I=-16:TP=-1.5:LRA=11" -ar 48000`.

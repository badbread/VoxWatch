"""speech — Natural Cadence TTS post-processing package for VoxWatch.

This package transforms a list of short AI-generated phrases into a single
natural-sounding audio file by:

  1. Generating each phrase as an independent TTS segment.
  2. Inserting punctuation-aware silence gaps between phrases.
  3. Optionally varying playback speed per phrase via ffmpeg's atempo filter.
  4. Concatenating everything with ffmpeg's concat demuxer.
  5. Applying a light loudness-normalisation + silence-trim postprocess pass.

The entry point for callers is ``generate_natural_speech`` in
``voxwatch.speech.natural_cadence``.  Audio post-processing helpers live in
``voxwatch.speech.postprocess``.

Example::

    from voxwatch.speech.natural_cadence import generate_natural_speech, CadenceConfig
    await generate_natural_speech(
        phrases=["Stop.", "You are being recorded.", "Leave the property now."],
        audio_pipeline=pipeline,
        output_path="/data/audio/escalation_natural.wav",
        config=config,
    )
"""

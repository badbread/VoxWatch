"""
providers/__init__.py — TTS Provider Sub-Package

Individual provider modules are imported on demand by the factory to
avoid import-time failures when optional SDKs (elevenlabs, cartesia,
boto3, kokoro-onnx) are not installed.  Do not star-import this package.
"""

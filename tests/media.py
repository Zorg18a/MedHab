"""Тестовые медиафайлы без ffmpeg и Pillow: WAV из модуля wave, PNG из zlib+struct."""
import struct, wave, zlib
from pathlib import Path


def write_wav(path, seconds=2, rate=8000):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(1); w.setframerate(rate)
        w.writeframes(b"\x80" * int(rate * seconds))
    return path


def write_png(path, w, h, rgb=(200, 100, 50)):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    row = b"\x00" + bytes(rgb) * w
    raw = zlib.compress(row * h, 1)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    return path

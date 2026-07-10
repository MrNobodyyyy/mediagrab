#!/usr/bin/env python3
"""
MediaGrab – Server per la conversione di URL in MP3.
Usa YOUTUBE_COOKIES come variabile d'ambiente per bypassare il bot-check di YouTube.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile

from flask import Flask, jsonify, request, send_file

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"))


def _sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:120].strip("_. ") or "audio"


def _get_ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _write_cookies_file() -> str | None:
    """Scrive i cookie YouTube (da env var) in un file temporaneo."""
    content = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not content:
        return None
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="ytcookies_")
    tmp.write(content)
    tmp.close()
    return tmp.name


@app.route("/api/download-url", methods=["POST"])
def download_url():
    try:
        import yt_dlp
    except ImportError:
        return jsonify({"error": "yt-dlp non installato"}), 500

    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    bitrate = str(data.get("bitrate", 192))

    if not url:
        return jsonify({"error": "URL mancante"}), 400

    tmp_dir = tempfile.mkdtemp(prefix="mediagrab_")
    cookies_file = _write_cookies_file()

    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }],
            "ffmpeg_location": _get_ffmpeg_path(),
            "quiet": True,
            "no_warnings": True,
            # Client Android: meno rilevato come bot rispetto al client web
            "extractor_args": {
                "youtube": {"player_client": ["android", "web"]}
            },
        }

        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = _sanitize(info.get("title") or "audio")

        mp3_files = [f for f in os.listdir(tmp_dir) if f.endswith(".mp3")]
        if not mp3_files:
            return jsonify({"error": "Nessun MP3 prodotto."}), 500

        mp3_path = os.path.join(tmp_dir, mp3_files[0])
        out_name = f"{title}_{bitrate}kbps.mp3"

        with open(mp3_path, "rb") as fh:
            mp3_bytes = fh.read()

    except yt_dlp.utils.DownloadError as exc:
        msg = re.sub(r"^ERROR:\s*", "", str(exc), flags=re.IGNORECASE).strip()
        return jsonify({"error": msg}), 400

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if cookies_file and os.path.exists(cookies_file):
            os.unlink(cookies_file)

    return send_file(
        io.BytesIO(mp3_bytes),
        as_attachment=True,
        download_name=out_name,
        mimetype="audio/mpeg",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  MediaGrab avviato su http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

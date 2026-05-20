"""
YouTube Clip Transcript → GTT Bot Ingestion Script

Takes a list of YouTube clip URLs (youtu.be/VIDEO_ID?t=START format),
pulls transcripts, and outputs either:
  - Markdown files for the Obsidian vault (picked up by Watchdog/LlamaIndex Indexer)
  - JSON for direct Qdrant ingestion

Usage:
    # Markdown into vault (default) — fits existing GTT architecture
    python yt_transcript_to_qdrant.py clips.txt --format markdown --outdir ./vault/youtube-clips

    # JSON for direct Qdrant ingestion
    python yt_transcript_to_qdrant.py clips.txt --format json -o qdrant_points.json

Requirements:
    pip install youtube-transcript-api

clips.txt format (one URL per line, # comments and blank lines ignored):
    https://youtu.be/HKoATXxeZHk?t=23
    https://youtu.be/abcDEF12345?t=100
    https://www.youtube.com/watch?v=xyz789&t=50
"""

import argparse
import json
import os
import re
import sys
import uuid
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi


def parse_youtube_url(url: str) -> dict | None:
    """
    Extract video_id and start time from YouTube URLs.

    Supports:
        https://youtu.be/VIDEO_ID?t=SECONDS
        https://www.youtube.com/watch?v=VIDEO_ID&t=SECONDS
        https://youtube.com/watch?v=VIDEO_ID
    """
    url = url.strip()
    parsed = urlparse(url)

    video_id = None
    start_seconds = 0

    # youtu.be/VIDEO_ID
    if parsed.hostname in ("youtu.be",):
        video_id = parsed.path.lstrip("/")
        params = parse_qs(parsed.query)
        if "t" in params:
            start_seconds = int(params["t"][0])

    # youtube.com/watch?v=VIDEO_ID
    elif parsed.hostname in ("www.youtube.com", "youtube.com"):
        params = parse_qs(parsed.query)
        if "v" in params:
            video_id = params["v"][0]
        if "t" in params:
            raw = params["t"][0]
            # Handle "50s" format
            start_seconds = int(raw.rstrip("s"))

    if not video_id:
        return None

    return {
        "video_id": video_id,
        "start_seconds": start_seconds,
        "url": url,
    }


def fetch_transcript(video_id: str, start_seconds: int = 0) -> dict:
    """
    Fetch transcript for a video. Returns full text and segments
    starting from start_seconds onward (for clips).
    """
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)

    all_segments = []
    clip_segments = []

    for snippet in transcript.snippets:
        seg = {
            "text": snippet.text,
            "start": round(snippet.start, 2),
            "duration": round(snippet.duration, 2),
        }
        all_segments.append(seg)
        # Include segments from clip start time onward
        if snippet.start >= start_seconds:
            clip_segments.append(seg)

    # Use clip segments if we have a start time, otherwise all
    segments = clip_segments if start_seconds > 0 and clip_segments else all_segments

    full_text = " ".join(seg["text"] for seg in segments)
    # Clean up whitespace / newlines from auto-captions
    full_text = re.sub(r"\s+", " ", full_text).strip()

    return {
        "full_text": full_text,
        "segments": segments,
        "segment_count": len(segments),
    }


# ---------------------------------------------------------------------------
# Markdown output — drops into Obsidian vault for Watchdog/LlamaIndex pickup
# ---------------------------------------------------------------------------

def build_markdown(clip_info: dict, transcript_data: dict) -> str:
    """
    Build an Obsidian-compatible markdown note with YAML frontmatter.

    The Indexer (Watchdog + LlamaIndex) will detect the new file,
    embed the content via Ollama, and store it in Qdrant automatically.
    The frontmatter metadata lands in Qdrant's payload for retrieval.
    """
    video_id = clip_info["video_id"]
    clip_url = clip_info["url"]
    start = clip_info["start_seconds"]

    lines = [
        "---",
        "source: youtube_clip",
        f"video_id: {video_id}",
        f"clip_url: {clip_url}",
        f"start_seconds: {start}",
        f"segment_count: {transcript_data['segment_count']}",
        "---",
        "",
        f"# Clip: {video_id} (t={start}s)",
        "",
        f"[Watch clip]({clip_url})",
        "",
        transcript_data["full_text"],
        "",
    ]

    return "\n".join(lines)


def sanitize_filename(video_id: str, start_seconds: int) -> str:
    """Create a safe, unique filename from video ID and start time."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", video_id)
    return f"clip-{safe_id}-t{start_seconds}.md"


def write_markdown_files(results: list[dict], outdir: str) -> list[str]:
    """Write markdown files to output directory. Returns list of written paths."""
    os.makedirs(outdir, exist_ok=True)
    written = []

    for item in results:
        clip_info = item["clip_info"]
        transcript_data = item["transcript_data"]

        filename = sanitize_filename(clip_info["video_id"], clip_info["start_seconds"])
        filepath = os.path.join(outdir, filename)

        md_content = build_markdown(clip_info, transcript_data)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        written.append(filepath)

    return written


# ---------------------------------------------------------------------------
# JSON output — direct Qdrant ingestion
# ---------------------------------------------------------------------------

def build_qdrant_point(clip_info: dict, transcript_data: dict) -> dict:
    """
    Build a Qdrant-ready point with text for embedding and metadata payload.
    """
    return {
        "id": str(uuid.uuid4()),
        "text": transcript_data["full_text"],
        "payload": {
            "source": "youtube_clip",
            "video_id": clip_info["video_id"],
            "clip_url": clip_info["url"],
            "start_seconds": clip_info["start_seconds"],
            "segment_count": transcript_data["segment_count"],
            "transcript_segments": transcript_data["segments"],
        },
    }


def write_json(results: list[dict], errors: list[dict], output_path: str, collection: str):
    """Write JSON output for direct Qdrant ingestion."""
    points = [build_qdrant_point(r["clip_info"], r["transcript_data"]) for r in results]

    output = {
        "_meta": {
            "collection": collection,
            "total_points": len(points),
            "failed": len(errors),
            "note": "Embed each point's 'text' field and upsert with 'id' and 'payload' into Qdrant.",
        },
        "points": points,
        "errors": errors,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_urls(filepath: str) -> list[str]:
    """Load URLs from a text file, skipping comments and blank lines."""
    urls = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="Fetch YouTube clip transcripts for GTT Bot ingestion."
    )
    parser.add_argument(
        "input",
        help="Path to text file with YouTube URLs (one per line)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format: 'markdown' for Obsidian vault (default), 'json' for direct Qdrant",
    )
    parser.add_argument(
        "--outdir",
        default="./youtube-clips",
        help="Output directory for markdown files (default: ./youtube-clips)",
    )
    parser.add_argument(
        "-o", "--output",
        default="qdrant_points.json",
        help="Output JSON file path, used with --format json (default: qdrant_points.json)",
    )
    parser.add_argument(
        "--collection",
        default="gtt-transcripts",
        help="Qdrant collection name, used with --format json (default: gtt-transcripts)",
    )
    args = parser.parse_args()

    urls = load_urls(args.input)
    print(f"Loaded {len(urls)} URLs from {args.input}")
    print(f"Format: {args.format}")
    print()

    results = []
    errors = []

    for i, url in enumerate(urls, 1):
        clip_info = parse_youtube_url(url)
        if not clip_info:
            print(f"  [{i}/{len(urls)}] SKIP - couldn't parse: {url}")
            errors.append({"url": url, "error": "unparseable URL"})
            continue

        video_id = clip_info["video_id"]
        start = clip_info["start_seconds"]

        # Skip if markdown file already exists
        if args.format == "markdown":
            existing = os.path.join(args.outdir, sanitize_filename(video_id, start))
            if os.path.exists(existing):
                print(f"  [{i}/{len(urls)}] SKIP - already exists: {sanitize_filename(video_id, start)}")
                continue

        print(f"  [{i}/{len(urls)}] Fetching {video_id} (t={start}s)...", end=" ")

        try:
            transcript_data = fetch_transcript(video_id, start)
            results.append({"clip_info": clip_info, "transcript_data": transcript_data})
            word_count = len(transcript_data["full_text"].split())
            print(f"OK ({word_count} words, {transcript_data['segment_count']} segments)")
        except Exception as e:
            error_msg = str(e).split("\n")[0]
            print(f"FAIL - {error_msg}")
            errors.append({"url": url, "video_id": video_id, "error": error_msg})

    print()

    # Write output in chosen format
    if args.format == "markdown":
        written = write_markdown_files(results, args.outdir)
        print(f"Done: {len(written)} markdown files → {args.outdir}/")
        for path in written:
            print(f"  {path}")
        if errors:
            print(f"\n  {len(errors)} failed:")
            for err in errors:
                print(f"    {err['url']} — {err['error']}")
        print(f"\nNext: copy {args.outdir}/ into your Obsidian vault.")
        print("Watchdog will detect the new files and the Indexer will embed + store them in Qdrant.")

    elif args.format == "json":
        write_json(results, errors, args.output, args.collection)
        print(f"Done: {len(results)} transcripts → {args.output}")
        if errors:
            print(f"  {len(errors)} failed (see 'errors' in output)")
        print(f"\nNext steps:")
        print(f"  1. Embed each point['text'] with nomic-embed-text via Ollama")
        print(f"  2. Upsert into Qdrant collection '{args.collection}' with the vector + payload")


if __name__ == "__main__":
    main()

"""Produce el recorrido y el reel de Umbral con capturas reales, TTS local y FFmpeg."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import subprocess
import textwrap
import wave
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "docs" / "video"
WORK = ROOT / ".production" / "video-work"
STORY = json.loads((PUBLIC / "storyboard.json").read_text(encoding="utf-8"))
FPS = STORY["fps"]
PAPER, SURFACE, INK, AMBER, BLUE = "#FFF7DF", "#FFFEF7", "#172337", "#F7C744", "#CEE5EC"
FFMPEG = shutil.which("ffmpeg")


def run(args):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fonts():
    folder = PUBLIC / "fonts"
    folder.mkdir(exist_ok=True)
    variants = [("barlow-condensed", 800, "display"), ("atkinson-hyperlegible", 400, "body"), ("atkinson-hyperlegible", 700, "bold")]
    for family, weight, target in variants:
        output = folder / f"{target}.ttf"
        if not output.exists():
            source = ROOT / "apps" / "web" / "node_modules" / "@fontsource" / family
            font = TTFont(source / "files" / f"{family}-latin-{weight}-normal.woff")
            font.flavor = None
            font.save(output)
            shutil.copyfile(source / "LICENSE", folder / f"{family}-OFL.txt")


@lru_cache(maxsize=32)
def font(name, size):
    return ImageFont.truetype(str(PUBLIC / "fonts" / f"{name}.ttf"), size)


def timeline():
    start = 0
    result = []
    for scene in STORY["scenes"]:
        result.append({**scene, "start": start})
        start += scene["duration"]
    assert start == 77
    return result


def prepare_capture(fmt):
    capture = json.loads((WORK / f"capture-{fmt}.json").read_text(encoding="utf-8"))
    if not capture["offline"] or capture["dataMode"] == "fixture" or capture["externalRequestsBlocked"]:
        raise RuntimeError("La captura debe ser local, sin fixtures y sin solicitudes externas.")
    destination = PUBLIC / "captures"
    destination.mkdir(exist_ok=True)
    entries = []
    for scene in timeline():
        if scene["id"] in {"intro", "outro"}:
            continue
        source = next(s for s in capture["scenes"] if s["name"] == scene["id"])
        factor = scene["duration"] / source["duration"]
        filename = f"{scene['id']}-{fmt}.mp4"
        output = destination / filename
        crop = f"crop={capture['size']['width']}:{capture['size']['height']}:0:0,"
        run(["-ss", source["start"], "-i", capture["raw"], "-vf",
             crop + f"trim=duration={source['duration']},setpts=(PTS-STARTPTS)*{factor},fps={FPS},tpad=stop_mode=clone:stop_duration=0.3",
             "-t", scene["duration"], "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output])
        clicks = [{"time": round((e["time"] - source["start"]) * factor, 3), "x": e["x"], "y": e["y"]}
                  for e in capture["clicks"] if source["start"] <= e["time"] < source["start"] + source["duration"]]
        entries.append({"id": scene["id"], "file": filename, "duration": scene["duration"], "sha256": sha(output), "clicks": clicks})
    manifest = {"snapshotId": capture["snapshotId"], "dataMode": capture["dataMode"], "offline": True,
                "containsFixtures": False, "externalRequests": 0, "topic": capture["topic"], "viewport": capture["size"],
                "applicationCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "recordedAtUtc": datetime.now(timezone.utc).isoformat(), "scenes": entries}
    (destination / f"{fmt}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{fmt}: seis capturas normalizadas", flush=True)


def wave_duration(path):
    with wave.open(str(path)) as audio:
        return audio.getnframes() / audio.getframerate()


@lru_cache(maxsize=16)
def speech_parts(lang, scene_id):
    metadata = json.loads((WORK / "speech" / f"{lang}-{scene_id}.json").read_text(encoding="utf-8-sig"))
    blocks, segments, offset = [], [], 0
    parameters = None
    for i, segment in enumerate(metadata["segments"]):
        with wave.open(str(WORK / "speech" / segment["file"])) as part:
            if parameters is None:
                parameters = part.getparams()
            elif (parameters.nchannels, parameters.sampwidth, parameters.framerate) != (part.getnchannels(), part.getsampwidth(), part.getframerate()):
                raise RuntimeError("Las frases de voz deben compartir el formato PCM.")
            raw = part.readframes(part.getnframes())
            if part.getsampwidth() != 2:
                raise RuntimeError("La voz local debe exportar PCM de 16 bits.")
            samples = np.frombuffer(raw, dtype="<i2").reshape(-1, part.getnchannels())
            amplitude = np.max(np.abs(samples.astype(np.int32)), axis=1)
            audible = np.flatnonzero(amplitude > max(24, amplitude.max() * .007))
            if not len(audible):
                raise RuntimeError("La frase de voz está vacía.")
            first = max(0, audible[0] - round(.04 * part.getframerate()))
            last = min(len(samples), audible[-1] + round(.11 * part.getframerate()))
            trimmed = samples[first:last]
            duration = len(trimmed) / part.getframerate()
            blocks.append(trimmed.tobytes())
        segments.append({"text": segment["text"], "start": offset, "duration": duration})
        offset += duration
        if i + 1 < len(metadata["segments"]):
            silence = round(.09 * parameters.framerate)
            blocks.append(bytes(silence * parameters.sampwidth * parameters.nchannels))
            offset += silence / parameters.framerate
    output = WORK / "speech" / f"{lang}-{scene_id}.wav"
    with wave.open(str(output), "wb") as assembled:
        assembled.setparams(parameters)
        assembled.writeframes(b"".join(blocks))
    return output, offset, segments


def speech_info(lang, scene):
    path, duration, _ = speech_parts(lang, scene["id"])
    speed = max(1, duration / (scene["duration"] - .8))
    if speed > 1.23:
        raise RuntimeError(f"La narración {lang}/{scene['id']} necesita acortarse ({speed:.2f}).")
    return path, duration, speed


def caption_cues(lang):
    cues = []
    for scene in timeline():
        _, duration, speed = speech_info(lang, scene)
        _, _, parts = speech_parts(lang, scene["id"])
        for part in parts:
            cues.append({"start": scene["start"] + .35 + part["start"] / speed,
                         "end": min(scene["start"] + scene["duration"] - .12, scene["start"] + .35 + (part["start"] + part["duration"]) / speed), "text": part["text"]})
    return cues


def timestamp(t):
    milliseconds = round(t * 1000)
    return f"{milliseconds // 3600000:02d}:{milliseconds // 60000 % 60:02d}:{milliseconds // 1000 % 60:02d}.{milliseconds % 1000:03d}"


def subtitles(lang, cues):
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.extend([f"{timestamp(cue['start'])} --> {timestamp(cue['end'])}", cue["text"], ""])
    (PUBLIC / f"umbral-{lang}.vtt").write_text("\n".join(lines), encoding="utf-8")


def soundtrack(lang, fmt):
    capture = json.loads((PUBLIC / "captures" / f"{fmt}.json").read_text(encoding="utf-8"))
    sample_rate = 48000
    clicks = np.zeros(sample_rate * STORY["duration"], dtype=np.float64)
    rng = np.random.default_rng(17)
    for scene in timeline():
        entry = next((x for x in capture["scenes"] if x["id"] == scene["id"]), None)
        if not entry:
            continue
        for click in entry["clicks"]:
            index = round((scene["start"] + click["time"]) * sample_rate)
            for delay, strength in [(0, .22), (.062, .14)]:
                length = round(.025 * sample_rate)
                t = np.arange(length) / sample_rate
                pulse = (np.sin(t * math.tau * 1900) * .6 + rng.normal(size=length) * .35) * np.exp(-t * 230) * strength
                offset = index + round(delay * sample_rate)
                if offset + length < len(clicks):
                    clicks[offset:offset + length] += pulse
    click_path = WORK / f"clicks-{fmt}.wav"
    with wave.open(str(click_path), "wb") as audio:
        audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(sample_rate)
        audio.writeframes(np.repeat((clicks * 32767).astype("<i2")[:, None], 2, axis=1).tobytes())
    inputs, filters = [], []
    for i, scene in enumerate(timeline()):
        path, _, speed = speech_info(lang, scene)
        inputs += ["-i", path]
        delay = round((scene["start"] + .35) * 1000)
        filters.append(f"[{i}:a]atempo={speed:.7f},aresample=48000,aformat=channel_layouts=stereo,adelay={delay}|{delay},apad,atrim=duration=77[v{i}]")
    inputs += ["-i", PUBLIC / "source-music.m4a", "-i", click_path]
    filters += ["[8:a]aresample=48000,volume=0.055,afade=t=in:d=1.2,afade=t=out:st=74:d=3[music]",
                "[9:a]volume=1[clicks]", "".join(f"[v{i}]" for i in range(8)) + "[music][clicks]amix=inputs=10:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9,atrim=duration=77[out]"]
    path = WORK / f"audio-{lang}-{fmt}.wav"
    run([*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "48000", "-c:a", "pcm_s16le", path])
    return path


def ease(t):
    return 1 - (1 - min(1, max(0, t))) ** 3


def wrap(draw, text, face, width):
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=face) > width and line:
            lines.append(line); line = word
        else:
            line = candidate
    return lines + ([line] if line else [])


@lru_cache(maxsize=4)
def base_stage(fmt, lang):
    portrait = fmt == "portrait"
    size = (1080, 1920) if portrait else (1920, 1080)
    image = Image.new("RGB", size, PAPER)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 22):
        for x in range((y // 22 % 2) * 11, size[0], 22):
            draw.ellipse((x, y, x + 1, y + 1), fill="#DECFA8")
    draw.rectangle((36, 34, size[0] - 36, size[1] - 34), outline=INK, width=3)
    draw.text((70, 57), "UMBRAL.", font=font("display", 65 if portrait else 62), fill=INK)
    badge_face = font("bold", 21 if portrait else 23)
    badge = STORY["languages"][lang]["badge"]
    width = draw.textlength(badge, font=badge_face) + 36
    x = size[0] - 70 - width
    draw.rectangle((x + 5, 62, size[0] - 65, 111), fill=INK)
    draw.rectangle((x, 57, size[0] - 70, 106), fill=AMBER, outline=INK, width=2)
    draw.text((x + 18, 69), badge, font=badge_face, fill=INK)
    return image


def stage(scene, local, fmt, lang, video=None, global_time=0, cues=()):
    portrait = fmt == "portrait"
    image = base_stage(fmt, lang).copy()
    draw = ImageDraw.Draw(image)
    width, height = image.size
    entry = ease(local / .7)
    closing = ease((scene["duration"] - local) / .45)
    opacity = entry * closing
    words = scene[lang]
    intro = scene["id"] in {"intro", "outro"}
    if intro:
        display = font("display", 125 if portrait else 139)
        lines = words["title"].split("\n")
        ty = (260 if portrait else 270) + round((1 - entry) * 65)
        for line in lines:
            tx = (width - draw.textlength(line, font=display)) / 2 if portrait else 115
            draw.text((tx, ty), line, font=display, fill=INK)
            ty += 139 if portrait else 148
        # Las cinco viñetas del símbolo son una animación de marca.
        icon_x, icon_y = (230, 700) if portrait else (1160, 270)
        icon_w = 620 if portrait else 530
        for i in range(5):
            progress = ease((local - .15 - i * .15) / .7)
            if i == 0:
                box = (icon_x, icon_y, icon_x + icon_w, icon_y + 160)
            else:
                cell = (icon_w - 22) // 2
                cx = icon_x + ((i - 1) % 2) * (cell + 22)
                cy = icon_y + 184 + ((i - 1) // 2) * 148
                box = (cx, cy, cx + cell, cy + 124)
            shift = round((1 - progress) * 110)
            box = (box[0] + shift, box[1], box[2] + shift, box[3])
            if progress > 0:
                draw.rectangle(tuple(v + 10 for v in box), fill=INK)
                draw.rectangle(box, fill=AMBER if i == 0 else SURFACE, outline=INK, width=5)
                draw.text((box[0] + 28, box[1] + 12), f"0{i + 1}", font=font("display", 75), fill=INK)
                draw.line((box[0] + 118, box[1] + 46, box[2] - 25, box[1] + 46), fill=INK, width=5)
                draw.line((box[0] + 118, box[1] + 70, box[2] - 50, box[1] + 70), fill=INK, width=3)
        py = 1260 if portrait else 680
        for i, point in enumerate(words["points"]):
            progress = ease((local - .6 - i * .2) / .65)
            px = 145 if portrait else 120
            draw.text((px + round((1 - progress) * 80), py + i * 62), point, font=font("bold", 38 if portrait else 36), fill=INK)
        draw.text((145 if portrait else 120, 1440 if portrait else 835), STORY["languages"][lang]["repo"], font=font("body", 31 if portrait else 32), fill=INK)
    else:
        title_face = font("display", 76 if portrait else 69)
        lines = words["title"].split("\n")
        y = (141 if portrait else 243) + round((1 - entry) * 35)
        for line in lines:
            x = (width - draw.textlength(line, font=title_face)) / 2 if portrait else 76
            draw.text((x, y), line, font=title_face, fill=INK)
            y += 79 if portrait else 78
        if not portrait:
            for i, point in enumerate(words["points"]):
                progress = ease((local - .25 - i * .16) / .65)
                px, py = 75 + round((1 - progress) * -35), 525 + i * 109
                draw.rectangle((px + 7, py + 7, px + 360, py + 88), fill=INK)
                draw.rectangle((px, py, px + 353, py + 81), fill=BLUE if i == 1 else SURFACE, outline=INK, width=3)
                draw.text((px + 17, py + 18), point, font=font("bold", 27), fill=INK)
        if video is not None:
            if portrait:
                scale = min(780 / video.width, 1240 / video.height)
                fw, fh = round(video.width * scale), round(video.height * scale)
                fx, fy = (1080 - fw) // 2, 340
            else:
                fw, fh, fx, fy = 1335, 760, 500, 133
            fx += round((1 - entry) * 70)
            zoom = 1 + .018 * min(1, local / scene["duration"])
            resized = video.resize((round(fw * zoom), round(fh * zoom)), Image.Resampling.BILINEAR)
            left, top = (resized.width - fw) // 2, (resized.height - fh) // 2
            resized = resized.crop((left, top, left + fw, top + fh))
            screen = Image.new("RGBA", image.size)
            sd = ImageDraw.Draw(screen)
            sd.rectangle((fx - 6 + 12, fy - 6 + 12, fx + fw + 6 + 12, fy + fh + 6 + 12), fill=INK)
            sd.rectangle((fx - 6, fy - 6, fx + fw + 6, fy + fh + 6), fill=SURFACE, outline=INK, width=4)
            screen.paste(resized, (fx, fy))
            screen.putalpha(screen.getchannel("A").point(lambda a: round(a * opacity)))
            image = Image.alpha_composite(image.convert("RGBA"), screen).convert("RGB")
            draw = ImageDraw.Draw(image)
    caption = next((c["text"] for c in cues if c["start"] <= global_time < c["end"]), "")
    if caption:
        face = font("bold", 40 if portrait else 32)
        cx, cw, cy = (80, 920, 1624) if portrait else (475, 1370, 916)
        lines = wrap(draw, caption, face, cw - 50)
        if len(lines) > 2:
            face = font("bold", 35 if portrait else 30)
            lines = wrap(draw, caption, face, cw - 50)
        line_height = 48 if portrait else 38
        ch = len(lines) * line_height + 24
        draw.rectangle((cx + 5, cy + 5, cx + cw + 5, cy + ch + 5), fill=INK)
        draw.rectangle((cx, cy, cx + cw, cy + ch), fill=SURFACE, outline=INK, width=3)
        for i, line in enumerate(lines):
            draw.text((cx + (cw - draw.textlength(line, font=face)) / 2, cy + 9 + i * line_height), line, font=face, fill=INK)
    foot_y = 1806 if portrait else 1024
    foot = STORY["languages"][lang]["data"]
    if lang == "en":
        foot += " · Spanish app UI"
    draw.text((72, foot_y), foot, font=font("body", 25 if portrait else 18), fill=INK)
    draw.text((width - 155, foot_y), f"{lang.upper()} / 77 s", font=font("bold", 24 if portrait else 18), fill=INK)
    bar_y = 1867 if portrait else 1060
    draw.rectangle((70, bar_y, width - 70, bar_y + 8), fill="#DED3B9")
    draw.rectangle((70, bar_y, 70 + round((width - 140) * global_time / 77), bar_y + 8), fill=INK)
    return image


def video_frame(scene, fmt, local):
    clip = PUBLIC / "captures" / f"{scene['id']}-{fmt}.mp4"
    if not clip.exists():
        return None
    raw = subprocess.check_output([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", str(local), "-i", str(clip), "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"])
    return Image.open(io.BytesIO(raw)).convert("RGB")


def stills(fmt, lang):
    cues = caption_cues(lang)
    subtitles(lang, cues)
    folder = WORK / "review"
    folder.mkdir(exist_ok=True)
    for scene in timeline():
        local = min(scene["duration"] - .5, scene["duration"] * .58)
        picture = stage(scene, local, fmt, lang, video_frame(scene, fmt, local), scene["start"] + local, cues)
        picture.save(folder / f"{lang}-{fmt}-{scene['id']}.png")
    print(f"{lang}/{fmt}: ocho fotogramas de revisión", flush=True)


def render(fmt, lang):
    cues_path = WORK / f"captions-{lang}.json"
    cues = json.loads(cues_path.read_text(encoding="utf-8")) if cues_path.exists() else caption_cues(lang)
    audio = WORK / f"audio-{lang}-{fmt}.wav"
    if not audio.exists():
        audio = soundtrack(lang, fmt)
    size = (1080, 1920) if fmt == "portrait" else (1920, 1080)
    kind = "reel" if fmt == "portrait" else "tour"
    output = PUBLIC / f"umbral-{kind}-{lang}.mp4"
    temporary = WORK / f"umbral-{kind}-{lang}.mp4"
    log = open(WORK / f"render-{lang}-{fmt}.log", "w", encoding="utf-8")
    encoder = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-threads", "4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", "77", "-movflags", "+faststart", "-metadata", f"title=Umbral | {kind} | {lang.upper()}", str(temporary)], stdin=subprocess.PIPE, stderr=log)
    try:
        for scene in timeline():
            decoder = None
            clip = PUBLIC / "captures" / f"{scene['id']}-{fmt}.mp4"
            if clip.exists():
                probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(clip)]))
                stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
                source_size = (stream["width"], stream["height"])
                decoder = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(clip), "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "2", "-"], stdout=subprocess.PIPE, stderr=log)
                frame_bytes = source_size[0] * source_size[1] * 3
            video = None
            for i in range(scene["duration"] * FPS):
                if decoder:
                    data = decoder.stdout.read(frame_bytes)
                    if len(data) == frame_bytes:
                        video = Image.frombytes("RGB", source_size, data)
                local = i / FPS
                picture = stage(scene, local, fmt, lang, video, scene["start"] + local, cues)
                encoder.stdin.write(picture.tobytes())
            if decoder:
                decoder.stdout.close()
                decoder.wait()
            print(f"{lang}/{fmt}: {scene['id']} — {scene['start'] + scene['duration']}/77 s", flush=True)
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("FFmpeg no completó la exportación; revisa el log local.")
        temporary.replace(output)
        print(f"Listo: {output.name} ({output.stat().st_size / 1e6:.1f} MB)", flush=True)
    finally:
        if encoder.poll() is None:
            encoder.kill()
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--prepare-audio", action="store_true")
    parser.add_argument("--stills", action="store_true")
    parser.add_argument("--lang", choices=["es", "en"], default="es")
    parser.add_argument("--format", choices=["landscape", "portrait"], default="landscape")
    args = parser.parse_args()
    if not FFMPEG:
        raise SystemExit("Falta FFmpeg en PATH.")
    fonts()
    if args.prepare:
        prepare_capture(args.format)
    elif args.prepare_audio:
        for language in ["es", "en"]:
            cues = caption_cues(language)
            subtitles(language, cues)
            (WORK / f"captions-{language}.json").write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
            for orientation in ["landscape", "portrait"]:
                soundtrack(language, orientation)
        print("Voz, música, clics y subtítulos preparados.", flush=True)
    elif args.stills:
        stills(args.format, args.lang)
    else:
        render(args.format, args.lang)


if __name__ == "__main__":
    main()

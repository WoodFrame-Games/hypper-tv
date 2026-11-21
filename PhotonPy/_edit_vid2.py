import io

p = 'monitor_video.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('def frame_text(frame: bytes, w: int, h: int) -> str:',
     'def frame_text(frame: bytes, w: int, h: int, size: int = 136) -> str:'),
    ('    return "<size=136%>" + "\\n".join(lines) + "</size>"',
     '    return f"<size={size}%>" + "\\n".join(lines) + "</size>"'),
    ('    ap.add_argument("--pvp", action="store_true", default=False)',
     '    ap.add_argument("--pvp", action="store_true", default=False)\n'
     '    ap.add_argument("--size", type=int, default=136, help="размер текста, %")'),
    ('        text = frame_text(frames[idx % len(frames)], args.w, args.h)',
     '        text = frame_text(frames[idx % len(frames)], args.w, args.h, args.size)'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', old.strip()[:45])
    else:
        print('MISS:', old.strip()[:45])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
import io

p = 'monitor_video.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('    ap.add_argument("--size", type=int, default=136, help="размер текста в процентах")',
     '    ap.add_argument("--size", type=int, default=136, help="размер текста в процентах")\n'
     '    ap.add_argument("--pattern", action="store_true",\n'
     '                    help="слать калибровочную сетку вместо видео")'),
    ('    frames = load_frames(args.rgb, args.w, args.h)',
     '    if args.pattern:\n'
     '        w, h = args.w, args.h\n'
     '        buf = bytearray()\n'
     '        for y in range(h):\n'
     '            for x in range(w):\n'
     '                buf += bytes([(x * 255) // max(1, w - 1),\n'
     '                              (y * 255) // max(1, h - 1),\n'
     '                              40 + (x + y) % 2 * 180])\n'
     '        frames = [bytes(buf)]\n'
     '    else:\n'
     '        frames = load_frames(args.rgb, args.w, args.h)'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', old.strip()[:50])
    else:
        print('MISS:', old.strip()[:50])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
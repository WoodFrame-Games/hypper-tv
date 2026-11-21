import io

p = 'monitor_video.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('ap.add_argument("--accept-window", type=float, default=10.0,',
     'ap.add_argument("--accept-window", type=float, default=30.0,'),
    ('                print(f"kick {actor} (мешает)", flush=True)',
     '                print(f"[{time.strftime(\'%H:%M:%S\')}] kick {actor} (мешает)", flush=True)'),
    ('            print(f"accept {actor} (метка {age:.1f}s)", flush=True)',
     '            print(f"[{time.strftime(\'%H:%M:%S\')}] accept {actor} (метка {age:.1f}s)", flush=True)'),
    ('            print(f"kick {actor} (нет метки)", flush=True)',
     '            print(f"[{time.strftime(\'%H:%M:%S\')}] kick {actor} '
     '(метка {age if age is None else round(age, 1)})", flush=True)'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', old.strip()[:45])
    else:
        print('MISS:', old.strip()[:45])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
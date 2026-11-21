import io

p = 'monitor_video.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('    ap.add_argument("--seconds", type=float, default=900.0)',
     '    ap.add_argument("--seconds", type=float, default=900.0)\n'
     '    ap.add_argument("--password", default="", help="пароль комнаты (пусто = без пароля)")\n'
     '    ap.add_argument("--max", type=int, default=2, help="максимум игроков")\n'
     '    ap.add_argument("--pvp", action="store_true", default=False)'),
    ('    if not await mt.enter_room(st, args.room, create=True):',
     '    if not await mt.enter_room(st, args.room, create=True,\n'
     '                               max_players=args.max, password=args.password,\n'
     '                               pvp=args.pvp):'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', old.strip()[:50])
    else:
        print('MISS:', old.strip()[:50])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
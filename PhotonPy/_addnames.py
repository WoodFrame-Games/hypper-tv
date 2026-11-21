import io

p = 'ptWorkFreeze.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('"ButteBus", "CartonLarge"', '"ButteBus", "Button", "CartonLarge"'),
    ('"Tire", "Toilet"', '"Timer", "Tire", "Toilet"'),
    ('"Yield",\n]', '"Yield", "YoutubeMonitor",\n]'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', new[:40])
    else:
        print('MISS:', old[:40])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
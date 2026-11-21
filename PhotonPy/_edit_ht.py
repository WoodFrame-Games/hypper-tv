import io

p = 'ptWorkFreeze.py'
s = io.open(p, encoding='utf-8').read()
pairs = [
    ('def build_simple_hashtable(max_players: int = 10) -> bytes:',
     'def build_simple_hashtable(max_players: int = 10, password: str = "", pvp: bool = True) -> bytes:'),
    ('write_string_prop(buf, "Password",        "")',
     'write_string_prop(buf, "Password",        password)'),
    ('write_bool_prop(buf,   "PvP",              True)',
     'write_bool_prop(buf,   "PvP",              pvp)'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)
        print('ok:', old[:50])
    else:
        print('MISS:', old[:50])
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
import io

p = 'ptWorkFreeze.py'
s = io.open(p, encoding='utf-8').read()

old_kick = '''def build_kick_payload(actor_nr: int) -> bytes:
    """PUN CloseConnection: RaiseEvent 203 с номером актёра (только мастер)."""
    return build_op(253, (244, 203), (245, int(actor_nr)))'''
new_kick = '''def build_kick_payload(actor_nr: int) -> bytes:
    """PUN CloseConnection: RaiseEvent 203, data = actor, адресат 252 = [actor]."""
    return build_op(253, (244, 203), (245, int(actor_nr)),
                    (252, [int(actor_nr)]))'''
if old_kick in s:
    s = s.replace(old_kick, new_kick, 1)
    print('kick ok')
else:
    print('kick MISS')

old_list = 'write_string_array_entry(buf, 250, ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism"])'
new_list = 'write_string_array_entry(buf, 250, ["Map", "GameMode", "PvP", "Nextbot", "PublicMechanism", "Password"])'
if old_list in s:
    s = s.replace(old_list, new_list, 1)
    print('props list ok')
else:
    print('props list MISS')

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
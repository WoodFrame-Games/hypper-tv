import io

p = 'ptWorkFreeze.py'
s = io.open(p, encoding='utf-8').read()
anchor = 'PUN_MAX_VIEW_IDS = 1000'
add = '''def build_kick_payload(actor_nr: int) -> bytes:
    """PUN CloseConnection: RaiseEvent 203 с номером актёра (только мастер)."""
    return build_op(253, (244, 203), (245, int(actor_nr)))


'''
if 'def build_kick_payload' in s:
    print('already there')
else:
    s = s.replace(anchor, add + anchor, 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('added')
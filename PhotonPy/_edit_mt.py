import io

p = 'monitor_test.py'
s = io.open(p, encoding='utf-8').read()
s = s.replace('pt.build_simple_hashtable()',
              'pt.build_simple_hashtable(max_players, password, pvp)')
io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('replaced', s.count('pt.build_simple_hashtable(max_players, password, pvp)'))
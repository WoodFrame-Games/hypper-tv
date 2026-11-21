import sys
p = r"C:\Work\Hypper\OTHER\full059\libil2cpp.so"
data = open(p, "rb").read()
for pat in [b"props/resources", b"wire/resources", b"PcMonitor", b"OldMonitor",
            b"/resources/", b"MonitorController", b"resources/"]:
    idx = []
    start = 0
    while True:
        i = data.find(pat, start)
        if i < 0:
            break
        idx.append(i)
        start = i + 1
        if len(idx) > 12:
            break
    print(pat, "->", idx)
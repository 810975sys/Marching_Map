b = [[12,34], [23, 4]]
a = b[0]
for c in b:
    if c == a:
        print('111')
    if c is a:
        print('222')
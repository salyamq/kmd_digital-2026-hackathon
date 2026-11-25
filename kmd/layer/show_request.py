import json,sys,textwrap
r=json.load(open(sys.argv[1]))
u=r['user']; u=u[u.index('Единицы фрагмента'):u.index('Заполни для каждого узла')] if 'Заполни для каждого узла' in u else u
for line in u.split("\n"):
    print("\n   ".join(textwrap.wrap(line, 300, break_long_words=False, break_on_hyphens=False)) if line else "")

# nothing here moves .. watcher

a small cloud watcher for [nothing here moves](https://mint.keyrunnft.art), long-form op-art by keyrun on base (built on abx).

every ~10 minutes it reads the sale from the chain and sends the artist a phone notification when something happens: a wave opens, a rare output is minted, a wave sells out, or the next wave is due. it signs nothing and holds no keys.

- `watch.py` .. the watcher (python, stdlib only)
- `state.json` .. what it has already seen and sent

# atoms & pixels .. superrare auction watcher (keybot)
# reads the 3 auctions of the ATOMS & PIXELS collection from the chain every 20 s and replies under keyrun's pinned
# launch post on x: first light (reserve met), every new bid, a late bid that extends the clock, the final hour, sold,
# and once all three are sold. it signs nothing and holds no keys besides the x posting keys (github secrets).
# stdlib only.  env: X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET, RUN_MIN (default 345), DRY=1 (print only)
#   python sr_bids.py            run (loops until RUN_MIN or all three sold)
#   python sr_bids.py --whoami   read-only: which x account the keys post as
#   python sr_bids.py --once     one poll (with DRY=1: shows what it would post)
import os, sys, json, time, subprocess, urllib.request, urllib.error, hmac, hashlib, base64, secrets as _secrets
from urllib.parse import quote
try:
    import truststore; truststore.inject_into_ssl()
except ImportError:
    pass

CONTRACT = '0x720dff241124793a7940429f4a2ee35cf027e0fc'
NAMES = {1: 'Vortex', 2: 'Heat Map', 3: 'Golden Lake'}
PARENT = '2122203258974269837'            # keyrun's pinned launch gm post (16 Nov 2026)
BAZAAR = '0x6d7c44773c52d396f43c2d511b81aa168e9a7a42'
T_BID = '0x189a468e632a450afd491f84aa9ae94addc6813c7e309a7b1b1223f88802a77d'
EXTEND = 900                               # a bid in the last 15 min moves the end to bid + 15 min
RPCS = ['https://ethereum-rpc.publicnode.com', 'https://gateway.tenderly.co/public/mainnet', 'https://rpc.mevblocker.io', 'https://ethereum.publicnode.com']
SIGN = '[automated message · keybot]'
UA = {'User-Agent': 'atoms-pixels-watcher/1.0'}
DRY = os.environ.get('DRY') == '1'
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sr_state.json')

# ---------------- chain ----------------
_good = 0
def rpc(method, params):
    global _good
    last = None
    for k in range(len(RPCS)):
        i = (_good + k) % len(RPCS)
        try:
            body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
            j = json.load(urllib.request.urlopen(urllib.request.Request(RPCS[i], data=body, headers={'content-type': 'application/json', **UA}), timeout=20))
            if 'error' in j: raise RuntimeError(j['error'])
            _good = i; return j['result']
        except Exception as e:
            last = e
    raise RuntimeError(f'all rpcs failed: {last}')

def word(d, i): return int(d[2 + 64 * i: 2 + 64 * (i + 1)], 16)
_times = {}
def block_time(bn):
    if bn not in _times: _times[bn] = int(rpc('eth_getBlockByNumber', [hex(bn), False])['timestamp'], 16)
    return _times[bn]

def new_bids(frm, to):
    """bid events of the collection's tokens 1-3 in blocks frm..to, oldest first"""
    out = []
    for a in range(frm, to + 1, 2000):
        b = min(to, a + 1999)
        logs = rpc('eth_getLogs', [{'address': BAZAAR, 'fromBlock': hex(a), 'toBlock': hex(b), 'topics': [T_BID, '0x' + CONTRACT[2:].rjust(64, '0')]}])
        for l in logs:
            tid = int(l['topics'][3], 16)
            if tid not in NAMES: continue
            out.append({'tid': tid, 'bn': int(l['blockNumber'], 16), 'li': int(l['logIndex'], 16), 'tx': l['transactionHash'],
                        'wallet': '0x' + l['topics'][2][-40:], 'amount': word(l['data'], 1) / 1e18, 'len': word(l['data'], 3)})
    return sorted(out, key=lambda x: (x['bn'], x['li']))

_ens = {}
def who(addr):
    if addr not in _ens:
        name = None
        try:
            name = json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.ensideas.com/ens/resolve/{addr}', headers=UA), timeout=15)).get('name')
        except Exception:
            pass
        _ens[addr] = name or f'{addr[:6]}…{addr[-4:]}'
    return _ens[addr]

# ---------------- x (oauth 1.0a user context, as in watch.py) ----------------
XK = {k: os.environ.get(k, '').strip() for k in ('X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET')}
def _oauth(method, url):
    enc = lambda x: quote(str(x), safe='~')
    p = {'oauth_consumer_key': XK['X_API_KEY'], 'oauth_nonce': _secrets.token_hex(16), 'oauth_signature_method': 'HMAC-SHA1',
         'oauth_timestamp': str(int(time.time())), 'oauth_token': XK['X_ACCESS_TOKEN'], 'oauth_version': '1.0'}
    base = '&'.join([method, enc(url), enc('&'.join(f'{enc(k)}={enc(v)}' for k, v in sorted(p.items())))])
    key = enc(XK['X_API_SECRET']) + '&' + enc(XK['X_ACCESS_SECRET'])
    p['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return 'OAuth ' + ', '.join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(p.items()))
def _x(method, url, data=None):
    h = {'Authorization': _oauth(method, url), **UA}
    if data is not None: h['content-type'] = 'application/json'
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=60))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'x {e.code}: {e.read()[:300]!r}')

def post(text, st):
    if DRY or not all(XK.values()):
        print('[dry] would post:\n' + text + '\n'); return
    r = _x('POST', 'https://api.x.com/2/tweets', json.dumps({'text': text, 'reply': {'in_reply_to_tweet_id': PARENT}}).encode())
    st['posted'].append(r['data']['id']); print('[x] posted', r['data']['id'], '|', text.replace('\n', ' / ')); save(st)

# ---------------- texts (approved by keyrun, 16 Nov 2026) ----------------
def eth(x): return ('%.4f' % x).rstrip('0').rstrip('.')
def t_first(nm, b): return f'{nm} just got its first light 🕯️\nReserve met at {eth(b["amount"])} ETH by {who(b["wallet"])} .. the 24h auction has started.\nEvery bid becomes a light and stays in the art.\n{SIGN}'
def t_bid(nm, b, n): return f'{nm} has a new light .. {n} lights now.\n{who(b["wallet"])} bid {eth(b["amount"])} ETH.\n{SIGN}'
def t_hour(nm, a): return f'{nm} .. 1 hour left.\nCurrent bid {eth(a["amount"])} ETH by {who(a["wallet"])}, {a["n"]} lights in the art.\n{SIGN}'
def t_late(nm, b, mins): return f'A late bid on {nm} .. {eth(b["amount"])} ETH by {who(b["wallet"])}.\nThe clock moved back, {mins} min left.\n{SIGN}'
def t_sold(nm, a): return f'{nm} is sold for {eth(a["amount"])} ETH to {who(a["wallet"])} 🙏\n{a["n"]} lights stay in it forever .. every bidder is part of its creation.\n{SIGN}'
def t_all(A): return (f'All three are home ✨\nVortex {eth(A["1"]["amount"])} · Heat Map {eth(A["2"]["amount"])} · Golden Lake {eth(A["3"]["amount"])} ETH\n'
                      f'Thank you to every bidder .. your lights live in the art now.\n@wildalps x @keyrun\n{SIGN}')

# ---------------- state ----------------
def load():
    if os.path.exists(STATE):
        with open(STATE) as f: return json.load(f)
    return {'last': None, 'auctions': {}, 'posted': [], 'all_done': False}
def save(st):
    with open(STATE, 'w') as f: json.dump(st, f, indent=1)
    if os.environ.get('GITHUB_ACTIONS') == 'true' and not DRY:
        subprocess.run('git add sr_state.json && (git diff --cached --quiet || (git -c user.name=sr-watcher -c user.email=41898282+github-actions[bot]@users.noreply.github.com commit -qm sr-state && git pull -q --rebase && git push -q))', shell=True)

def poll(st):
    head = int(rpc('eth_blockNumber', []), 16)
    if st['last'] is None: st['last'] = head - 30000                     # ~4 days back: before the listing (14 Nov mint)
    now = time.time(); A = st['auctions']
    for b in new_bids(st['last'] + 1, head):
        k = str(b['tid']); nm = NAMES[b['tid']]; t = block_time(b['bn']); a = A.get(k)
        if a is None:                                                    # the bid that meets the reserve starts the 24h clock
            A[k] = {'n': 1, 'amount': b['amount'], 'wallet': b['wallet'], 'end': t + (b['len'] or 86400), 'hour': False, 'sold': False}
            post(t_first(nm, b), st)
        elif not a['sold']:
            a['n'] += 1; a['amount'], a['wallet'] = b['amount'], b['wallet']
            if t > a['end'] - EXTEND:
                a['end'] = t + EXTEND; a['hour'] = True
                post(t_late(nm, b, max(1, round((a['end'] - now) / 60))), st)
            else:
                post(t_bid(nm, b, a['n']), st)
        st['last'] = max(st['last'], b['bn'])
    st['last'] = head
    for k, a in A.items():
        nm = NAMES[int(k)]
        if not a['sold'] and not a['hour'] and a['end'] - 3600 <= now < a['end']:
            a['hour'] = True; post(t_hour(nm, a), st)
        if not a['sold'] and now >= a['end'] + 30:                       # the clock ran out: sold (settling moves art + eth later)
            a['sold'] = True; post(t_sold(nm, a), st)
    if not st['all_done'] and len(A) == 3 and all(a['sold'] for a in A.values()):
        st['all_done'] = True; post(t_all(A), st)
    save(st)

if __name__ == '__main__':
    if '--whoami' in sys.argv:
        r = _x('GET', 'https://api.x.com/2/users/me'); print('x keys post as @' + r['data']['username']); sys.exit()
    st = load()
    if '--once' in sys.argv:
        poll(st); print(json.dumps(st['auctions'], indent=1)); sys.exit()
    stop = time.time() + 60 * float(os.environ.get('RUN_MIN', 345))
    while time.time() < stop and not st['all_done']:
        try: poll(st)
        except Exception as e: print('poll failed:', e)
        time.sleep(20)
    print('done' if st['all_done'] else 'run window over')
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a') as f: f.write(f'all_done={str(st["all_done"]).lower()}\n')

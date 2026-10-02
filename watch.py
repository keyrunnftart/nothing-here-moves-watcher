# cloud watcher for "nothing here moves" (base 0xB139…02ba) .. runs on github actions every ~10 min.
# reads the sale straight from the chain, remembers what it already sent in state.json (committed back),
# and pings the artist's phone through ntfy:
#   - x posts ready to go (tap → x opens with the text written → post): wave open, 10/30, 20/30, sold out,
#     rare pulls (mono/void), round-ups of 5 mints (or whatever waited 30 min), edition closed
#   - reminders when an owner tx is due: open the next wave (24h after a sellout), close (72h without one)
# it never signs anything .. the owner tx still runs on the laptop (node wave.mjs waves.mainnet.json open-next|close).
# stdlib only.  env: NTFY_TOPIC (secret).  local test: python watch.py --dry
import os, sys, json, time, urllib.request
from urllib.parse import quote
try:
    import truststore; truststore.inject_into_ssl()   # only on the laptop (its python can't verify certs); not needed on github
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
DRY = '--dry' in sys.argv
TOKEN = '0xb13971551bd3c14a0f793571347ddcdfb08902ba'
MINTER = '0xfb5c61274a3a7da83ccdd88ddec914438244e2c9'
CHAIN = 8453
RPCS = ['https://base-rpc.publicnode.com', 'https://base.drpc.org', 'https://mainnet.base.org']
RESERVES, WAVE, BASE_PRICE, STEP = 8, 30, 0.005, 0.001
BREAK_H, WINDOW_H = 24, 72
WAVE1_AT = 1790951400            # fri 2 oct 2026, 20:00 ist
MINT = 'mint.keyrunnft.art'
OS_ITEM = f'opensea.io/item/base/{TOKEN}/'
OS_COLL = 'opensea.io/collection/nothing-here-moves'
ROUNDUP_N, ROUNDUP_WAIT = 5, 30 * 60
MAX_PINGS = 4                    # per run, so a burst can't flood the phone
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'state.json')
UA = {'user-agent': 'Mozilla/5.0 nhm-cloud-watcher'}
now = time.time()

def rpc_call(to, data):
    last = None
    for url in RPCS:
        try:
            body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'eth_call', 'params': [{'to': to, 'data': data}, 'latest']}).encode()
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, data=body, headers={'content-type': 'application/json', **UA}), timeout=15))
            if 'result' in r: return r['result'][2:]
            last = r.get('error')
        except Exception as e:
            last = e
    raise RuntimeError(f'rpc failed: {last}')

def words(hexs): return [int(hexs[i:i + 64], 16) for i in range(0, len(hexs), 64)]

def chain():
    supply = words(rpc_call(TOKEN, '0x18160ddd'))[0]
    mx = words(rpc_call(TOKEN, '0x6cbdef61'))[0]
    paused = bool(words(rpc_call(TOKEN, '0x5c975abb'))[0])
    configured, _pay, price, alloc, sold = words(rpc_call(MINTER, '0xc6b9f06a' + TOKEN[2:].rjust(64, '0')))
    return {'supply': supply, 'max': mx, 'paused': paused, 'configured': bool(configured), 'price': price / 1e18, 'alloc': alloc, 'sold': sold}

def meta(i):
    """token json once the render has landed, else None"""
    j = json.load(urllib.request.urlopen(urllib.request.Request(f'https://resolver.abx.io/t/{CHAIN}/{TOKEN}/{i}', headers=UA), timeout=20))
    src = next((p.get('source') for p in j.get('abx_provenance', []) if p.get('field') == 'image'), '')
    return j if src == 'effect:render' else None

# ---------------- phone ----------------
sent = 0
def ping(title, text, click=None, urgent=False):
    global sent
    sent += 1
    print(f'[ping] {title} | ' + text.replace('\n', ' / '))
    topic = os.environ.get('NTFY_TOPIC')
    if DRY or not topic: return
    h = {'Title': title.encode('utf-8'), 'Priority': 'urgent' if urgent else 'high', 'Tags': 'rotating_light' if urgent else 'bird'}
    if click: h['Click'] = click
    urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{topic}', data=text.encode('utf-8'), headers={**h, **UA}), timeout=15)

def tap_post(title, text):
    ping(title, text + '\n\n(tap → x opens with this post ready)', 'https://x.com/intent/post?text=' + quote(text, safe=''))

def eth(x): return ('%.4f' % x).rstrip('0').rstrip('.')
def dur(sec):
    m = int(max(0, sec) // 60); h, m = divmod(m, 60)
    return f'{h}h {m}m' if h else f'{m}m'
def when(ts):
    t = time.gmtime(ts + 5.5 * 3600)
    return f"{time.strftime('%a', t).lower()} {t.tm_mday} {time.strftime('%b', t).lower()}, {time.strftime('%H:%M', t)} ist"

# ---------------- rules ----------------
def run(st, c):
    waves, ann, rem = st['waves'], st['announced'], st['reminded']
    n = -(-c['alloc'] // WAVE) if c['configured'] and c['alloc'] else 0
    for k in range(1, n + 1):
        waves.setdefault(str(k), {'openedAt': now})
    w = waves.get(str(n))
    sold_in = c['sold'] - (n - 1) * WAVE if n else 0
    if w and sold_in >= WAVE and not w.get('soldOutAt'): w['soldOutAt'] = now
    closed = n > 0 and c['paused'] and c['supply'] >= c['max']

    # owner-tx reminders (no x post, just the nudge)
    def remind(key, every_h, title, text):
        if now - rem.get(key, 0) >= every_h * 3600 and sent < MAX_PINGS:
            rem[key] = now; ping(title, text, urgent=True)
    if not closed:
        if n == 0 and now >= WAVE1_AT:
            remind('open:1', 1, 'nhm: wave 1 is due', 'on the laptop, in trippy/abx/launch:\nnode wave.mjs waves.mainnet.json open-next')
        elif w and w.get('soldOutAt') and c['supply'] < c['max']:
            due = w['soldOutAt'] + BREAK_H * 3600
            if now >= due:
                remind(f'open:{n + 1}', 2, f'nhm: wave {n + 1} is due', f'wave {n} sold out {dur(now - w["soldOutAt"])} ago.\non the laptop: node wave.mjs waves.mainnet.json open-next')
        elif w and not w.get('soldOutAt'):
            left = w['openedAt'] + WINDOW_H * 3600 - now
            for h in (6, 1):
                if 0 < left < h * 3600 and f'warn:{n}:{h}' not in rem and sent < MAX_PINGS:
                    rem[f'warn:{n}:{h}'] = now
                    ping(f'nhm: wave {n} window ends in {dur(left)}', f'{sold_in}/{WAVE} sold. if it doesn\'t sell out, the rules close the edition.')
            if left <= 0:
                remind(f'close:{n}', 3, 'nhm: close is due', f'wave {n} did not sell out in {WINDOW_H}h ({sold_in}/{WAVE}).\non the laptop: node wave.mjs waves.mainnet.json close')

    # x posts
    def post_once(key, title, text):
        if key not in ann and sent < MAX_PINGS:
            tap_post(title, text); ann[key] = now
    if closed:
        post_once('closed', 'nhm: edition closed .. post it',
                  f"nothing here moves is closed at {c['supply']} editions\n\nthank you to everyone who minted .. the edition is final\n{OS_COLL}")
    for k in range(1, n + 1):   # one open post per wave (also catches up if a run was missed)
        price = BASE_PRICE + STEP * (k - 1)
        post_once(f'{k}:open', f'nhm: wave {k} is open .. post it',
                  f"wave {k} is open\n\n{WAVE} editions · {eth(price)} eth · on base\neach one is generated on-chain at mint .. nobody sees it before it lands\n{MINT}")
    if n:
        for m in (10, 20):
            if m <= sold_in < WAVE: post_once(f'{n}:{m}', f'nhm: wave {n} at {sold_in}/{WAVE} .. post it', f"wave {n} · {sold_in}/{WAVE} minted\n\n{MINT}")
        if w.get('soldOutAt'):
            took = dur(w['soldOutAt'] - w['openedAt'])
            if c['supply'] >= c['max']:
                text = f"wave {n} sold out in {took} .. that was the last one, the edition is complete\nthank you\n{OS_COLL}"
            else:
                text = f"wave {n} sold out in {took} .. thank you\n\nwave {n + 1} opens {when(w['soldOutAt'] + BREAK_H * 3600)} · {eth(BASE_PRICE + STEP * n)} eth\n{MINT}"
            post_once(f'{n}:sold', f'nhm: wave {n} sold out .. post it', text)

    # new mints → queue (in order; stop at the first render that hasn't landed yet)
    while st['next'] < c['supply']:
        i = st['next']
        j = meta(i)
        if j is None: print(f'#{i} render pending'); break
        tr = {a['trait_type']: a['value'] for a in j.get('attributes', [])}
        hero = tr.get('Hero', 'None')
        bits = [tr.get('Mode', '').lower()] + ([hero.lower()] if hero != 'None' else []) + [tr.get('Palette', '').lower(), tr.get('Drift Strength', '').lower() + ' drift']
        st['queue'].append({'i': i, 'mode': bits[0], 'bits': [b for b in bits if b], 't': now})
        st['next'] = i + 1
        print(f'new #{i} {bits[0]}')
    q = st['queue']
    for r in [x for x in q if x['mode'] in ('mono', 'void')]:
        if sent >= MAX_PINGS: break
        pct = '2%' if r['mode'] == 'mono' else '6%'
        tap_post(f"nhm: rare pull #{r['i']} ({r['mode']}) .. post it",
                 f"rare pull .. #{r['i']} is {r['mode']} ({pct} of outputs)\n\n" + ' · '.join(r['bits'][1:]) + f"\n{OS_ITEM}{r['i']}")
        q.remove(r)
    while q and sent < MAX_PINGS and (len(q) >= ROUNDUP_N or now - min(x['t'] for x in q) >= ROUNDUP_WAIT):
        batch = q[:ROUNDUP_N]
        if len(batch) == 1:
            b = batch[0]; text = f"just minted .. #{b['i']} · " + ' · '.join(b['bits']) + f"\n{OS_ITEM}{b['i']}"
        else:
            text = 'just minted\n' + '\n'.join(f"#{b['i']} · {b['bits'][0]}" for b in batch) + f"\n\n{MINT}\n{OS_ITEM}{batch[-1]['i']}"
        tap_post(f"nhm: {len(batch)} new mint{'s' if len(batch) > 1 else ''} .. post it", text)
        del q[:len(batch)]
    return n, sold_in

if __name__ == '__main__':
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    st.setdefault('next', RESERVES)          # the reserves #0-7 are history, never posted
    for k in ('waves', 'announced', 'reminded'): st.setdefault(k, {})
    st.setdefault('queue', [])
    c = chain()
    n, sold_in = run(st, c)
    # printed only (not saved) so a quiet run leaves state.json unchanged and makes no commit
    print('chain:', c, '· wave', n, '· sold in wave', sold_in)
    if not DRY:
        json.dump(st, open(STATE, 'w'), indent=1)

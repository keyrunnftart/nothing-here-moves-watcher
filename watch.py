# cloud watcher for "nothing here moves" (base 0xB139…02ba) .. runs on github actions every ~10 min.
# reads the sale straight from the chain, remembers what it already sent in state.json (committed back),
# and pings the artist's phone through ntfy:
#   - x posts ready to go (tap → x opens with the text written → post): wave open, 10/30, 20/30, sold out,
#     rare pulls (mono/void), round-ups of 5 mints (or whatever waited 30 min), edition closed
#   - reminders when an owner tx is due: open the next wave (24h after a sellout), close (72h without one)
# it also asks opensea to refresh each new mint's metadata (render landed + once more a run later), so the
# collection page doesn't sit on the pink placeholder.  env: OPENSEA_API_KEY (secret).
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
BYLINE = '"nothing here moves" by keyrun'
SCHEDULED = [
    {'key': 'us-evening-1', 'at': 1790990100},   # sat 3 oct 2026 06:45 ist = fri 18:15 pt
]
SIG = '[automated message · keybot]'
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

def minter(st, i):
    """a public display name for the wallet holding #i: opensea username, else ens/basename, else 0x1234…abcd.
    never an @handle .. keybot doesn't tag people (x automation rules)."""
    addr = '0x' + rpc_call(TOKEN, '0x6352211e' + format(i, '064x'))[-40:]
    names = st.setdefault('names', {})
    if addr not in names:
        name = None
        try:
            key = os.environ.get('OPENSEA_API_KEY')
            if key:
                d = json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.opensea.io/api/v2/accounts/{addr}', headers={'X-API-KEY': key, **UA}), timeout=15))
                name = d.get('username')
        except Exception:
            pass
        if not name:
            try:
                name = json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.ensideas.com/ens/resolve/{addr}', headers=UA), timeout=15)).get('name')
            except Exception:
                pass
        name = (name or '').replace('@', '').strip()[:30]
        names[addr] = name or f'{addr[:6]}…{addr[-4:]}'
    return names[addr]

def meta(i):
    """token json once the render has landed, else None"""
    j = json.load(urllib.request.urlopen(urllib.request.Request(f'https://resolver.abx.io/t/{CHAIN}/{TOKEN}/{i}', headers=UA), timeout=20))
    src = next((p.get('source') for p in j.get('abx_provenance', []) if p.get('field') == 'image'), '')
    return j if src == 'effect:render' else None

# ---------------- phone ----------------
sent = 0
def ping(title, text, click=None, urgent=False, tags=None, budget=True):
    global sent
    if budget: sent += 1
    print(f'[ping] {title} | ' + text.replace('\n', ' / '))
    topic = os.environ.get('NTFY_TOPIC')
    if DRY or not topic: return
    h = {'Title': title.encode('utf-8'), 'Priority': 'urgent' if urgent else 'high', 'Tags': tags or ('rotating_light' if urgent else 'bird')}
    if click: h['Click'] = click
    urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{topic}', data=text.encode('utf-8'), headers={**h, **UA}), timeout=15)

def os_ok(i):
    """True once opensea shows the token with its traits (i.e. it has the real metadata, not the placeholder)"""
    key = os.environ.get('OPENSEA_API_KEY')
    try:
        url = f'https://api.opensea.io/api/v2/chain/base/contract/{TOKEN}/nfts/{i}'
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'X-API-KEY': key, **UA}), timeout=20))['nft']
        return bool(d.get('traits')) and bool(d.get('display_image_url') or d.get('image_url'))
    except Exception:
        return False

def os_refresh(i):
    key = os.environ.get('OPENSEA_API_KEY')
    if DRY or not key: print(f'[opensea] refresh #{i} (skipped)'); return True
    try:
        url = f'https://api.opensea.io/api/v2/chain/base/contract/{TOKEN}/nfts/{i}/refresh'
        urllib.request.urlopen(urllib.request.Request(url, method='POST', data=b'', headers={'X-API-KEY': key, **UA}), timeout=20)
        print(f'[opensea] refreshed #{i}'); return True
    except Exception as e:
        print(f'[opensea] refresh #{i} failed: {e}'); return False

def tap_post(title, text):
    ping(title, text + '\n\n(tap → x opens with this post ready)', 'https://x.com/intent/post?text=' + quote(text, safe=''))

# ---------------- x api (oauth 1.0a user context, stdlib) ----------------
# pay-per-use: $0.015 a post, $0.20 if it contains a link .. so only "wave n is open" carries the mint link;
# everything else goes out with the artwork image and no link.
import hmac, hashlib, base64, secrets as _secrets, urllib.error
XK = {k: os.environ.get(k, '').strip() for k in ('X_API_KEY', 'X_API_SECRET', 'X_ACCESS_TOKEN', 'X_ACCESS_SECRET')}
X_ON = all(XK.values())

def _oauth(method, url):
    enc = lambda x: quote(str(x), safe='~')
    p = {'oauth_consumer_key': XK['X_API_KEY'], 'oauth_nonce': _secrets.token_hex(16), 'oauth_signature_method': 'HMAC-SHA1',
         'oauth_timestamp': str(int(time.time())), 'oauth_token': XK['X_ACCESS_TOKEN'], 'oauth_version': '1.0'}
    base = '&'.join([method, enc(url), enc('&'.join(f'{enc(k)}={enc(v)}' for k, v in sorted(p.items())))])
    key = enc(XK['X_API_SECRET']) + '&' + enc(XK['X_ACCESS_SECRET'])
    p['oauth_signature'] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return 'OAuth ' + ', '.join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(p.items()))

def _x(method, url, data=None, ctype=None):
    h = {'Authorization': _oauth(method, url), **UA}
    if ctype: h['content-type'] = ctype
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=60))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'x {e.code}: {e.read()[:300]!r}')

def x_upload(img):
    """img = an image url (resolver png) or jpeg bytes (a milestone card)"""
    raw = isinstance(img, bytes)
    if not raw: img = urllib.request.urlopen(urllib.request.Request(img, headers=UA), timeout=30).read()
    name, ctype = ('nhm.jpg', 'image/jpeg') if raw else ('nhm.png', 'image/png')
    b = '----nhm' + _secrets.token_hex(8)
    body = (f'--{b}\r\nContent-Disposition: form-data; name="media_category"\r\n\r\ntweet_image\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="media"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n').encode() + img + f'\r\n--{b}--\r\n'.encode()
    r = _x('POST', 'https://api.x.com/2/media/upload', body, f'multipart/form-data; boundary={b}')
    return (r.get('data') or {}).get('id') or r.get('media_id_string')

def x_post(text, images=(), reply_to=None):
    body = {'text': text}
    ids = [m for m in (x_upload(u) for u in list(images)[:4]) if m]
    if ids: body['media'] = {'media_ids': ids}
    if reply_to: body['reply'] = {'in_reply_to_tweet_id': str(reply_to)}
    return _x('POST', 'https://api.x.com/2/tweets', json.dumps(body).encode(), 'application/json')['data']['id']

def publish(title, text, images=(), link=False, reply_to=None):
    """auto-post on x when the keys are there (link lines dropped unless link=True), else a one-tap ping. returns the post id or None"""
    global sent
    if not X_ON or DRY:
        tap_post(title, text); return None
    if not link:
        text = '\n'.join(l for l in text.split('\n') if 'keyrunnft.art' not in l and 'opensea.io' not in l).strip()
    try:
        pid = x_post(text, images, reply_to)
        sent += 1
        print(f'[x] posted {pid} | ' + text.replace('\n', ' / '))
        return pid
    except Exception as e:
        print(f'[x] failed: {e} .. falling back to a one-tap ping')
        tap_post(title + ' (auto-post failed)', text); return None

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

    # sale pings: one phone notification per run for new mints, straight from totalSupply (doesn't wait for
    # the render, doesn't use the x/ping budget). first run sets the baseline, so older mints aren't replayed.
    seen = st.setdefault('sale_pinged', c['supply'])
    if c['supply'] > seen:
        ids = list(range(seen, c['supply']))
        try: who = list(dict.fromkeys(minter(st, i) for i in ids))
        except Exception: who = []
        title = f"nhm: sold #{ids[0]}" if len(ids) == 1 else f"nhm: {len(ids)} sold (#{ids[0]}–#{ids[-1]})"
        text = (f"{'minted by ' + ', '.join(who) if who else 'new mint'}\n"
                f"wave {n} · {sold_in}/{WAVE} · +{eth(c['price'] * len(ids))} eth\n{c['supply']}/{c['max']} minted")
        try: ping(title, text, click='https://' + OS_ITEM + str(ids[-1]), tags='moneybag', budget=False)
        except Exception as e: print(f'[ping] sale ping failed: {e}')
        st['sale_pinged'] = c['supply']

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

    # new mints → queue (in order; stop at the first render that hasn't landed yet)
    while st['next'] < c['supply']:
        i = st['next']
        j = meta(i)
        if j is None: print(f'#{i} render pending'); break
        tr = {a['trait_type']: a['value'] for a in j.get('attributes', [])}
        hero = tr.get('Hero', 'None')
        bits = [tr.get('Mode', '').lower()] + ([hero.lower()] if hero != 'None' else []) + [tr.get('Palette', '').lower(), tr.get('Drift Strength', '').lower() + ' drift']
        st['queue'].append({'i': i, 'mode': bits[0], 'bits': [b for b in bits if b], 't': now, 'img': j.get('image')})
        st['minted'][str(i)] = {'mode': bits[0], 'img': j.get('image')}
        st['last_img'] = j.get('image')
        st['refresh'].append({'i': i, 'left': 12})
        st['next'] = i + 1
        print(f'new #{i} {bits[0]}')

    # x posts
    xid = st['xids']
    pending = st['next'] < c['supply']   # a render hasn't landed yet .. card posts wait a run so the grid is complete
    def post_once(key, title, text, link=False, img=True, card_fn=None):
        if key not in ann and sent < MAX_PINGS:
            imgs = card_fn() if card_fn else None
            if not imgs: imgs = [st['last_img']] if img and st.get('last_img') else []
            pid = publish(title, text, imgs, link=link)
            ann[key] = now
            if pid: xid[key] = pid
    def mcard(ids, headline, sub, footer, left='MINT.KEYRUNNFT.ART'):
        """milestone card (one jpeg, art grid) .. None on any failure, so the post falls back to the last mint image"""
        try:
            import card
            tiles = [(i, st['minted'][str(i)]['mode'], st['minted'][str(i)]['img']) for i in ids if st['minted'].get(str(i), {}).get('img')]
            return [card.card(tiles, headline, sub, footer, left)] if tiles else None
        except Exception as e:
            print(f'[card] failed: {e}'); return None
    public = sorted(int(k) for k in st['minted'] if int(k) >= RESERVES)
    # wordings agreed with the artist 2 oct 2026: line 1 = what happened, byline, details, sign-off.
    # links ($0.20 a post) only on wave open, 10/30, 20/30, sold out, rare pulls and the close.
    # cards (approved 3 oct 2026): 10/20 = latest 4 mints 2x2; sold out = the whole wave; closed = every public mint (≤60).
    for k in range(1, n + 1):   # one open post per wave (also catches up if a run was missed)
        price = BASE_PRICE + STEP * (k - 1)
        post_once(f'{k}:open', f'nhm: wave {k} is open .. post it',
                  f"wave {k} is open\n{BYLINE}\n\n{WAVE} editions · {eth(price)} eth · on base\ngenerated on-chain at mint .. nobody sees it before it lands\n{MINT}\n\n{SIG}",
                  link=True, img=False)

    # opensea: keep asking for a refresh every run until opensea shows the traits (max 12 runs ≈ 2h)
    for r in list(st['refresh'])[:30]:
        if not DRY and os.environ.get('OPENSEA_API_KEY') and os_ok(r['i']):
            print(f"[opensea] #{r['i']} ok"); st['refresh'].remove(r); continue
        os_refresh(r['i'])
        r['left'] = r.get('left', 12) - 1
        if r['left'] <= 0: st['refresh'].remove(r)
    q = st['queue']
    for r in [x for x in q if x['mode'] in ('mono', 'void')]:
        if sent >= MAX_PINGS: break
        pct = '2%' if r['mode'] == 'mono' else '6%'
        publish(f"nhm: rare pull #{r['i']} ({r['mode']}) .. post it",
                f"rare pull .. #{r['i']} is {r['mode']} ({pct} of outputs)\n{BYLINE}\n\n" + ' · '.join(r['bits'][1:])
                + f"\nminted by {minter(st, r['i'])}\n{MINT}\n\n{SIG}",
                [r['img']] if r.get('img') else [], link=True)
        q.remove(r)
    size = 4 if X_ON else ROUNDUP_N      # x takes at most 4 images a post
    wait = 0 if X_ON else ROUNDUP_WAIT   # auto-posting: every new mint goes out on the next run (≤5-10 min)
    while q and sent < MAX_PINGS and (len(q) >= size or now - min(x['t'] for x in q) >= wait):
        batch = q[:size]
        tail = f"wave {n} · {sold_in}/{WAVE} · {eth(BASE_PRICE + STEP * (n - 1))} eth · mint link in bio\n\n{SIG}"
        who = list(dict.fromkeys(minter(st, b['i']) for b in batch))   # unique, in order
        by = f"minted by {who[0]}" if len(who) == 1 else (f"minted by {who[0]} and {who[1]}" if len(who) == 2 else f"minted by {len(who)} collectors")
        if len(batch) == 1:
            b = batch[0]
            text = f"just minted .. #{b['i']}\n{BYLINE}\n\n" + ' · '.join(b['bits']) + f"\n{by}\n{tail}"
        else:
            text = (f"just minted .. " + ', '.join(f"#{b['i']}" for b in batch) + f"\n{BYLINE}\n\n"
                    + ' · '.join(f"#{b['i']} {b['bits'][0]}" for b in batch) + f"\n{by}\n{tail}")
        publish(f"nhm: {len(batch)} new mint{'s' if len(batch) > 1 else ''} .. post it", text,
                [b['img'] for b in batch if b.get('img')])   # a main post, so it shows on the profile timeline
        del q[:len(batch)]

    # milestones after the mint posts, so "10/30" lands after the mint that made it 10 (and waits if mints are still queued)
    if closed and not pending and not q:
        post_once('closed', 'nhm: edition closed .. post it',
                  f"nothing here moves is closed at {c['supply']} editions\n{BYLINE}\n\nthank you to everyone who minted .. secondary on opensea\n{OS_COLL}\n\n{SIG}",
                  link=True, card_fn=lambda: mcard(public[-60:], f"CLOSED AT {c['supply']}", f'{len(public)} MINTED IN PUBLIC', 'ON BASE', 'SECONDARY ON OPENSEA'))
    if n and not pending and not q:
        price = BASE_PRICE + STEP * (n - 1)
        for m in (10, 20):
            if m <= sold_in < WAVE:
                post_once(f'{n}:{m}', f'nhm: wave {n} at {sold_in}/{WAVE} .. post it',
                          f"wave {n} · {sold_in}/{WAVE} minted\n{BYLINE}\n\n{WAVE - sold_in} left at {eth(price)} eth\n{MINT}\n\n{SIG}", link=True,
                          card_fn=lambda: mcard(public[-4:], f'WAVE {n} · {sold_in}/{WAVE}', f'MINTED  ·  {WAVE - sold_in} LEFT', f'{eth(price)} ETH  ·  ON BASE'))
        if w.get('soldOutAt'):
            took = dur(w['soldOutAt'] - w['openedAt'])
            wave_ids = [i for i in public if (i - RESERVES) // WAVE == n - 1]
            if c['supply'] >= c['max']:
                text = f"wave {n} sold out in {took} .. that was the last one, the edition is complete\n{BYLINE}\n\nthank you .. secondary on opensea\n{OS_COLL}\n\n{SIG}"
                fn = lambda: mcard(wave_ids, f'WAVE {n} · SOLD OUT', f'{WAVE} / {WAVE} IN {took.upper()}', 'EDITION COMPLETE', 'SECONDARY ON OPENSEA')
            else:
                text = (f"wave {n} sold out in {took} .. thank you\n{BYLINE}\n\n"
                        f"wave {n + 1} opens {when(w['soldOutAt'] + BREAK_H * 3600)} · {eth(BASE_PRICE + STEP * n)} eth\n{MINT}\n\n{SIG}")
                nxt = when(w['soldOutAt'] + BREAK_H * 3600).split(',')[0].upper()
                fn = lambda: mcard(wave_ids, f'WAVE {n} · SOLD OUT', f'{WAVE} / {WAVE} IN {took.upper()}', f'WAVE {n + 1}  ·  {eth(BASE_PRICE + STEP * n)} ETH  ·  {nxt}')
            post_once(f'{n}:sold', f'nhm: wave {n} sold out .. post it', text, link=True, card_fn=fn)

    # one-off scheduled posts with live numbers (sent once, only within 3h of their time so a late run never posts stale)
    if n and not closed:
        for sp in SCHEDULED:
            if sp['key'] in ann or not (sp['at'] <= now < sp['at'] + 3 * 3600) or sent >= MAX_PINGS: continue
            modes = [m['mode'] for k, m in st['minted'].items() if int(k) >= RESERVES]
            rare = {r: modes.count(r) for r in ('void', 'mono') if modes.count(r)}
            rline = ('no void or mono pulled yet' if not rare else
                     ' and '.join(f"{c} {r}" for r, c in rare.items()) + ' found so far')
            imgs = [st['minted'][k]['img'] for k in sorted(st['minted'], key=int)[-4:] if st['minted'][k].get('img')]
            text = (f"wave {n} of nothing here moves · {sold_in}/{WAVE} minted\n{BYLINE}\n\n"
                    f"a still image. zero frames of animation. it still moves.\n"
                    f"each one is generated on-chain at mint .. {rline}\n"
                    f"{WAVE - sold_in} left at {eth(BASE_PRICE + STEP * (n - 1))} eth\n{MINT}\n\n{SIG}")
            if publish(f"nhm: {sp['key']} .. post it", text, imgs, link=True) or not X_ON:
                ann[sp['key']] = now
    return n, sold_in

if __name__ == '__main__':
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    st.setdefault('next', RESERVES)          # the reserves #0-7 are history, never posted
    for k in ('waves', 'announced', 'reminded'): st.setdefault(k, {})
    st.setdefault('queue', [])
    st.setdefault('refresh', [])
    st.setdefault('xids', {})
    if 'minted' not in st:   # backfill what was minted before this field existed
        st['minted'] = {}
        for i in range(RESERVES, st['next']):
            try:
                j = meta(i)
                if j: st['minted'][str(i)] = {'mode': next((a['value'] for a in j.get('attributes', []) if a['trait_type'] == 'Mode'), '').lower(), 'img': j.get('image')}
            except Exception as e:
                print(f'backfill #{i}: {e}')
    if '--test-post' in sys.argv:
        # one real post to check the x keys (delete it afterwards); touches no state
        print('x keys:', 'all 4 set' if X_ON else 'MISSING ' + ', '.join(k for k, v in XK.items() if not v))
        pid = x_post('test .. checking an automation, ignore (will be deleted)', [f'https://resolver.abx.io/t/{CHAIN}/{TOKEN}/2/image'])
        print(f'[x] test posted: https://x.com/keyrunnftart/status/{pid}')
        sys.exit(0)
    c = chain()
    n, sold_in = run(st, c)
    # printed only (not saved) so a quiet run leaves state.json unchanged and makes no commit
    print('chain:', c, '· wave', n, '· sold in wave', sold_in)
    if not DRY:
        json.dump(st, open(STATE, 'w'), indent=1)

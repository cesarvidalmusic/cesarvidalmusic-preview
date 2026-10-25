"""Browser regression checks: python3 tests/test_page_transitions.py."""

import argparse
import asyncio
import functools
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted(p.name for p in ROOT.glob('*.html'))
GALLERY_COLORS = {
    'des-visages.html': 'rgb(196, 15, 20)',
    'spam.html': 'rgb(230, 223, 197)',
    'des-visages-ep.html': 'rgb(0, 0, 0)',
    'nubes.html': 'rgb(0, 0, 0)',
    'flor-de-loto.html': 'rgb(0, 0, 0)',
    'aleas.html': 'rgb(0, 0, 0)',
    'artikulation-band.html': 'rgb(0, 0, 0)',
}
PAGE_COLORS = {
    **GALLERY_COLORS,
    'index.html': 'rgb(0, 0, 0)',
    'bio.html': 'rgb(255, 255, 255)',
    'contact.html': 'rgb(0, 0, 0)',
    'music-projects.html': 'rgb(255, 255, 255)',
    'gonzalez-reeds.html': 'rgb(255, 255, 255)',
    'merch.html': 'rgb(255, 255, 255)',
}
PHOTO_IMAGES = {
    'index.html': 'hero-home.webp',
    'gonzalez-reeds.html': 'gonzalez-transition.webp',
    'contact.html': 'contact-transition.webp',
    'aleas.html': 'aleas-transition.webp',
    'bio.html': 'bio-transition.webp',
    'artikulation-band.html': 'artikulation-video-1.webp',
    'des-visages.html': 'des-visages-transition.webp',
    'spam.html': 'spam-transition.webp',
    'des-visages-ep.html': 'des-visages-ep-transition.webp',
    'flor-de-loto.html': 'flor-de-loto-transition.webp',
    'nubes.html': 'nubes-transition.webp',
}
LIVE_PAGES = {'music-projects.html'}


def route_color(source, destination):
    return PAGE_COLORS[destination]


INSTRUMENT = """
window.fadeRuns = [];
window.fadeEnds = [];
window.fadeSamples = [];
const seen = new Set();
new MutationObserver(() => {
  const curtain = document.querySelector('.cv-transition-curtain');
  if (curtain) for (const animation of curtain.getAnimations()) {
    if (seen.has(animation)) continue;
    seen.add(animation);
    const duration = animation.effect.getTiming().duration / 1000;
    animation.finished.then(() => console.debug('__cv_exit__' + JSON.stringify({
      duration, opacity: getComputedStyle(curtain).opacity})), () => {});
  }
  const overlay = document.querySelector('.cv-transition-entering');
  if (!overlay) return;
  for (const animation of overlay.getAnimations()) {
    if (seen.has(animation)) continue;
    seen.add(animation);
    const style = getComputedStyle(overlay);
    const photo = getComputedStyle(overlay, '::before');
    const content = document.querySelector('[data-page-transition-content]');
    const contentAnimation = content?.getAnimations()[0];
    const seconds = animation.effect.getTiming().duration / 1000;
    window.fadeRuns.push({duration: seconds, background: style.backgroundColor,
      gradient: style.backgroundImage,
      photo: photo.backgroundImage.includes('data:image/') ? 'prepared-gallery-preview' : photo.backgroundImage,
      live: document.documentElement.classList.contains('cv-transition-to-music-live'),
      photoTransform: photo.transform, photoBlur: photo.filter,
      contentFrames: contentAnimation?.effect.getKeyframes().map(frame => frame.filter) || [],
      cards: document.querySelectorAll('.cv-mp-card').length});
    animation.finished.then(() => {
      if (!fadeEnds.includes(seconds)) fadeEnds.push(seconds);
    }, () => {});
  }
}).observe(document, {subtree: true, attributes: true, attributeFilter: ['class']});
document.addEventListener('transitionend', event => {
  if (event.target.classList.contains('cv-transition-entering') &&
      event.propertyName === 'opacity' && !fadeEnds.includes(event.elapsedTime)) {
    // CSS fallbacks may be cleaned up before their finished promise resolves.
    fadeEnds.push(event.elapsedTime);
  }
  if (event.target.classList.contains('cv-transition-curtain') &&
      event.propertyName === 'opacity') {
    console.debug('__cv_exit__' + JSON.stringify({duration: event.elapsedTime,
      opacity: getComputedStyle(event.target).opacity}));
  }
});
document.addEventListener('animationend', event => {
  if (event.target.classList.contains('cv-transition-entering') &&
      event.animationName === 'cv-transition-overlay-in' && !fadeEnds.includes(event.elapsedTime)) {
    fadeEnds.push(event.elapsedTime);
  }
});
function sample() {
  if (document.documentElement.classList.contains('cv-transition-reveal')) {
    fadeSamples.push(Number(getComputedStyle(document.querySelector('.cv-transition-entering')).opacity));
  }
  requestAnimationFrame(sample);
}
requestAnimationFrame(sample);
"""


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.code = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and 'src' not in dict(attrs):
            self.code = []

    def handle_data(self, data):
        if self.code is not None:
            self.code.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.code is not None:
            subprocess.run(['node', '--check'], input=''.join(self.code),
                           text=True, capture_output=True, check=True)
            self.code = None


def check_installation():
    subprocess.run(['node', '--check', str(ROOT / 'page-transition.js')], check=True)
    subprocess.run(['node', '--check', str(ROOT / 'gallery-transition.js')], check=True)
    assert not (ROOT / 'CNAME').exists(), 'The preview must not bind the official domain'
    for name in PAGES:
        html = (ROOT / name).read_text()
        version = 21
        assert html.count(f'src="page-transition.js?v={version}"') == 1, name
        assert html.count('src="gallery-transition.js?v=1"') == 1, name
        assert html.count(f'href="css/page-transition.css?v={version}"') == 1, name
        assert html.count('data-page-transition-content') == 1, name
        assert html.count('class="cv-transition-entering"') == 1, name
        assert html.index('cv-page-transition') < html.index('<link'), name
        InlineScripts().feed(html)
    assert len(PAGES) >= 13


async def new_page(browser, base, *, mobile=False, reduced=False, init='', external_filter=True):
    context = await browser.new_context(
        viewport={'width': 390, 'height': 844} if mobile else {'width': 1440, 'height': 1000},
        is_mobile=mobile, has_touch=mobile,
        reduced_motion='reduce' if reduced else 'no-preference',
    )
    origin = urlsplit(base).netloc

    async def local_only(route):
        # The suite checks navigation, not third-party music playback.
        if urlsplit(route.request.url).netloc == origin:
            await route.continue_()
        else:
            await route.abort()

    if external_filter:
        await context.route('**/*', local_only)
    await context.add_init_script(INSTRUMENT + init)
    page = await context.new_page()
    page.errors = []
    page.exits = []
    page.on('pageerror', lambda error: page.errors.append(str(error)))
    page.on('console', lambda message: page.exits.append(json.loads(message.text[11:]))
            if message.text.startswith('__cv_exit__') else None)
    return context, page


async def direct(page, base, name):
    response = await page.goto(base + name, wait_until='domcontentloaded')
    assert response.status == 200, name
    if name == 'music-projects.html':
        await page.evaluate('window.cvPageReady')
        await page.wait_for_function("document.querySelectorAll('.cv-mp-card').length >= 8")
    assert not await page.evaluate('window.fadeRuns.length'), name


async def check_entry(page, destination, *, reduced=False, color=None):
    if color is None:
        color = PAGE_COLORS[destination]
    await page.wait_for_url('**/' + destination, wait_until='domcontentloaded', timeout=25000)
    await page.wait_for_function('window.fadeEnds.length === 1', timeout=6000)
    await page.wait_for_function("!document.documentElement.classList.contains('cv-transition-incoming')")
    result = await page.evaluate("""({runs:fadeRuns, ends:fadeEnds, samples:fadeSamples,
      pending:sessionStorage.getItem('cv-page-transition'),
      overlay:getComputedStyle(document.querySelector('.cv-transition-entering')).opacity,
      filter:getComputedStyle(document.querySelector('[data-page-transition-content]')).filter,
      transform:getComputedStyle(document.querySelector('[data-page-transition-content]')).transform})""")
    duration = 0.1 if reduced else 0.65
    assert len(result['runs']) == 1 and result['ends'] == [duration], (destination, result)
    run = result['runs'][0]
    if destination in PHOTO_IMAGES or destination in LIVE_PAGES:
        if destination in LIVE_PAGES:
            assert run['live'] and run['photo'] in ('prepared-gallery-preview', 'none'), result
            assert run['background'] == 'rgba(0, 0, 0, 0)', result
            assert run['photoTransform'] == 'matrix(1.008, 0, 0, 1.008, 0, 0)', result
        else:
            assert PHOTO_IMAGES[destination] in run['photo'], result
        assert run['photoBlur'].startswith('blur(') and (reduced or run['photoBlur'] != 'blur(0px)'), result
        assert run['contentFrames'][0] == f"blur({0 if reduced else 48}px) brightness(1)", result
        assert run['contentFrames'][-1] == 'blur(0px) brightness(1)', result
    else:
        assert run['background'] == color, result
        assert run['gradient'] == 'none', result
    assert result['runs'][0]['duration'] == duration, result
    if not reduced:
        assert any(0 < value < 1 for value in result['samples']), result
    if destination == 'music-projects.html':
        assert result['runs'][0]['cards'] >= 8, result
    assert result['pending'] is None and result['overlay'] == '0', result
    assert result['filter'] == 'none' and result['transform'] == 'none', result
    assert not page.errors, page.errors


async def links_on_page(page, base, source):
    links = await page.locator('a[href]').evaluate_all("""links => links
      .filter(link => !link.hasAttribute('download') &&
        (!link.target || link.target === '_self') &&
        !link.closest('.cv-nav-soon, [aria-disabled="true"]'))
      .map(link => ({href:link.getAttribute('href'), url:link.href}))""")
    edges = {}
    for link in links:
        if not link['url'].startswith(base):
            continue
        target = urlsplit(link['url']).path[len(urlsplit(base).path):] or 'index.html'
        if target in PAGES and target != source:
            edges[target] = link['href']
    return edges


async def navigation_graph(browser, base, sources, worker):
    context, page = await new_page(browser, base)
    checked = []
    for source in sources:
        await direct(page, base, source)
        edges = await links_on_page(page, base, source)
        assert edges, source
        for destination, href in sorted(edges.items()):
            await direct(page, base, source)
            page.exits.clear()
            link = page.locator(f'a[href="{href}"]').first
            if source == 'music-projects.html' and destination not in (
                    'index.html', 'bio.html', 'contact.html', 'gonzalez-reeds.html'):
                # Off-screen moving cards still use the actual delegated handler.
                await page.wait_for_timeout(80)
                await link.evaluate('(link) => link.click()')
            else:
                await link.click()
            await check_entry(page, destination, color=route_color(source, destination))
            assert page.exits and abs(page.exits[-1]['duration'] - 0.5) < 0.005, (source, destination, page.exits)
            assert page.exits[-1]['opacity'] == '1'
            checked.append([source, destination])
        print(json.dumps({'worker': worker, 'page': source, 'links_passed': len(edges)}), flush=True)
    await context.close()
    return checked


async def mobile_cycle(browser, base, *, reduced=False):
    context, page = await new_page(browser, base, mobile=True, reduced=reduced)
    visits = ['index.html', 'bio.html', 'gonzalez-reeds.html', 'contact.html',
              'music-projects.html', 'nubes.html', 'spam.html', 'des-visages.html',
              'des-visages-ep.html', 'aleas.html', 'flor-de-loto.html',
              'artikulation-band.html', 'merch.html', 'index.html']
    await direct(page, base, visits[0])
    for source, destination in zip(visits, visits[1:]):
        await page.wait_for_timeout(80)
        # Some existing mobile menu entries are off-screen; layout is outside scope.
        await page.evaluate("""name => {
          const link = document.createElement('a'); link.href = name;
          document.body.appendChild(link); link.click(); link.remove();
        }""", destination)
        await check_entry(page, destination, reduced=reduced, color=route_color(source, destination))
    await page.go_back(wait_until='domcontentloaded')
    await page.wait_for_function("!document.documentElement.className.includes('cv-transition-') && !document.querySelector('.cv-transition-curtain')")
    assert not page.errors, page.errors
    await context.close()
    return {'mobile_reduced_motion' if reduced else 'mobile': len(visits) - 1}


async def delayed_load(browser, base, label, pattern, seconds):
    context, page = await new_page(browser, base)
    await direct(page, base, 'bio.html')

    async def delayed(route):
        await asyncio.sleep(seconds)
        await route.continue_()

    await page.route(pattern, delayed)
    await page.locator('a[href="music-projects.html"]').click()
    await check_entry(page, 'music-projects.html')
    await page.unroute_all(behavior='wait')
    await page.locator('nav a[href="contact.html"]').click()
    await check_entry(page, 'contact.html')
    await context.close()
    return label


async def failure_and_link_checks(browser, base):
    context, page = await new_page(browser, base)
    await direct(page, base, 'bio.html')
    result = await page.evaluate("""() => {
      const cases = [
        ['bio.html#section', {}], ['contact.html', {metaKey:true}],
        ['contact.html', {ctrlKey:true}], ['contact.html', {shiftKey:true}],
        ['contact.html', {altKey:true}], ['contact.html', {button:1}],
        ['https://example.com/bio.html', {}], ['../different-site/bio.html', {}],
        ['contact.html', {}, {target:'_blank'}],
        ['contact.html', {}, {download:'contact.html'}]
      ];
      return cases.map(([href, options, attributes]) => {
        const link=document.createElement('a');link.href=href;
        for(const [key,value] of Object.entries(attributes||{})) link.setAttribute(key,value);
        document.body.appendChild(link);
        let intercepted;
        document.addEventListener('click',event=>{
          intercepted=event.defaultPrevented;event.preventDefault();
        },{once:true});
        link.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,...options}));
        link.remove();return {href,intercepted};
      });
    }""")
    assert all(not case['intercepted'] for case in result), result
    await page.locator('.cv-nav-soon a').evaluate('(link) => link.click()')
    assert not await page.locator('.cv-transition-curtain').count()
    await context.close()

    context, page = await new_page(browser, base, init="Storage.prototype.setItem = () => { throw new DOMException('Blocked','SecurityError'); };")
    await direct(page, base, 'bio.html')
    await page.locator('a[href="contact.html"]').click()
    await page.wait_for_url('**/contact.html', wait_until='domcontentloaded')
    assert not await page.evaluate('fadeRuns.length') and not page.errors
    await context.close()

    for pattern in ('**/page-transition.js?*', '**/css/page-transition.css?*'):
        context, page = await new_page(browser, base)
        await direct(page, base, 'bio.html')
        await page.route(pattern, lambda route: route.abort())
        await page.locator('a[href="contact.html"]').click()
        await page.wait_for_url('**/contact.html', wait_until='domcontentloaded')
        await page.wait_for_function("!document.documentElement.classList.contains('cv-transition-incoming')")
        assert not page.errors
        await context.close()
    return 'external/modifier/disabled links and missing-resource/storage fallbacks'


async def gallery_scene_alignment(browser, base):
    cases = []
    for mobile in (False, True):
        for view in ('moving', 'overview'):
            context, page = await new_page(browser, base, mobile=mobile)
            await direct(page, base, 'bio.html')
            await page.evaluate('(view)=>sessionStorage.setItem("cv-mp-view",view)', view)
            scene = await page.evaluate('''async () => {
              const scene=cvGalleryTransition.prepare();await scene.ready;
              return {seed:scene.seed,hasImage:!!scene.image,layout:scene.layout};
            }''')
            assert scene['hasImage'] and scene['layout'], scene
            assert not await page.locator('iframe[data-cv-gallery-preview]').count()
            await page.locator('nav a[href="music-projects.html"]').click()
            await check_entry(page, 'music-projects.html')
            await page.evaluate('pauseGallery()')
            actual = await page.evaluate('''() => {
              const clip=document.querySelector('.cv-mp-stage').getBoundingClientRect();
              return Array.from(document.querySelectorAll('.cv-mp-cover')).flatMap(image=>{
                const box=image.getBoundingClientRect();
                return box.width && box.right>clip.left && box.left<clip.right && box.bottom>clip.top && box.top<clip.bottom
                  ? [{project:image.closest('.cv-mp-card').dataset.project,x:box.x,y:box.y,width:box.width}] : [];
              });
            }''')
            assert [a['project'] for a in actual] == [a['project'] for a in scene['layout']], (scene, actual)
            for a, b in zip(actual, scene['layout']):
                assert abs(a['x'] - b['x']) < 1 and abs(a['width'] - b['width']) < 1, (a, b)
                # Moving covers naturally travel during the 650 ms reveal.
                assert abs(a['y'] - b['y']) < (40 if view == 'moving' else 1), (a, b)
            assert await page.evaluate('window.cvMusicTransitionSeed') == scene['seed']
            assert not await page.evaluate('document.documentElement.style.getPropertyValue("--cv-transition-live-image")')
            assert not page.errors, page.errors
            cases.append({'mobile': mobile, 'view': view, 'matching_covers': len(actual)})
            await context.close()
    return cases


async def warm_cache_and_gallery(browser, base):
    context, page = await new_page(browser, base, external_filter=False)
    await direct(page, base, 'index.html')
    for destination in ('bio.html', 'gonzalez-reeds.html', 'contact.html', 'index.html', 'bio.html'):
        await page.locator(f'nav a[href="{destination}"]').click()
        await check_entry(page, destination)
    cached = await page.evaluate("""performance.getEntriesByType('resource').filter(
      entry => entry.name.includes('page-transition.js') && entry.transferSize === 0).length""")
    assert cached, 'Expected a cached transition script'
    await context.close()

    context, page = await new_page(browser, base)
    await direct(page, base, 'music-projects.html')
    await page.wait_for_timeout(100)
    card = await page.locator('.cv-mp-card[href]').evaluate_all("""links => {
      for (const link of links) {
        const box = link.getBoundingClientRect();
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        if (x > 30 && x < innerWidth - 30 && y > 100 && y < innerHeight - 80)
          return {x, y, destination: new URL(link.href).pathname.split('/').pop()};
      }
      return null;
    }""")
    assert card, 'Expected a visible gallery card'
    await page.mouse.click(card['x'], card['y'])
    await check_entry(page, card['destination'], color=GALLERY_COLORS.get(card['destination']))
    await context.close()
    return {'warm_cache_navigations': 5, 'visible_gallery_card': card['destination']}


class QuietHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'public, max-age=600')
        super().end_headers()

    def log_message(self, *args):
        pass


class TestServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, address)


async def run(base, suite):
    check_installation()
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        results = {'html_pages': len(PAGES), 'third_party_playback': 'not tested'}
        if suite in ('all', 'graph'):
            groups = await asyncio.gather(*(navigation_graph(browser, base, PAGES[i::3], i) for i in range(3)))
            edges = [edge for group in groups for edge in group]
            assert {source for source, _ in edges} == set(PAGES)
            assert len(edges) >= 60, len(edges)
            results['internal_links_passed'] = len(edges)
            results['edges'] = edges
        if suite in ('all', 'mobile'):
            results['mobile'] = await mobile_cycle(browser, base)
            results['reduced_motion'] = await mobile_cycle(browser, base, reduced=True)
        if suite in ('all', 'resilience'):
            results['gallery_scene_alignment'] = await gallery_scene_alignment(browser, base)
            results['fallbacks'] = await failure_and_link_checks(browser, base)
            results['cache_and_gallery'] = await warm_cache_and_gallery(browser, base)
            results['delayed_loads'] = await asyncio.gather(
                delayed_load(browser, base, 'script_12.4s', '**/page-transition.js?*', 12.4),
                delayed_load(browser, base, 'stylesheet_12.4s', '**/css/page-transition.css?*', 12.4),
                delayed_load(browser, base, 'document_12.4s', '**/music-projects.html', 12.4),
                delayed_load(browser, base, 'gallery_images_1.6s', '**/img/*', 1.6),
            )
        await browser.close()
    print(json.dumps({'status': 'passed', **results}), flush=True)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all', 'graph', 'mobile', 'resilience'), default='all')
    parser.add_argument('--base-url')
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    server = None
    try:
        base = args.base_url
        if not base:
            server = TestServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT.parent)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}/{ROOT.name}/'
        result = asyncio.run(run(base.rstrip('/') + '/', args.suite))
        if args.results:
            args.results.write_text(json.dumps({'status': 'passed', **result}, indent=2))
    finally:
        if server:
            server.shutdown()
            server.server_close()

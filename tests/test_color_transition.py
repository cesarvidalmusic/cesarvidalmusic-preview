"""Exercise the gallery-to-Des-Visages color prototype in a real browser."""

import asyncio
import functools
import json
from pathlib import Path
import re
import threading

from playwright.async_api import async_playwright

from test_page_transitions import (
    ROOT, QuietHandler, TestServer, check_installation, new_page, direct, check_entry,
)


SAMPLE_COLORS = """
const colors = [];
const colorAnimations = new Set();
function colorFrame() {
  const curtain = document.querySelector('.cv-transition-curtain');
  if (curtain && document.documentElement.classList.contains('cv-transition-gallery-to-des-visages')) {
    const style = getComputedStyle(curtain);
    colors.push({background:style.backgroundColor, gradient:style.backgroundImage,
      opacity:style.opacity});
    for (const animation of curtain.getAnimations()) {
      if (colorAnimations.has(animation)) continue;
      colorAnimations.add(animation);
      animation.finished.then(() => {
        colorFrame();
        console.debug('__cv_colors__' + JSON.stringify(colors));
      }, () => {});
    }
  }
}
new MutationObserver(colorFrame).observe(document, {subtree:true, childList:true,
  attributes:true, attributeFilter:['class']});
function colorLoop() { colorFrame(); requestAnimationFrame(colorLoop); }
requestAnimationFrame(colorLoop);
"""


async def color_route(browser, base, *, mobile=False, reduced=False, fallback=False, delayed=False):
    init = SAMPLE_COLORS + ('Element.prototype.animate = undefined;' if fallback else '')
    context, page = await new_page(browser, base, mobile=mobile, reduced=reduced, init=init)
    samples = []
    page.on('console', lambda message: samples.append(json.loads(message.text[13:]))
            if message.text.startswith('__cv_colors__') else None)
    await direct(page, base, 'music-projects.html')
    if delayed:
        async def delay_script(route):
            await asyncio.sleep(0.8)
            await route.continue_()
        await page.route('**/page-transition.js?v=11', delay_script)
    await page.locator('.cv-mp-card[href="des-visages.html"]').first.evaluate('(link)=>link.click()')
    if delayed:
        await page.wait_for_url('**/des-visages.html', wait_until='commit')
        await page.wait_for_function("""() => {
          const overlay=document.querySelector('.cv-transition-entering');
          return overlay && getComputedStyle(overlay).backgroundColor==='rgb(196, 15, 20)' &&
            getComputedStyle(overlay).opacity==='1' && overlay.getAnimations().length===0;
        }""")
    await check_entry(page, 'des-visages.html', reduced=reduced, color=True)
    if delayed:
        await page.unroute('**/page-transition.js?v=11', delay_script)
    assert samples and samples[0], samples
    frames = samples[0]
    rgb = [tuple(map(int, re.findall(r'\d+', frame['background']))) for frame in frames]
    assert rgb[0] == (255, 255, 255) and rgb[-1] == (196, 15, 20), rgb
    assert frames[-1]['opacity'] == '1' and all(f['gradient'] == 'none' for f in frames), frames
    if not reduced:
        assert len({color for color in rgb if color not in ((255, 255, 255), (196, 15, 20))}) >= 2, rgb
    assert all(a[1] >= b[1] for a, b in zip(rgb, rgb[1:])), rgb
    assert abs(page.exits[-1]['duration'] - (0.08 if reduced else 0.5)) < 0.005, page.exits
    assert not await page.evaluate("document.documentElement.className.includes('cv-transition-')")
    # The reverse route and a later visit to Des Visages keep the original wash.
    await page.locator('nav a[href="music-projects.html"]').click()
    await check_entry(page, 'music-projects.html', reduced=reduced)
    await page.locator('nav a[href="bio.html"]').click()
    await check_entry(page, 'bio.html', reduced=reduced)
    await page.evaluate("""() => {
      const link=document.createElement('a'); link.href='des-visages.html';
      document.body.append(link); link.click();
    }""")
    await check_entry(page, 'des-visages.html', reduced=reduced)
    await page.go_back(wait_until='domcontentloaded')
    await page.wait_for_function("!document.documentElement.className.includes('cv-transition-')")
    assert not page.errors, page.errors
    await context.close()
    return {'mobile':mobile, 'reduced':reduced, 'css_fallback':fallback,
            'early_red_cover':delayed, 'color_samples':len(frames)}


async def failures(browser, base):
    for pattern in ('**/page-transition.js?*', '**/css/page-transition.css?*'):
        context, page = await new_page(browser, base)
        await direct(page, base, 'music-projects.html')
        await page.route(pattern, lambda route: route.abort())
        await page.locator('.cv-mp-card[href="des-visages.html"]').first.evaluate('(link)=>link.click()')
        await page.wait_for_url('**/des-visages.html', wait_until='domcontentloaded')
        await page.wait_for_function("!document.documentElement.className.includes('cv-transition-')")
        overlay = await page.locator('.cv-transition-entering').evaluate('''el=>({
          opacity:getComputedStyle(el).opacity, background:getComputedStyle(el).backgroundColor,
          height:el.getBoundingClientRect().height})''')
        if 'page-transition.js' in pattern:
            assert overlay['opacity'] == '0', overlay
        else:
            # With no transition stylesheet the empty div has no visible area.
            assert overlay['height'] == 0 and overlay['background'] == 'rgba(0, 0, 0, 0)', overlay
        assert not page.errors, page.errors
        await context.close()
    context, page = await new_page(browser, base, init="Storage.prototype.setItem=()=>{throw new DOMException('Blocked','SecurityError')}")
    await direct(page, base, 'music-projects.html')
    await page.locator('.cv-mp-card[href="des-visages.html"]').first.evaluate('(link)=>link.click()')
    await page.wait_for_url('**/des-visages.html', wait_until='domcontentloaded')
    assert not await page.evaluate('fadeRuns.length') and not page.errors
    await context.close()


async def run(base):
    check_installation()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        cases = []
        for options in ({'delayed':True}, {'mobile':True}, {'reduced':True},
                        {'fallback':True}, {'fallback':True, 'reduced':True}):
            case = await color_route(browser, base, **options)
            cases.append(case)
            print(json.dumps(case), flush=True)
        await failures(browser, base)
        await browser.close()
    result = {'status':'passed', 'cases':cases, 'failure_paths':3}
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    server = TestServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = asyncio.run(run(f'http://127.0.0.1:{server.server_port}/{ROOT.name}/'))
        if args.results:
            args.results.write_text(json.dumps(result, indent=2))
    finally:
        server.shutdown()
        server.server_close()

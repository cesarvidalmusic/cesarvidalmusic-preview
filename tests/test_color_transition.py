"""Exercise all seven project color transitions in both directions in a real browser."""

import asyncio
import functools
import json
from pathlib import Path
import re
import threading

from playwright.async_api import async_playwright

from test_page_transitions import (
    ROOT, GALLERY_COLORS, QuietHandler, TestServer, check_installation, new_page, direct, check_entry,
)


SAMPLE_COLORS = """
const colors = [];
const colorAnimations = new Set();
function colorFrame() {
  const curtain = document.querySelector('.cv-transition-curtain');
  if (curtain && document.documentElement.className.includes('cv-transition-gallery-to-')) {
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


def check_colors(samples, source_rgb, target_rgb, reduced):
    assert samples and samples[0], samples
    frames = samples[0]
    rgb = [tuple(map(int, re.findall(r'\d+', frame['background']))) for frame in frames]
    assert rgb[0] == source_rgb and rgb[-1] == target_rgb, rgb
    assert frames[-1]['opacity'] == '1' and all(f['gradient'] == 'none' for f in frames), frames
    if not reduced:
        assert len({color for color in rgb if color not in (source_rgb, target_rgb)}) >= 2, rgb
    for channel in range(3):
        direction = 1 if target_rgb[channel] >= source_rgb[channel] else -1
        assert all(direction * (b[channel] - a[channel]) >= 0 for a, b in zip(rgb, rgb[1:])), rgb
    return len(frames)


async def early_cover(page, destination, color):
    await page.wait_for_url('**/' + destination, wait_until='commit')
    await page.wait_for_function("""expected => {
      const overlay=document.querySelector('.cv-transition-entering');
      return overlay && getComputedStyle(overlay).backgroundColor===expected &&
        getComputedStyle(overlay).opacity==='1' && overlay.getAnimations().length===0;
    }""", arg=color)


async def color_route(browser, base, destination='des-visages.html', *, mobile=False, reduced=False, fallback=False, delayed=False):
    target_color = GALLERY_COLORS[destination]
    target_rgb = tuple(map(int, re.findall(r'\d+', target_color)))
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
        await page.route('**/page-transition.js?v=13', delay_script)
    await page.locator(f'.cv-mp-card[href="{destination}"]').first.evaluate('(link)=>link.click()')
    if delayed:
        await early_cover(page, destination, target_color)
    await check_entry(page, destination, reduced=reduced, color=target_color)
    forward_samples = check_colors(samples, (255, 255, 255), target_rgb, reduced)
    assert abs(page.exits[-1]['duration'] - (0.08 if reduced else 0.5)) < 0.005, page.exits
    assert not await page.evaluate("document.documentElement.className.includes('cv-transition-')")
    # Every project returns through its own color to an opaque white gallery cover.
    samples.clear()
    await page.locator('nav a[href="music-projects.html"]').click()
    if delayed:
        await early_cover(page, 'music-projects.html', 'rgb(255, 255, 255)')
    await check_entry(page, 'music-projects.html', reduced=reduced, color='rgb(255, 255, 255)')
    reverse_samples = check_colors(samples, target_rgb, (255, 255, 255), reduced)
    assert abs(page.exits[-1]['duration'] - (0.08 if reduced else 0.5)) < 0.005, page.exits
    assert not await page.evaluate("document.documentElement.className.includes('cv-transition-')")
    if delayed:
        await page.unroute('**/page-transition.js?v=13', delay_script)
    # A subsequent navigation and a visit from Bio keep the original wash.
    await page.locator('nav a[href="bio.html"]').click()
    await check_entry(page, 'bio.html', reduced=reduced)
    await page.evaluate("""destination => {
      const link=document.createElement('a'); link.href=destination;
      document.body.append(link); link.click();
    }""", destination)
    await check_entry(page, destination, reduced=reduced)
    await page.go_back(wait_until='domcontentloaded')
    await page.wait_for_function("!document.documentElement.className.includes('cv-transition-')")
    assert not page.errors, page.errors
    await context.close()
    return {'destination':destination, 'mobile':mobile, 'reduced':reduced, 'css_fallback':fallback,
            'early_color_cover':delayed, 'forward_color_samples':forward_samples,
            'reverse_color_samples':reverse_samples}


async def failures(browser, base, source, destination):
    selector = (f'.cv-mp-card[href="{destination}"]' if source == 'music-projects.html'
                else 'nav a[href="music-projects.html"]')
    for pattern in ('**/page-transition.js?*', '**/css/page-transition.css?*'):
        context, page = await new_page(browser, base)
        await direct(page, base, source)
        await page.route(pattern, lambda route: route.abort())
        await page.locator(selector).first.evaluate('(link)=>link.click()')
        await page.wait_for_url('**/' + destination, wait_until='domcontentloaded')
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
    await direct(page, base, source)
    await page.locator(selector).first.evaluate('(link)=>link.click()')
    await page.wait_for_url('**/' + destination, wait_until='domcontentloaded')
    assert not await page.evaluate('fadeRuns.length') and not page.errors
    await context.close()


async def run(base):
    check_installation()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        cases = []
        for destination in GALLERY_COLORS:
            options = [{'delayed':True}, {'mobile':True}, {'reduced':True}, {'fallback':True}]
            if destination == 'des-visages.html':
                options.append({'fallback':True, 'reduced':True})
            for option in options:
                case = await color_route(browser, base, destination, **option)
                cases.append(case)
                print(json.dumps(case), flush=True)
            await failures(browser, base, 'music-projects.html', destination)
            await failures(browser, base, destination, 'music-projects.html')
        await browser.close()
    result = {'status':'passed', 'cases':cases, 'failure_paths':6 * len(GALLERY_COLORS)}
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

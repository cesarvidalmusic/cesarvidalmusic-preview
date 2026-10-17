"""Exercise complete gallery cycles: python3 tests/test_gallery_motion.py."""

import asyncio
import functools
import json
import threading

from playwright.async_api import async_playwright

from test_page_transitions import ROOT, QuietHandler, TestServer, check_installation


SPEEDS = [22, 30, 18, 26]
DIRECTIONS = [-1, 1, -1, 1]

# Advance the actual animation callback deterministically; other browser frames
# remain live for image decoding, hover transitions and page transitions.
CLOCK = """
const nativeFrame = window.requestAnimationFrame;
let galleryFrame, galleryTime = 1000, nextId = 0;
const ids = new WeakMap();
window.requestAnimationFrame = callback => {
  if (callback.name === 'animate') { galleryFrame = callback; return 0; }
  return nativeFrame(callback);
};
window.stepGallery = elapsed => { galleryTime += elapsed; galleryFrame(galleryTime); };
window.gallerySnapshot = () => {
  const stage = document.getElementById('stage').getBoundingClientRect();
  return {
    top: stage.top, bottom: stage.bottom,
    columns: Array.from(document.querySelectorAll('.cv-mp-track'), track =>
      Array.from(track.children, card => {
        if (!ids.has(card)) ids.set(card, ++nextId);
        const rect = card.getBoundingClientRect(), image = card.querySelector('img');
        const photo = image.getBoundingClientRect();
        return { id: ids.get(card), project: card.dataset.project,
          top: rect.top, bottom: rect.bottom, height: rect.height,
          photoTop: photo.top, photoBottom: photo.bottom,
          photoReady: image.complete && image.naturalWidth > 0 };
      }))
  };
};
"""


def check_coverage(state):
    """Every visible row has a real card; every visible cover has loaded."""
    for column in state['columns']:
        cursor = state['top']
        for card in sorted(column, key=lambda item: item['top']):
            top = max(card['top'], state['top'])
            bottom = min(card['bottom'], state['bottom'])
            if bottom <= top:
                continue
            assert top <= cursor + 0.1, ('Uncovered gallery strip', cursor, card)
            cursor = max(cursor, bottom)
            if card['photoTop'] < state['bottom'] and card['photoBottom'] > state['top']:
                assert card['photoReady'], ('Visible photo is missing', card)
        assert cursor >= state['bottom'] - 0.1, ('Empty bottom strip', cursor, state['bottom'])


def check_unique_projects(state):
    visible = [card for column in state['columns'] for card in column
               if min(card['bottom'], state['bottom']) - max(card['top'], state['top']) > 0.01]
    titles = [card['project'] for card in visible]
    assert len(titles) <= 8, ('More visible slots than projects', titles)
    assert len(titles) == len(set(titles)), ('Repeated visible projects', titles)


def check_recycling(before, after, elapsed):
    """A node may be replaced only after its painted position has left view."""
    for index, (old, new) in enumerate(zip(before['columns'], after['columns'])):
        old_ids = {card['id'] for card in old}
        new_ids = {card['id'] for card in new}
        movement = DIRECTIONS[index] * SPEEDS[index] * elapsed / 1000
        old_by_id = {card['id']: card for card in old}
        for card in new:
            previous = old_by_id.get(card['id'])
            if previous and previous['project'] != card['project']:
                visible = min(previous['bottom'], before['bottom']) - max(previous['top'], before['top'])
                assert visible <= 0.1, ('Project changed while visible', previous, card)
        for card in old:
            if card['id'] in new_ids:
                continue
            visible = min(card['bottom'] + movement, after['bottom']) - max(
                card['top'] + movement, after['top'])
            assert visible <= 0.1, ('Card removed while visible', index, card, visible)
        for card in new:
            if card['id'] in old_ids:
                continue
            visible = min(card['bottom'], after['bottom']) - max(card['top'], after['top'])
            assert visible <= 0.1, ('New card inserted directly into view', index, card)


async def snapshot(page):
    state = await page.evaluate('gallerySnapshot()')
    check_coverage(state)
    check_unique_projects(state)
    return state


async def check_cycles(page):
    await page.evaluate('stepGallery(0)')
    previous = await snapshot(page)
    height = previous['columns'][0][0]['height']
    duration = 3 * height / min(SPEEDS)
    times = {0, duration}
    times.update(range(2, int(duration), 2))
    for speed in SPEEDS:
        cycle = height / speed
        for number in range(1, int(duration / cycle) + 1):
            for offset in (-0.04, 0, 0.04):
                time = number * cycle + offset
                if 0 < time < duration:
                    times.add(time)
        # Both directions: inspect the instant a card enters/leaves the
        # reservation margin and the painted viewport, not only recycling.
        margin = height * 0.025 + 2
        stage_height = previous['bottom'] - previous['top']
        for phase in (margin, height - margin, stage_height + margin,
                      height - stage_height - margin, stage_height, height - stage_height):
            for number in range(int(duration / cycle) + 1):
                for offset in (-0.001, 0, 0.001):
                    time = (number * height + phase) / speed + offset
                    if 0 < time < duration:
                        times.add(time)
    last = 0
    for time in sorted(times):
        elapsed = (time - last) * 1000
        await page.evaluate('elapsed => stepGallery(elapsed)', elapsed)
        current = await snapshot(page)
        check_recycling(previous, current, elapsed)
        previous, last = current, time
    return len(times)


async def check_hover(page):
    cards = page.locator('.cv-mp-col').nth(1).locator('.cv-mp-card')
    stage = await page.locator('#stage').bounding_box()
    for index in range(await cards.count()):
        box = await cards.nth(index).bounding_box()
        top, bottom = max(box['y'], stage['y']), min(box['y'] + box['height'], stage['y'] + stage['height'])
        if bottom - top > 100:
            card = cards.nth(index)
            break
    else:
        raise AssertionError('No visible card to hover')
    await page.mouse.move(box['x'] + box['width'] / 2, (top + bottom) / 2)
    await page.wait_for_timeout(400)
    grown = await card.bounding_box()
    assert abs(grown['width'] / box['width'] - 1.05) < 0.001
    assert await card.evaluate("card => getComputedStyle(card, '::after').opacity") == '0'
    await snapshot(page)
    await page.mouse.move(box['x'] - (grown['width'] - box['width']) / 4, (top + bottom) / 2)
    assert await card.evaluate("card => card.matches(':hover')"), 'Expanded hit area is clipped'
    await page.mouse.move(10, 10)
    await page.wait_for_timeout(400)
    assert await card.evaluate("card => getComputedStyle(card, '::after').opacity") == '1'


async def check_hover_motion(page):
    stage = await page.locator('#stage').bounding_box()
    previous = await snapshot(page)
    for step in range(240):
        if step % 10 == 0:
            # Grow cards right beside either crop boundary during both motions.
            column = (step // 10) % 4
            x = stage['x'] + stage['width'] * (column + 0.5) / 4
            y = stage['y'] + (2 if step % 20 == 0 else stage['height'] - 2)
            await page.mouse.move(x, y)
            await page.wait_for_timeout(60)
        await page.evaluate('stepGallery(200)')
        current = await snapshot(page)
        check_recycling(previous, current, 200)
        previous = current
    await page.mouse.move(10, 10)
    await page.wait_for_timeout(400)


async def check_resize(page, width, height):
    before = await snapshot(page)
    await page.set_viewport_size({'width': width, 'height': height})
    await page.wait_for_timeout(50)
    after = await snapshot(page)
    assert [[card['id'] for card in col] for col in before['columns']] == [
        [card['id'] for card in col] for col in after['columns']]
    previous = after
    for _ in range(200):
        await page.evaluate('stepGallery(200)')
        current = await snapshot(page)
        check_recycling(previous, current, 200)
        previous = current


async def run(base):
    check_installation()
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        for width, height in [(1512, 770), (1440, 773), (1280, 900), (1920, 1080), (390, 844)]:
            page = await browser.new_page(viewport={'width': width, 'height': height}, device_scale_factor=2)
            await page.add_init_script(CLOCK)
            # Reproduce each shuffle while exercising several different decks.
            await page.add_init_script(f"""
                let projectSeed = {width + height};
                Math.random = () => ((projectSeed = (1664525 * projectSeed + 1013904223) >>> 0) / 4294967296);
            """)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            if width == 1512:
                # Exercise initial measurement while the parent is scaled by the page fade-in.
                await page.goto(base + 'bio.html', wait_until='domcontentloaded')
                await page.locator('a[href="music-projects.html"]').click()
                await page.wait_for_url('**/music-projects.html', wait_until='domcontentloaded')
                await page.wait_for_function("!document.documentElement.classList.contains('cv-transition-incoming')")
            else:
                await page.goto(base + 'music-projects.html', wait_until='domcontentloaded')
            await page.evaluate('window.cvPageReady')
            await page.evaluate("Promise.all(Array.from(document.querySelectorAll('.cv-mp-cover'), image => image.decode()))")
            samples = await check_cycles(page)
            await check_hover(page)
            if width == 1512:
                await check_hover_motion(page)
                await check_resize(page, 1440, 900)
            assert not errors, errors
            results.append({'viewport': [width, height], 'cycle_samples': samples})
            await page.close()
        await browser.close()
    print(json.dumps({'status': 'passed', 'gallery_motion': results,
                      'hover_motion_samples': 240, 'resize_samples': 200}))


if __name__ == '__main__':
    server = TestServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(run(f'http://127.0.0.1:{server.server_port}/{ROOT.name}/'))
    finally:
        server.shutdown()
        server.server_close()

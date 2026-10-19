"""Keep both text compositions fixed during gallery reordering."""
import argparse
import asyncio
import functools
import json
from pathlib import Path
import threading

from playwright.async_api import async_playwright
from test_page_transitions import ROOT, QuietHandler, TestServer, new_page, direct
from test_gallery_views import loaded, settled
from test_gallery_motion import CLOCK


MEASURE = """() => {
  const selectors=['.cv-mp-card-title','.cv-mp-card-preview','.cv-mp-card-more','.cv-mp-coming-soon'];
  window.textLayout=container=>selectors.flatMap(selector=>{
    const element=container.querySelector(selector);
    if(!element)return [];
    const box=element.getBoundingClientRect(),css=getComputedStyle(element);
    const scale=box.height/parseFloat(css.height);
    const lineHeight=parseFloat(css.lineHeight)*scale;
    const lines=new Map();
    const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);
    for(let node;node=walker.nextNode();) {
      for(const match of node.textContent.matchAll(/\\S+/g)) {
        const range=document.createRange();range.setStart(node,match.index);range.setEnd(node,match.index+match[0].length);
        for(const rect of range.getClientRects()) {
          if(rect.width<0.01)continue;
          const row=Math.round((rect.y-box.y)/lineHeight);
          if(!lines.has(row))lines.set(row,[]);
          lines.get(row).push(match[0]);
        }
      }
    }
    return [{selector,width:css.width,height:css.height,font:css.fontSize,lineHeight:css.lineHeight,
      lines:Array.from(lines.values(),words=>words.join(' ')),box:box.toJSON()}];
  });
  window.actualText=()=>{
    const stage=document.querySelector('#stage').getBoundingClientRect();
    const selector=document.querySelector('#stage').dataset.view==='overview'?'.cv-mp-overview > .cv-mp-card':'.cv-mp-track > .cv-mp-card';
    return Object.fromEntries(Array.from(document.querySelectorAll(selector)).filter(card=>{
      const box=card.getBoundingClientRect();return box.top<stage.bottom&&box.bottom>stage.top;
    }).map(card=>[card.dataset.project,textLayout(card)]));
  };
}"""


def signature(blocks):
    return [{key: block[key] for key in ['selector', 'width', 'height', 'font', 'lineHeight', 'lines']}
            for block in blocks]


def same_boxes(actual, proxy):
    for original, frozen in zip(actual, proxy):
        assert original['selector'] == frozen['selector']
        assert all(abs(original['box'][key] - frozen['box'][key]) < .2
                   for key in ['x', 'y', 'width', 'height']), (original, frozen)


async def check(browser, base, width, height, out):
    context, page = await new_page(browser, base, init=CLOCK)
    await page.set_viewport_size({'width': width, 'height': height})
    await direct(page, base, 'music-projects.html')
    await loaded(page)
    await page.evaluate(MEASURE)
    await page.evaluate('stepGallery(0);stepGallery(17000)')
    directions = []
    for mode, button in [('overview', 'All projects'), ('moving', 'Moving columns')]:
        source = await page.evaluate('actualText()')
        await page.get_by_role('button', name=button, exact=True).click()
        await page.evaluate("""() => {
          window.textAnimations=document.querySelector('.cv-mp-morph-layer').getAnimations({subtree:true});
          textAnimations.forEach(a=>{a.pause();a.currentTime=0});
        }""")
        reference = None
        for fraction in [0, .05, .12, .15, .2, .25, .3, .5, .75, 1]:
            state = await page.evaluate("""fraction => {
              textAnimations.forEach(a=>a.currentTime=1200*fraction);
              return Array.from(document.querySelectorAll('.cv-mp-morph-card'),card=>({
                project:card.dataset.project,layers:Array.from(card.querySelectorAll('.cv-mp-morph-text'),layer=>({
                  side:layer.dataset.layout,opacity:Number(getComputedStyle(layer).opacity),blocks:textLayout(layer)
                }))
              }));
            }""", fraction)
            assert len(state) == 8 and all(len(card['layers']) == 2 for card in state), state
            current = {card['project']: [signature(layer['blocks']) for layer in card['layers']] for card in state}
            if reference is None:
                reference = current
                for project, blocks in source.items():
                    assert reference[project][0] == signature(blocks), (mode, project, reference[project][0], signature(blocks))
                    proxy = next(card for card in state if card['project'] == project)
                    same_boxes(blocks, proxy['layers'][0]['blocks'])
            assert current == reference, (mode, fraction, current, reference)
            for card in state:
                old, new = [layer['opacity'] for layer in card['layers']]
                assert old == 0 or new == 0, (fraction, card)
                if fraction == 0: assert old == 1 and new == 0
                if fraction == .2: assert 0 < old < 1 and new == 0
                if fraction == .25: assert old == 0 and 0 < new < 1
                if fraction >= .3: assert old == 0 and new == 1
            if out and fraction in [0, .2, .5, 1]:
                await page.screenshot(path=str(out / f'text-{width}-{mode}-{fraction}.png'))
        assert any(layers[0] != layers[1] for layers in reference.values()), reference
        target = await page.evaluate('actualText()')
        for project, blocks in target.items():
            assert reference[project][1] == signature(blocks), (mode, project, reference[project][1], signature(blocks))
            proxy = next(card for card in state if card['project'] == project)
            same_boxes(blocks, proxy['layers'][1]['blocks'])
        await page.evaluate('textAnimations.forEach(a=>a.finish())')
        await settled(page, mode)
        assert not await page.locator('.cv-mp-morph-text').count()
        directions.append(mode)
    assert not page.errors, page.errors
    await context.close()
    return {'viewport': [width, height], 'directions': directions, 'samples_per_direction': 10,
            'fixed_line_breaks': True, 'source_and_target_match': True, 'brief_fade_without_overlap': True}


async def run(base, out):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        results = []
        for width, height in [(1512, 770), (1280, 900), (1920, 1080), (390, 844)]:
            results.append(await check(browser, base, width, height, out))
            print(json.dumps(results[-1]), flush=True)
        await browser.close()
    return {'status': 'passed', 'text': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    out = args.results.parent if args.results else None
    server = TestServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = asyncio.run(run(f'http://127.0.0.1:{server.server_port}/', out))
        if args.results:
            args.results.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    finally:
        server.shutdown()
        server.server_close()

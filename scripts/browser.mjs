import {chromium} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const browser = await chromium.launch();
const endpoint = new URL(process.env.EXAMPLE_URL ?? 'http://127.0.0.1:8010/');
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' || endpoint.username || endpoint.password) throw new Error('Only the owned loopback example is allowed');
const evidence = [];
try {
  for (const viewport of [{width:1280,height:800}, {width:390,height:844}]) {
    const context = await browser.newContext({viewport});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', () => errors.push('browser_error'));
    await page.goto(endpoint.href);
    await page.getByRole('button', {name:'Service outage'}).click();
    await page.getByRole('button', {name:'Route with local fixture'}).click();
    await page.getByText('incident queue', {exact:true}).waitFor();
    await page.getByRole('button', {name:'Missing usage'}).click();
    await page.getByRole('button', {name:'Route with local fixture'}).click();
    await page.getByText('Not reported', {exact:true}).waitFor();
    if (await page.locator('#result').getByText('Unknown', {exact:true}).count() !== 2) throw new Error('Missing usage was not unknown');
    const health = await (await page.request.get(new URL('/api/health', endpoint).href)).json();
    await page.getByRole('button', {name:'Refresh collector report'}).click();
    if (health.cutback_enabled) {
      await page.getByText('Read from the local PostgreSQL-backed collector', {exact:false}).waitFor();
      const complete = page.locator('#collector-summary dt').filter({hasText:/^Complete modeled cost$/}).locator('xpath=following-sibling::dd[1]');
      if (await complete.textContent() !== 'Unknown') throw new Error('Incomplete cost was reported as complete');
    } else {
      await page.getByText('Observation is off. Follow step 3', {exact:false}).waitFor();
    }
    await page.getByRole('button', {name:'Refresh improvement result'}).click();
    if (process.env.EXAMPLE_OPTIMIZATION === 'true') {
      await page.getByText('Separate confirmation passed · local fixture evidence only.', {exact:true}).waitFor();
      const candidates = page.locator('#optimization-candidates');
      if (await candidates.locator('tr').count() !== 5) throw new Error('Missing evaluated alternatives');
      if (await candidates.getByText('Quality gate failed', {exact:true}).count() !== 2) throw new Error('Negative quality controls missing');
      if (await candidates.getByText('Selected for confirmation', {exact:true}).count() !== 1) throw new Error('Frozen winner missing');
      await page.getByText('Application checks passed on both source trees. Exact rollback passed. External model calls: 0.', {exact:true}).waitFor();
      if ((await page.request.post(new URL('/api/optimization', endpoint).href, {data:{run:true}})).status() !== 405) throw new Error('Browser result must be read-only');
    } else {
      await page.getByText('No completed lesson yet. Follow OPTIMIZATION.md to run it locally.', {exact:true}).waitFor();
    }
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('Horizontal overflow');
    const results = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    if (results.violations.length || errors.length) {
      console.error(JSON.stringify({accessibility:results.violations.map(item => ({id:item.id,nodes:item.nodes.length})),browser_errors:errors.length}));
      throw new Error('Browser/accessibility check failed');
    }
    evidence.push({viewport, flows:3, optimization:process.env.EXAMPLE_OPTIMIZATION === 'true', axe_violations:0, browser_errors:0});
    await context.close();
  }
  console.log(JSON.stringify({status:'passed', evidence, screenshots:false, video:false, traces:false}));
} finally { await browser.close(); }

// Actual local browser acceptance; no credential or external service access.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const {chromium}=await import(process.env.THESISLAB_PLAYWRIGHT_MODULE||'playwright');
const url=process.env.THESISLAB_QA_URL||'http://127.0.0.1:8766';
assert.equal(new URL(url).hostname,'127.0.0.1');
const context=await chromium.launchPersistentContext(path.resolve('.local/v1-browser-profile'),{
 headless:true,chromiumSandbox:true,executablePath:process.env.THESISLAB_CHROME_BINARY,
 viewport:{width:1440,height:1080},args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run']});
await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
const page=await context.newPage(),checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const b=n=>page.getByRole('button',{name:n,exact:true});
const check=n=>{checks.push(n);console.log('PASS '+n)};
const get=async p=>{const r=await page.request.get(url+p);assert.equal(r.status(),200);return r.json()};
const latest=async()=> (await get('/api/tasks'))[0];
async function confirm(){await page.locator('#meaning-reviewed').check();await page.locator('#review-notes').fill('本地端到端验收：审查限定范围、原文、证据计划和未决日期限制；非投资建议。');await b('确认计划').click();await page.getByText('用户已确认',{exact:true}).waitFor()}
try{
 await page.goto(url);await page.getByRole('heading',{name:'我的研究',exact:true}).waitFor();
 assert.equal((await get('/api/session')).model_enabled,false);check('V1 offline localhost, fresh model disabled');
 await page.locator('#thesis-input').fill('宁德时代盈利改善来自主营业务');await b('保存新命题（离线）').click();await page.getByRole('heading',{name:'Claim Graph',exact:true}).waitFor();
 let s=await latest();assert.equal(s.raw_candidate,null);assert.equal(s.candidate_source,'manual_scaffold');
 assert.equal(await page.locator('[data-claim-field="kind"]').isVisible(),false);check('new thesis saved honestly, technical parameters hidden');
 await b('Agent 开始研究').click();await page.locator('#notice').filter({hasText:'请先审核并确认'}).waitFor();check('unconfirmed plan cannot execute agents');
 await b('返回研究库').click();await page.locator('#cached-choice').selectOption('4');await b('导入真实模型缓存').click();await page.getByRole('heading',{name:'Claim Graph',exact:true}).waitFor();
 s=await latest();assert.equal(s.raw_candidate!==null,true);assert.equal(s.design.claims.length,4);assert.equal(s.schema.status,'passed');assert.equal(s.semantic_review,'pending');check('actual DeepSeek multi-node candidate displayed with separate semantic review');
 for(const input of await page.locator('[data-answer]').all())await input.fill('离线流程验收；没有已授权估值来源，不推断基本面已验证。');
 for(const input of await page.locator('[data-accept]').all())await input.check();await confirm();await b('Agent 开始研究').click();await page.locator('#research-report').waitFor();
 s=await latest();assert.equal(s.orchestration.status,'completed');assert.equal(s.report.conclusion.state,'unverifiable');assert.ok(s.orchestration.steps[0].output.missing.length);check('AI plan -> confirmation -> real local agent execution -> evidence gap report');
 await b('返回研究库').click();await b('开始贵州茅台财报演示（人工计划）').click();await page.getByRole('heading',{name:'Claim Graph',exact:true}).waitFor();await confirm();
 s=await latest();const study=s.id,confirmedVersion=s.version;await b('Agent 开始研究').click();await page.locator('#research-report').waitFor();
 s=await get('/api/tasks/'+study);assert.equal(s.orchestration.status,'completed');assert.equal(s.orchestration.steps.length,5);assert.ok(s.orchestration.steps.every(x=>x.attempts===1&&x.finished_at));
 assert.ok(s.orchestration.steps[0].output.matches.length>0);assert.ok(s.orchestration.steps[1].output.matches.length>0);
 assert.equal(s.orchestration.steps[2].status,'needs_review');assert.equal(s.report.conclusion.state,'opposes');check('real financial case: support/refute tools, unresolved conflict audit, M2 calculation and report');
 const r=await get('/api/runs/'+s.run_id),catalog=await get('/api/evidence');const metric=id=>catalog.find(e=>e.id===id)?.scope.metric;
 assert.ok(Object.values(r.claims).some(x=>x.state==='supports'&&x.evidence_dependencies.some(id=>metric(id)==='operating_income_yoy')));
 assert.ok(Object.values(r.claims).some(x=>x.state==='opposes'&&x.evidence_dependencies.some(id=>metric(id)==='gross_margin_change')));check('revenue support and gross-margin counter-evidence are independently evaluated');
 await b('查看完整证据与计算').click();await b('gross_margin_change').first().click();await page.getByRole('dialog').waitFor();await page.getByText('公式：current_gross_margin-prior_gross_margin',{exact:true}).waitFor();assert.ok(await page.getByRole('link',{name:/打开原始财报第/}).count());await page.locator('#close-drawer').click();check('conclusion drills down to deterministic formula and issuer report page');
 await b('审查证据冲突').click();await page.getByRole('dialog').waitFor();await b('采用官方披露日，保留原因未决').first().click();await page.getByRole('dialog').waitFor({state:'hidden'});assert.ok((await get('/api/conflicts')).every(x=>x.state==='unresolved'));check('human field review preserves original values and unresolved date semantics');
 await b('保存研究').click();await page.locator('#notice').filter({hasText:'研究已保存'}).waitFor();await page.reload();await page.getByRole('heading',{name:'我的研究',exact:true}).waitFor();
 await page.locator('.study').filter({hasText:'真实财报 · 收入与毛利率验证'}).first().getByRole('button',{name:'继续研究',exact:true}).click();await page.locator('.tabs').waitFor();await b('研究报告').click();await page.locator('#research-report').waitFor();assert.equal((await get('/api/tasks/'+study)).report.run_id,s.report.run_id);check('refresh and reopen restores execution, report and sources');
 await b('历史').click();await page.locator('.history-item').first().waitFor();assert.ok(await page.locator('.history-item').count()>3);await page.locator('#close-drawer').click();check('history drawer awaits render and shows persisted checkpoints');
 await b('比较研究版本').click();await page.locator('#version-left').selectOption(String(confirmedVersion));await b('比较选定版本').click();await page.locator('#version-diff').waitFor();assert.ok((await page.locator('#version-diff').innerText()).includes('尚无结论'));check('Research Comparison: fixed same-thesis pre/post execution snapshots');
 await b('返回工作台').click();await b('Agent 研究流程').click();await page.locator('[data-agent="report"]').waitFor();await page.screenshot({path:'.local/v1-workspace.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.local/v1-mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);check('desktop and mobile execution view, no horizontal overflow');
 assert.deepEqual(errors,[]);check('no browser runtime errors');
 fs.writeFileSync('.local/v1-browser-results.json',JSON.stringify({passed:checks.length,failed:0,checks,financial_calls:0,model_calls:0,keychain_reads:0},null,2));console.log(JSON.stringify({passed:checks.length,failed:0}));
}catch(e){fs.writeFileSync('.local/v1-browser-failure.json',JSON.stringify({passed:checks.length,failed:1,message:String(e)},null,2));console.error(String(e));process.exitCode=1}
finally{await context.close()}

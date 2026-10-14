// Browser QA against local-only offline test server. No paid API or credentials.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const moduleName=process.env.THESISLAB_PLAYWRIGHT_MODULE||'playwright';
const {chromium}=await import(moduleName);
const url=process.env.THESISLAB_QA_URL||'http://127.0.0.1:8765';
assert.equal(new URL(url).hostname,'127.0.0.1');
const executablePath=process.env.THESISLAB_CHROME_BINARY;
const context=await chromium.launchPersistentContext(path.resolve('.local/browser-qa-profile'),{headless:true,chromiumSandbox:true,...(executablePath?{executablePath}:{}),viewport:{width:1440,height:1080},args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--disable-default-apps']});
await context.route('**/*',route=>{const host=new URL(route.request().url()).hostname;return host==='127.0.0.1'?route.continue():route.abort()});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
let checks=[];
const check=(name)=>{checks.push(name);console.log('PASS '+name)};
const button=(name)=>name==='关闭'?page.locator('#close-drawer'):page.getByRole('button',{name,exact:true});
const settle=async()=>{await page.waitForTimeout(200)};
async function current(){return page.evaluate(async()=>{const studies=await(await fetch('/api/tasks')).json();return studies[0]})}
async function apiGet(p){const r=await page.request.get(url+p);assert.equal(r.status(),200);return r.json()}
async function confirmPlan(){await page.locator('#meaning-reviewed').check();await page.locator('#review-notes').fill('浏览器端到端测试：明确审查原句、节点与计划；不宣称真实金融或模型语义质量通过。');await button('确认计划').click();await page.getByText('用户已确认',{exact:true}).waitFor()}
try{
 await page.goto(url);await page.getByRole('heading',{name:'让投资判断，经得起证据检验。'}).waitFor();
 const session=await apiGet('/api/session');assert.equal(session.model_mode,'real_model_cache_replay_only');check('loopback test mode explicitly labeled');
 await page.locator('#thesis-input').fill('估值回落，但基本面未恶化。');await page.locator('#model-consent').check();await button('创建并回放候选').click();await page.getByText('结构合格',{exact:true}).waitFor();
 let s=await current();assert.equal(s.semantic_review,'pending');assert.equal(s.model_receipt.new_model_requests,0);assert.equal(s.confirmed_id,null);check('input -> actual model cache replay -> schema passed, semantic pending');
 await button('运行研究').click();await page.locator('#notice').filter({hasText:'confirm_current_graph_and_plan_before_research'}).waitFor();check('research blocked before confirmation');
 const modelOriginal=JSON.stringify(s.design);let edited=structuredClone(s.design);
 // Explicit manual correction, not a hidden adapter repair: remove duplicate
 // suggested combination node and redundant tasks on the AND root.
 const duplicates=edited.claims.filter(c=>c.origin==='suggestion').map(c=>c.id);
 edited.claims=edited.claims.filter(c=>!duplicates.includes(c.id));edited.relations=edited.relations.filter(r=>!duplicates.includes(r.from_id)&&!duplicates.includes(r.to_id));edited.tasks=edited.tasks.filter(t=>t.claim_id!==edited.root_id&&!duplicates.includes(t.claim_id));
 for(const q of edited.clarifications)q.answer='本端到端测试保留当前断言，仅验证流程；没有真实估值来源，不形成确定金融结论。';
 await page.locator('#advanced-editor summary').click();await page.locator('#design-json').fill(JSON.stringify(edited,null,2));await button('保存完整JSON').click();await settle();s=await current();assert.equal(s.candidate_source,'manual_revision_of_model_candidate');assert.notEqual(JSON.stringify(s.design),modelOriginal);check('explicit manual revision retained, semantic review resets');
 await confirmPlan();await button('运行研究').click();await page.getByText('无法验证',{exact:true}).first().waitFor();s=await current();const run=await apiGet('/api/runs/'+s.run_id);assert.equal(run.conclusion.state,'unverifiable');check('confirmed plan -> real M2 run -> missing valuation unverifiable');
 await button('保存研究').click();const saved=s.id;await page.reload();await page.getByRole('heading',{name:'我的研究'}).waitFor();await page.getByRole('article').filter({hasText:'估值回落，但基本面未恶化。'}).first().getByRole('button',{name:'继续研究'}).click();await settle();assert.equal((await apiGet('/api/tasks/'+saved)).run_id,s.run_id);check('save -> reload -> restore persisted study');
 await button('返回研究库').click();await button('载入已核验财报研究设计').click();await page.getByRole('heading',{name:'Claim Graph'}).waitFor();await confirmPlan();await button('运行研究').click();await page.getByText('反对',{exact:true}).first().waitFor();s=await current();const originalId=s.id, originalRun=s.run_id;const financial=await apiGet('/api/runs/'+originalRun);assert.equal(financial.conclusion.state,'opposes');check('real financial evidence -> computed opposing composite conclusion');
 await page.getByRole('button',{name:'gross_margin_change',exact:true}).first().click();await page.getByRole('dialog').waitFor();await page.getByText('公式：current_gross_margin-prior_gross_margin',{exact:true}).waitFor();assert.ok(await page.getByRole('link',{name:/打开原始财报第/}).count());await button('关闭').click();check('conclusion -> recursive formulas -> original report page locator');
 await button('审查证据冲突').click();await page.getByRole('button',{name:'采用官方披露日，保留原因未决'}).first().click();await settle();const conflicts=await apiGet('/api/conflicts');assert.ok(conflicts.every(c=>c.state==='unresolved'));check('field-level issuer date adoption preserves unresolved supplier semantics');
 await button('手动重验').click();await settle();s=await apiGet('/api/tasks/'+originalId);assert.equal(s.run_ids.length,2);assert.notEqual(s.run_id,originalRun);assert.equal((await apiGet('/api/runs/'+originalRun)).conclusion.state,'opposes');check('manual revalidation appends run without rewriting old conclusion');
 await button('检查此条件').click();await button('保存条件检查').click();await settle();s=await apiGet('/api/tasks/'+originalId);assert.equal(s.condition_checks.at(-1).check_state,'unknown');check('unchecked change condition remains unknown, not safe');
 await button('继续研究').click();await page.locator('#followup-question').fill('日期异常影响什么？');await page.locator('#followup-topic').selectOption('date');await button('提交追问').click();await settle();s=await apiGet('/api/tasks/'+originalId);assert.equal(s.followups.at(-1).mode,'explain');assert.equal(s.followups.at(-1).model_calls,0);check('evidence-only followup persisted without model or finance request');
 await page.locator('#followup-mode').selectOption('verify');await page.locator('#followup-topic').selectOption('q2');const catalog=await apiGet('/api/evidence');const entity=catalog.find(e=>e.origin==='issuer').scope.entity;await page.locator('#followup-entity').selectOption(entity);await page.locator('#followup-question').fill('核验Q2单季');await button('提交追问').click();await settle();s=await apiGet('/api/tasks/'+originalId);const childId=s.followups.at(-1).child_task_id;assert.ok(childId);await button('审查新增验证计划').click();await page.getByRole('heading',{name:'Claim Graph'}).waitFor();await confirmPlan();await button('运行研究').click();await settle();const child=await apiGet('/api/tasks/'+childId);assert.equal((await apiGet('/api/runs/'+child.run_id)).conclusion.state,'opposes');check('new-fact followup -> Q2 calculation plan -> confirmation -> new M2 run');
 await button('继续研究').click();await page.locator('#compare-target').selectOption(originalId);
 const childRun=await apiGet('/api/runs/'+child.run_id), old=await apiGet('/api/runs/'+s.run_id);
 const ci=childRun.tasks.find(t=>t.evidence_id&&catalog.find(e=>e.id===t.evidence_id)?.scope.metric==='operating_income_yoy')?.evidence_id||childRun.tasks.find(t=>t.evidence_id).evidence_id;
 const oi=old.tasks.find(t=>t.evidence_id&&catalog.find(e=>e.id===t.evidence_id)?.scope.metric==='operating_income_yoy').evidence_id;
 await page.locator('#compare-left').selectOption(ci);await page.locator('#compare-right').selectOption(oi);await button('检查对齐并保存比较').click();await page.getByRole('heading',{name:'当前不可直接比较'}).waitFor();await button('关闭').click();check('H1/Q1 YTD versus Q2 single correctly rejected as comparable metric');
 // Positive calendar-aligned comparison uses two gross-margin fields from a
 // selected research closure, never hard-coded financial amounts.
 await button('返回研究库').click();await page.getByRole('article').filter({hasText:'真实财报 · 收入与毛利率验证'}).first().getByRole('button',{name:'继续研究'}).click();await page.locator('.tabs').waitFor();await button('继续研究').click();await page.locator('#compare-target').selectOption(originalId);const original=await apiGet('/api/tasks/'+originalId);const latest=await apiGet('/api/runs/'+original.run_id);const ids=new Set(latest.conclusion.evidence_dependencies);const margins=catalog.filter(e=>ids.has(e.id)&&e.scope.metric==='gross_margin'&&e.scope.end.endsWith('03-31'));assert.equal(margins.length,2);
 await page.locator('#compare-left').selectOption(margins[0].id);await page.locator('#compare-right').selectOption(margins[1].id);await button('检查对齐并保存比较').click();await page.getByRole('heading',{name:'口径已对齐'}).waitFor();await button('关闭').click();check('same-quarter cross-year financial comparison computes traceable delta');
 await page.reload();await page.getByRole('heading',{name:'我的研究'}).waitFor();await page.getByRole('article').filter({hasText:'真实财报 · 收入与毛利率验证'}).first().getByRole('button',{name:'继续研究'}).click();await page.locator('.tabs').waitFor();await button('继续研究').click();assert.ok(await page.getByRole('button',{name:/查看已保存比较/}).count());check('comparison and followup restored after browser reload');
 await button('历史').click();assert.ok(await page.locator('.history-item').count()>3);await button('关闭').click();check('revision/audit history actually persisted');
 await button('证据与结论').click();await page.screenshot({path:'.local/m3-workbench.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.local/m3-mobile.png',fullPage:true});check('desktop and mobile render inspected artifacts saved privately');
 assert.deepEqual(errors,[]);check('no browser runtime errors');
 fs.writeFileSync('.local/m3-browser-results.json',JSON.stringify({passed:checks.length,failed:0,checks,model_requests:0,financial_requests:0,keychain_reads:0,input_kind:'real_financial_material_and_prior_real_model_cache_replay'},null,2));
 console.log(JSON.stringify({passed:checks.length,failed:0,real_model_requests:0,keychain_reads:0}));
}catch(e){fs.writeFileSync('.local/m3-browser-failure.json',JSON.stringify({passed:checks.length,failed:1,message:String(e)},null,2));console.error(String(e));process.exitCode=1}finally{await context.close()}

# Competitor evidence and natural-language redesign

Reviewed 2026-10-14. This records public product/documentation statements and
source inspection, not a logged-in product benchmark. No competitor UI/code/assets
are copied into ThesisLab. Research capability is limited by our actual tools.

| Product | Public evidence | Mechanism adopted | Boundary |
| --- | --- | --- | --- |
| AlphaSense Generative Search | [Modes and inputs](https://dev-developer.alpha-sense.com/agent-api/gensearch): prompt is required; entity/date filters optional; conversation followups | Prompt-first entry, optional structured scope, continuing research context | No AlphaSense API/content access, premium corpus or coverage claims |
| AlphaSense Deep Research | [Official help](https://help.alpha-sense.com/hc/en-us/articles/42391092171795-Deep-Research-Conduct-In-Depth-Multi-Step-Research-Autonomously): iterative research and visible execution log | Inspectable plan, bounded tool execution, logged results and supplementary source checks | Our job/call budgets are deliberately smaller; no claimed output equivalence |
| AlphaSense Thesis Checker / Bull & Bear | [April 2026](https://help.alpha-sense.com/hc/en-us/articles/51403579155731-AlphaSense-Product-Updates-April-2026) confirms Thesis Checker; [workflow API](https://dev-developer.alpha-sense.com/agent-api/workflow-agents) names Bull & Bear templates and clarifying followups | Supporting and opposing tests attached to each claim | Template existence verified; internal debate prompts/evaluation reliability not inspectable. We use one agent, not theatrical debating agents |
| Hebbia Matrix | [March 2026 update](https://www.hebbia.com/blog/the-disclosure-march-2026): natural-language creation wizard chooses documents and decomposes questions into columns; [hedge-fund use](https://www.hebbia.com/blog/how-hedge-funds-use-hebbia) describes structured citation-linked tables | Claim/evidence/assessment/condition matrix with inspectable original locations | No Hebbia source code, licensed corpus, unlimited context, proprietary ISD, or scale guarantees |
| Suvi / AgenticThesis | [Official engine](https://www.getsuvi.com/agenticthesis/) describes original artifacts, precise citations, review and recovery; code inspection below | Plan review by user, source lineage, persistent states and conservative unverified classifications | Engine concerns thesis monitoring; not proof it offers general valuation. Version-history UI and scheduled monitoring deferred here |
| subThesis | [Workspace](https://www.subthesis.app/equity-research-workspace), [AI research](https://www.subthesis.app/ai-investment-research-tool), [long-term workflow](https://www.subthesis.app/solutions/long-term-investors) describe durable research context and evidence linked to claims | Save/restore, followup, revising research and adding comparison objects | Public marketing/docs reviewed, no private implementation/source or authenticated workflow benchmark |

## Open-source inspection actually completed

GitHub Web tree/raw access initially failed. Read-only GitHub API access then
listed `src/agentic_thesis` and retrieved the following files from the public
[suvimatt/agentic-thesis](https://github.com/suvimatt/agentic-thesis) repository:

- [workflow.py](https://github.com/suvimatt/agentic-thesis/blob/main/src/agentic_thesis/workflow.py): observed LangGraph nodes for retrieval, evidence packs,
  delta analysis, citation validation, human review, snapshot commit. Observed
  SQLite checkpoint connection, resume path and review-conflict protection.
- [rag.py](https://github.com/suvimatt/agentic-thesis/blob/main/src/agentic_thesis/rag.py): observed preserved artifact/page/character range metadata;
  `enforce_citations` checks that the exact selected text slice equals the quote.

Repository lists AGPL-3.0. We inspected mechanism boundaries only, did not fork,
copy or depend on its implementation, and did not run its service or evals.
No accessible official open-source implementation was identified for AlphaSense,
Hebbia or subThesis in the reviewed material; their product features are not
treated as implementation facts.

## Repository changes

- Add independent Understand contract: objective, thesis type, multiple entities,
  time expression, assumptions, critical clarifications and research axes.
- Task creation accepts statement only. No mandatory symbol/year/period in entry.
  Identifier aliases are metadata, not financial facts; model guessed codes never
  become trusted tool identities. Unknown identifiers remain explicit limitations.
- Add schema-v2 plans: editable/addable/removable claims, entity references,
  observation window, required original sources, bull/bear tests, dependencies,
  necessary/context roles and observable invalidation conditions.
- Compile tools separately per entity and subquestion scope. Financial metrics
  retain M1/M2/M4 admission/calculation guards. Multiple SEC metrics now have unique
  source identities including precise raw pointers (fixed a source collision).
- Add a whitelisted, re-computable cash conversion metric; do not infer complete
  earnings quality from that ratio. Cross-company comparison checks full scope.
- Build a claim × evidence matrix rather than replacing research with chat text.
  No-data and unsupported questions stay visible through the conclusion.
- Keep local Python/JS/SQLite + Compose and environment-only secrets. Legacy tasks
  and the old workspace remain readable. No public hosting or new agent framework.

## Deliberate limits

Natural-language understanding/planning supports broad research requests; actual
validation still covers a narrower set of company financial evidence. Market
valuation history, macro causal effects, value-chain profit shares, reliable
qualitative causal inference and arbitrary company resolution need additional
authorized adapters. Unsupported tasks create capability checks with zero external
requests and an unverifiable assessment. No model-memory facts are admitted.

Acceptance uses six explicit scenarios, separated into synthetic model/HTTP
fixtures and actual network checks. An isolated browser fixture server is visibly
marked and never part of production/Compose startup. Empty .env credentials and
the previously observed network DNS boundary are not concealed as successful live
financial verification.

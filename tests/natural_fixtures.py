"""Six explicit synthetic acceptance scenarios. Never imported by production code."""
from copy import deepcopy
import json
from urllib.parse import urlsplit

CASES=[
 ('profitability','微软2025年净利润同比增长。'),
 ('valuation','微软估值回落，但2025年基本面没有恶化。'),
 ('comparison','比较微软与苹果2025年的盈利质量，微软的经营现金流与净利润比更高。'),
 ('supply_chain','2025年新能源汽车产业链利润向电池企业转移。'),
 ('macro','美联储降息将提升银行盈利。'),
 ('exploratory','龙头盈利改善是否可持续？'),
]

def entity(id,name,kind='company'):return {'id':id,'name':name,'kind':kind}

def understanding(type,statement,answers=None):
    entities={'profitability':[entity('msft','微软')],'valuation':[entity('msft','微软')],
              'comparison':[entity('msft','微软'),entity('aapl','苹果')],
              'supply_chain':[entity('ev','新能源汽车产业链','industry'),entity('battery','电池企业','industry')],
              'macro':[entity('fed','美联储降息','macro_event'),entity('banks','银行业','industry')],
              'exploratory':[entity('leader','龙头','unknown')]}[type]
    clarifications=[]
    if type=='exploratory':
        if answers and answers.get('subject'):entities=[entity('msft','微软')]
        else:clarifications=[{'id':'subject','question':'你说的龙头是哪个公司或行业？','required':True}]
    return {'objective':statement,'thesis_type':type,'entities':entities,
        'time_range':{'label':'2025年度；预测持续性另列为未验证','year':2025,'period':'annual'},
        'assumptions':['年度范围仅用于可查询财务事实，不代表宏观或预测已验证。'],
        'clarifications':clarifications,'research_axes':['支持与反证','口径与竞争解释']}

def question(id,statement,entities,*,kind='numeric',metric='net_profit_yoy',tool='sec_facts',role='necessary'):
    return {'id':id,'statement':statement,'research_question':statement,'kind':kind,'entity_ids':entities,
        'time_range':'2025年度','year':2025,'period':'annual','metric':metric,'operator':'gt',
        'threshold':'0' if kind=='numeric' else None,'tool':tool,'role':role,'depends_on':[],
        'source_requirement':'原始披露中的同口径指标与完整观察区间。',
        'support_test':'取得符合该主张的可定位同口径证据。',
        'counter_test':'取得与该主张相反的同口径证据或竞争解释。',
        'condition':'下一份同口径披露否定当前必要判断，或出现更可靠的相反证据。'}

def plan(type,statement,answers=None):
    if type=='profitability':qs=[question('profit','2025年微软净利润同比大于零',['msft'])]
    elif type=='valuation':qs=[question('valuation','估值确实回落且基本面未恶化',['msft'],kind='qualitative',metric='valuation_history',tool='unavailable'),
        question('profit','净利润同比大于零',['msft'],role='context')]
    elif type=='comparison':qs=[question('cash','微软现金流/净利润比高于苹果',['msft','aapl'],kind='comparison',metric='cash_conversion'),
        question('quality','利润质量未因非经常损益或会计口径变化被高估',['msft','aapl'],kind='qualitative',metric='earnings_quality',tool='unavailable')]
    elif type=='supply_chain':qs=[question('distribution','产业链利润份额向电池企业转移',['ev','battery'],kind='qualitative',metric='profit_share',tool='unavailable')]
    elif type=='macro':qs=[question('impact','降息对银行净息差和信用成本的因果影响',['fed','banks'],kind='qualitative',metric='macro_impact',tool='unavailable')]
    else:qs=[question('sustainability','微软未来盈利改善能够持续',['msft'],kind='qualitative',metric='forecast',tool='unavailable'),
        question('profit','2025年净利润同比大于零',['msft'],role='context')]
    return {'scope':statement+'；按子问题分别核验，不能用背景事实填补缺口。','questions':qs}

class NaturalFixtureModel:
    def __init__(self):self.requests=[]
    def json(self,system,payload):
        self.requests.append(payload)
        if 'needs_new_research' in system:
            return {'answer':'【合成验收模型推断】已取得指标不足以证明整体估值/因果判断，应补充计划中的原始资料。',
                'evidence_ids':payload['allowed_evidence_ids'][:1],'needs_new_research':True}
        statement=payload.get('statement','');type=next((t for t,s in CASES if s in statement),'profitability')
        added_comparison='新增比较对象：苹果' in statement and '微软' in statement
        if added_comparison:type='comparison'
        if '研究助手的 Understand' in system:return understanding(type,statement,payload.get('answers'))
        if '你是 Plan 节点' in system:
            if added_comparison:
                return {'scope':statement,'questions':[question('compare_profit','微软净利润同比高于苹果',['msft','aapl'],kind='comparison',metric='net_profit_yoy')]}
            return plan(type,statement,payload.get('answers'))
        if 'document_urls' in system:return {'reason':'合成夹具无新增原始资料','document_urls':[]}
        return {'reason':'合成测试无新增来源','additional_queries':[]}

class NaturalFixtureHTTP:
    def __init__(self):self.requests=[];self.error=None;self.conflict=False
    def request(self,url,**kwargs):
        self.requests.append(url)
        if self.error:
            from thesislab.domain import ContractError
            raise ContractError(self.error)
        cik=urlsplit(url).path.rsplit('/',1)[-1].removeprefix('CIK').removesuffix('.json')
        if not cik.isdigit():raise AssertionError('Fixture only supports SEC CompanyFacts')
        current=120 if int(cik)==789019 else 100;cash=180 if int(cik)==789019 else 100
        def rows(a,b):
            result=[{'start':'2025-01-01','end':'2025-12-31','filed':'2026-02-01','form':'10-K',
                'accn':cik+'-26-000001','val':a},
                {'start':'2024-01-01','end':'2024-12-31','filed':'2025-02-01','form':'10-K',
                'accn':cik+'-25-000001','val':b}]
            if self.conflict:result.append({**result[0],'val':a+10,'accn':cik+'-26-000002','filed':'2026-03-01'})
            return result
        raw={'cik':int(cik),'entityName':'SYNTHETIC FIXTURE — NOT LIVE DATA','facts':{'us-gaap':{
            'NetIncomeLoss':{'units':{'USD':rows(current,80)}},
            'NetCashProvidedByUsedInOperatingActivities':{'units':{'USD':rows(cash,90)}},
            'RevenueFromContractWithCustomerExcludingAssessedTax':{'units':{'USD':rows(300,200)}}}}}
        return json.dumps(raw).encode()

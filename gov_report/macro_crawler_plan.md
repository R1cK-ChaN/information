# 宏观分析 Agent 数据采集方案
## 金十财经日历 + 官方机构新闻稿全文爬取

---

## 一、整体架构

```
┌─────────────────────────────────────────┐
│         金十财经日历 API（触发器）           │
│  每日拉取未来7天日历 → 写入发布任务队列       │
└──────────────────┬──────────────────────┘
                   │ 到点触发
                   ▼
┌─────────────────────────────────────────┐
│           官方机构爬虫（执行层）             │
│  根据事件类型 → 路由到对应 fetcher          │
│  抓取 HTML/PDF 正文 → 清洗为纯文本          │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│              数据库（存储层）               │
│  结构化数据 → PostgreSQL（指标数值）         │
│  文本数据   → 向量数据库（RAG检索）          │
└─────────────────────────────────────────┘
```

---

## 二、金十财经日历 API

### 接口信息

```
Base URL:  https://open-data-api.jin10.com/data-api/
Auth:      headers: { 'secret-key': YOUR_KEY }
```

### 日历接口调用示例

```python
import requests
from datetime import datetime, timedelta

def get_calendar(region: str = 'us', days_ahead: int = 7):
    """
    region: 'us'(美国) | 'cn'(中国) | 'eu'(欧元区) | 'all'
    返回字段: event_id, event_name, country, publish_time,
              importance(1-3星), previous, forecast, actual
    """
    headers = {'secret-key': 'YOUR_SECRET_KEY'}
    params = {
        'type': 'calendar',
        'calendar_type': region,
        'calendar_datatype': 'data',
        'start': datetime.now().strftime('%Y-%m-%d'),
        'end': (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'),
    }
    resp = requests.get(
        'https://open-data-api.jin10.com/data-api/calendar',
        headers=headers,
        params=params
    )
    return resp.json()
```

### 事件名称到爬虫的路由映射表

金十日历返回的 `event_name` 是中文，需要映射到对应的官方来源：

```python
EVENT_ROUTER = {
    # === 美国 ===
    '美国CPI':                'us_bls_cpi',
    '美国核心CPI':             'us_bls_cpi',
    '美国PPI':                'us_bls_ppi',
    '美国非农就业':             'us_bls_nfp',
    '美国失业率':              'us_bls_nfp',
    '美国GDP':                'us_bea_gdp',
    '美国核心PCE':             'us_bea_pce',
    '美国FOMC利率决议':         'us_fed_fomc_statement',
    '美联储会议纪要':            'us_fed_fomc_minutes',
    '美国ISM制造业PMI':         'us_ism_manufacturing',
    '美国ISM非制造业PMI':       'us_ism_services',
    '密歇根大学消费者信心指数':   'us_umich_sentiment',
    '美国零售销售':             'us_census_retail',
    '美国工业产出':             'us_fed_ip',
    '美国新屋开工':             'us_census_housing',
    '美国贸易帐':              'us_bea_trade',
    '美联储褐皮书':             'us_fed_beigebook',
    # === 中国 ===
    'CPI年率':               'cn_stats_cpi',
    'CPI月率':               'cn_stats_cpi',
    'PPI年率':               'cn_stats_ppi',
    'GDP':                  'cn_stats_gdp',
    '工业增加值':              'cn_stats_industrial',
    '社会消费品零售总额':        'cn_stats_retail',
    '固定资产投资':             'cn_stats_fai',
    '制造业PMI':              'cn_stats_pmi',
    '非制造业PMI':             'cn_stats_pmi',
    '财新制造业PMI':           'cn_caixin_pmi',
    '财新服务业PMI':           'cn_caixin_pmi',
    'M2货币供应':              'cn_pboc_monetary',
    '社会融资规模':             'cn_pboc_monetary',
    '新增人民币贷款':           'cn_pboc_monetary',
    'LPR利率':               'cn_pboc_lpr',
    '贸易帐':                 'cn_customs_trade',
    '外汇储备':               'cn_safe_fx',
}
```

---

## 三、美国官方机构爬虫

### 3.1 美国劳工统计局 BLS（bls.gov）

**覆盖数据：CPI、PPI、非农就业、失业率**

BLS每份报告发布时会覆盖更新同一个固定URL，也有按日期归档的URL。

```python
BLS_ENDPOINTS = {
    'us_bls_cpi': {
        'latest_url':   'https://www.bls.gov/news.release/cpi.nr0.htm',
        'archive_base': 'https://www.bls.gov/news.release/archives/cpi_{MMDDYYYY}.htm',
        'description':  'CPI新闻稿，含分项解读和BLS统计员说明',
        'content_type': 'html',
    },
    'us_bls_ppi': {
        'latest_url':   'https://www.bls.gov/news.release/ppi.nr0.htm',
        'archive_base': 'https://www.bls.gov/news.release/archives/ppi_{MMDDYYYY}.htm',
        'description':  'PPI新闻稿',
        'content_type': 'html',
    },
    'us_bls_nfp': {
        'latest_url':   'https://www.bls.gov/news.release/empsit.nr0.htm',
        'archive_base': 'https://www.bls.gov/news.release/archives/empsit_{MMDDYYYY}.htm',
        'description':  '就业形势新闻稿（含非农、失业率、时薪详细分析）',
        'content_type': 'html',
    },
}

# BLS HTML提取逻辑
from bs4 import BeautifulSoup
import requests

def fetch_bls_report(url: str) -> dict:
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # BLS新闻稿主内容在 <div id="release-calendar-next"> 和 <div class="release-content">
    content_div = soup.find('div', {'id': 'release-content'}) \
                  or soup.find('div', {'class': 'news-release-intro'})
    
    # 提取发布日期
    date_tag = soup.find('span', {'class': 'date'}) or soup.find('meta', {'name': 'dc.date'})
    
    return {
        'source': 'BLS',
        'url': url,
        'publish_date': date_tag.get('content', '') if date_tag else '',
        'full_text': content_div.get_text(separator='\n', strip=True) if content_div else '',
        'html': str(content_div) if content_div else '',
    }
```

### 3.2 美联储 Federal Reserve（federalreserve.gov）

**覆盖数据：FOMC声明、会议纪要、主席讲话、褐皮书、工业产出**

美联储官网URL结构极其规律，是所有官方来源里最好爬的。

```python
FED_ENDPOINTS = {
    'us_fed_fomc_statement': {
        # FOMC声明URL规律: /newsevents/pressreleases/monetary{YYYYMMDD}a.htm
        'url_pattern':   'https://www.federalreserve.gov/newsevents/pressreleases/monetary{date}a.htm',
        'listing_url':   'https://www.federalreserve.gov/monetarypolicy/fomc_historical_year.htm',
        'description':   'FOMC利率决议声明全文，含政策立场原文',
        'content_type':  'html',
    },
    'us_fed_fomc_minutes': {
        # 会议纪要URL规律: /monetarypolicy/fomcminutes{YYYYMMDD}.htm
        'url_pattern':   'https://www.federalreserve.gov/monetarypolicy/fomcminutes{date}.htm',
        'listing_url':   'https://www.federalreserve.gov/monetarypolicy/fomc_historical_year.htm',
        'description':   'FOMC会议纪要全文（约3周后发布，含委员详细讨论）',
        'content_type':  'html',
    },
    'us_fed_beigebook': {
        # 褐皮书（经济形势调查）: 每年8次
        'listing_url':   'https://www.federalreserve.gov/monetarypolicy/beige-book-default.htm',
        'description':   '美联储褐皮书，12个地区联储的经济状况定性描述',
        'content_type':  'html',
    },
    'us_fed_ip': {
        'latest_url':    'https://www.federalreserve.gov/releases/g17/current/default.htm',
        'description':   '工业产出与产能利用率',
        'content_type':  'html',
    },
}

def fetch_fed_report(url: str) -> dict:
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 美联储页面主内容在 <div id="content"> 或 <article>
    content = soup.find('div', {'id': 'content'}) or soup.find('article')
    
    # 去掉导航、页脚等噪音
    for tag in content.find_all(['nav', 'footer', 'aside', 'script', 'style']):
        tag.decompose()
    
    return {
        'source': 'Federal Reserve',
        'url': url,
        'full_text': content.get_text(separator='\n', strip=True),
    }
```

### 3.3 美国经济分析局 BEA（bea.gov）

**覆盖数据：GDP、PCE（核心通胀）、贸易账**

```python
BEA_ENDPOINTS = {
    'us_bea_gdp': {
        'latest_url':   'https://www.bea.gov/news/current-releases',  # 列表页
        # GDP新闻稿URL示例: https://www.bea.gov/news/2024/gross-domestic-product-fourth-quarter-2023-advance-estimate
        'rss_feed':     'https://www.bea.gov/rss/releases.xml',       # ✅ BEA提供RSS，可直接订阅
        'description':  'GDP季度报告，含各分项贡献度分析',
        'content_type': 'html',
    },
    'us_bea_pce': {
        'rss_feed':     'https://www.bea.gov/rss/releases.xml',
        'description':  '个人消费支出PCE（美联储首选通胀指标）',
        'content_type': 'html',
    },
    'us_bea_trade': {
        'rss_feed':     'https://www.bea.gov/rss/releases.xml',
        'description':  '国际贸易账',
        'content_type': 'html',
    },
}
# 注意: BEA有官方RSS，是最省力的获取方式
```

### 3.4 ISM 供应管理协会（ismworld.org）

**覆盖数据：ISM制造业PMI、非制造业PMI（含分项+评述）**

```python
ISM_ENDPOINTS = {
    'us_ism_manufacturing': {
        'listing_url':  'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/pmi/',
        'description':  'ISM制造业PMI全报告，含各分项（新订单、就业、价格等）及受访企业评述',
        'note':         'ISM报告包含大量定性评论，是纯数字API无法替代的内容',
        'content_type': 'html',
    },
    'us_ism_services': {
        'listing_url':  'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/services/',
        'description':  'ISM非制造业PMI全报告',
        'content_type': 'html',
    },
}
```

### 3.5 密歇根大学消费者调查（surveys.isr.umich.edu）

```python
UMICH_ENDPOINTS = {
    'us_umich_sentiment': {
        'latest_url':   'https://data.sca.isr.umich.edu/data-archive/mine.php',
        'press_page':   'https://research.sca.isr.umich.edu/',
        'description':  '消费者信心调查，包含通胀预期原文，是美联储重点关注指标',
        'content_type': 'html',
    },
}
```

---

## 四、中国官方机构爬虫

### 4.1 国家统计局（stats.gov.cn）

**覆盖数据：CPI、PPI、GDP、工业增加值、零售、固定资产投资、PMI**

国家统计局是最重要的中国数据来源，每次发布都有新闻稿和发言人点评。

```python
NBS_ENDPOINTS = {
    'cn_stats_cpi': {
        'listing_url':  'https://www.stats.gov.cn/sj/zxfb/',  # 最新发布列表
        # 具体报告URL示例: https://www.stats.gov.cn/sj/zxfb/202401/t20240115_1946701.html
        'rss_feed':     'https://www.stats.gov.cn/rss.xml',   # ✅ 统计局有RSS
        'keywords':     ['居民消费价格', 'CPI'],
        'description':  'CPI新闻稿，含统计局新闻发言人解读',
        'content_type': 'html',
    },
    'cn_stats_pmi': {
        'listing_url':  'https://www.stats.gov.cn/sj/zxfb/',
        'keywords':     ['采购经理指数', 'PMI'],
        'description':  'PMI新闻稿，含分类指数和统计局解读',
        'content_type': 'html',
    },
    'cn_stats_gdp': {
        'listing_url':  'https://www.stats.gov.cn/sj/zxfb/',
        'keywords':     ['国内生产总值', 'GDP', '国民经济'],
        'description':  'GDP季度数据，附发布会问答摘要',
        'content_type': 'html',
    },
}

def fetch_nbs_report(url: str) -> dict:
    resp = requests.get(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://www.stats.gov.cn/'
    })
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 统计局文章主体在 <div class="TRS_Editor"> 或 <div id="zoom">
    content = soup.find('div', {'class': 'TRS_Editor'}) \
              or soup.find('div', {'id': 'zoom'})
    
    title = soup.find('h1') or soup.find('title')
    
    return {
        'source': '国家统计局',
        'url': url,
        'title': title.get_text(strip=True) if title else '',
        'full_text': content.get_text(separator='\n', strip=True) if content else '',
    }
```

### 4.2 中国人民银行（pbc.gov.cn）

**覆盖数据：M2/社融/新增贷款、LPR、货币政策报告、新闻发布会**

```python
PBOC_ENDPOINTS = {
    'cn_pboc_monetary': {
        'listing_url':   'https://www.pbc.gov.cn/rmyh/105208/index.html',  # 货币统计数据
        'press_listing': 'https://www.pbc.gov.cn/goutongjiaoliu/113456/index.html',  # 新闻发布会
        'description':   'M2、社融、信贷数据，附发布会记录（含记者问答）',
        'content_type':  'html',
    },
    'cn_pboc_lpr': {
        'listing_url':   'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/index.html',
        'description':   'LPR报价公告',
        'content_type':  'html',
    },
    'cn_pboc_mpr': {
        # 货币政策执行报告（季度），每季度约发布一次
        'listing_url':   'https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html',
        'description':   '货币政策执行报告全文（季度），最重要的货币政策分析文件',
        'content_type':  'html',
        'frequency':     'quarterly',
    },
}
```

### 4.3 财新 PMI（中英文来源）

```python
CAIXIN_ENDPOINTS = {
    'cn_caixin_pmi': {
        # 财新PMI由IHS Markit/S&P Global发布，英文版含更详细分析
        'english_url':   'https://www.pmi.spglobal.com/Public/Home/PressRelease/68d01e62e9aa43a68db1f2c22c5dd38f',
        'chinese_url':   'https://www.caixin.com/tag/PMI/',
        'description':   '财新制造业/服务业PMI，含样本企业定性评述',
        'content_type':  'html',
        'note':          '英文版由S&P Global直接发布，数据和措辞更原始',
    },
}
```

### 4.4 海关总署（customs.gov.cn）

```python
CUSTOMS_ENDPOINTS = {
    'cn_customs_trade': {
        'listing_url':   'http://www.customs.gov.cn/customs/302249/302274/302277/index.html',
        'description':   '进出口贸易数据新闻稿，含商品分类和区域分析',
        'content_type':  'html',
    },
}
```

### 4.5 国家外汇管理局（safe.gov.cn）

```python
SAFE_ENDPOINTS = {
    'cn_safe_fx': {
        'listing_url':   'https://www.safe.gov.cn/safe/ywfb/index.html',
        'description':   '外汇储备数据及说明',
        'content_type':  'html',
    },
}
```

### 4.6 国务院新闻办发布会（scio.gov.cn）

国新办记者会是最重要的政策解读来源，在GDP、CPI等重大数据发布后通常举办。

```python
SCIO_ENDPOINTS = {
    'cn_scio_press': {
        'listing_url':   'http://www.scio.gov.cn/xwfb/index.htm',
        'description':   '国务院新闻办发布会文字记录，包含部委官员详细政策解读和记者问答',
        'content_type':  'html',
        'note':          '这是最有价值的政策点评来源，需要按关键词过滤',
    },
}
```

---

## 五、RSS 订阅（优先使用）

以下来源提供 RSS Feed，应优先使用，无需解析 HTML 列表页：

| 机构 | RSS URL | 说明 |
|------|---------|------|
| BEA（美国经济分析局）| `https://www.bea.gov/rss/releases.xml` | 包含所有新闻稿链接 |
| 国家统计局 | `https://www.stats.gov.cn/rss.xml` | 包含最新发布 |
| 美联储 | `https://www.federalreserve.gov/feeds/press_all.xml` | 所有新闻稿 |
| Census Bureau | `https://www.census.gov/economic-indicators/feed.xml` | 零售、房屋开工等 |

```python
import feedparser

def poll_rss(feed_url: str) -> list:
    feed = feedparser.parse(feed_url)
    return [{
        'title': entry.title,
        'link':  entry.link,
        'published': entry.published,
        'summary': entry.get('summary', ''),
    } for entry in feed.entries]
```

---

## 六、完整调度流程代码

```python
import schedule
import time
from datetime import datetime

class MacroDataPipeline:
    
    def __init__(self, jin10_key: str):
        self.jin10_key = jin10_key
        self.task_queue = []
    
    def step1_pull_calendar(self):
        """每天早上7点拉取未来7天日历，写入任务队列"""
        calendar = get_calendar(region='all', days_ahead=7)
        for event in calendar:
            if event.get('importance', 0) >= 2:  # 只处理2星及以上重要事件
                event_key = EVENT_ROUTER.get(event['event_name'])
                if event_key:
                    self.task_queue.append({
                        'event_name': event['event_name'],
                        'publish_time': event['publish_time'],
                        'fetcher_key': event_key,
                        'previous': event.get('previous'),
                        'forecast': event.get('forecast'),
                    })
        print(f"[日历] 写入 {len(self.task_queue)} 个任务")
    
    def step2_check_and_fetch(self):
        """每15分钟检查是否有任务到点"""
        now = datetime.now()
        due_tasks = [t for t in self.task_queue 
                     if abs((t['publish_time'] - now).total_seconds()) < 900]
        
        for task in due_tasks:
            self.fetch_report(task)
            self.task_queue.remove(task)
    
    def fetch_report(self, task: dict):
        """根据fetcher_key路由到对应爬虫"""
        fetcher_map = {
            'us_bls_cpi':           fetch_bls_report,
            'us_fed_fomc_statement': fetch_fed_report,
            'cn_stats_cpi':         fetch_nbs_report,
            'cn_pboc_monetary':     fetch_pboc_report,
            # ... 其他映射
        }
        
        fetcher = fetcher_map.get(task['fetcher_key'])
        if not fetcher:
            return
        
        config = ALL_ENDPOINTS[task['fetcher_key']]
        result = fetcher(config['latest_url'])
        
        # 打上元数据标签（关键！）
        result['meta'] = {
            'event_name':    task['event_name'],
            'publish_time':  task['publish_time'].isoformat(),
            'previous':      task['previous'],
            'forecast':      task['forecast'],
            'fetcher_key':   task['fetcher_key'],
            'data_type':     'official_press_release',
        }
        
        self.save_to_db(result)
    
    def save_to_db(self, doc: dict):
        """存入向量数据库（附完整元数据）"""
        # 示例：存入 Qdrant 或 PGVector
        # embedding = embed(doc['full_text'])
        # vector_db.upsert(embedding, doc['meta'], doc['full_text'])
        print(f"[存储] {doc['meta']['event_name']} @ {doc['meta']['publish_time']}")

# 调度
pipeline = MacroDataPipeline(jin10_key='YOUR_KEY')
schedule.every().day.at("07:00").do(pipeline.step1_pull_calendar)
schedule.every(15).minutes.do(pipeline.step2_check_and_fetch)

# RSS 轮询（不依赖日历，作为补充）
schedule.every(30).minutes.do(lambda: poll_rss('https://www.bea.gov/rss/releases.xml'))
schedule.every(30).minutes.do(lambda: poll_rss('https://www.federalreserve.gov/feeds/press_all.xml'))

while True:
    schedule.run_pending()
    time.sleep(60)
```

---

## 七、元数据字段规范

每条入库文档必须携带以下元数据，否则 Agent 无法准确引用：

```json
{
  "source_institution": "BLS | Federal Reserve | 国家统计局 | ...",
  "source_country": "US | CN",
  "data_category": "inflation | employment | gdp | monetary_policy | pmi | trade",
  "event_name": "美国CPI",
  "report_period": "2024-12",
  "publish_time": "2025-01-15T13:30:00Z",
  "data_type": "official_press_release",
  "previous_value": "2.7%",
  "forecast_value": "2.9%",
  "actual_value": "2.9%",
  "beat_miss": "inline",
  "url": "https://www.bls.gov/news.release/cpi.nr0.htm",
  "language": "en | zh",
  "contains_official_commentary": true
}
```

`contains_official_commentary` 字段标记该文档是否包含官员点评，Agent 检索时可优先过滤此类文档做解读分析。

---

## 八、各来源价值评级

| 来源 | 数据类型 | 包含点评？ | 稳定性 | 优先级 |
|------|---------|-----------|-------|-------|
| BLS（美国） | CPI/PPI/就业 | ✅ 统计员分析 | ⭐⭐⭐⭐⭐ | 🔴 最高 |
| Federal Reserve | FOMC/纪要/褐皮书 | ✅ 委员原话 | ⭐⭐⭐⭐⭐ | 🔴 最高 |
| BEA（美国） | GDP/PCE | ✅ 分析师说明 | ⭐⭐⭐⭐⭐ | 🔴 最高 |
| ISM（美国） | PMI | ✅ 行业受访评述 | ⭐⭐⭐⭐ | 🟠 高 |
| 国家统计局 | CPI/GDP/PMI等 | ✅ 发言人点评 | ⭐⭐⭐⭐⭐ | 🔴 最高 |
| 人民银行 | M2/社融/LPR | ✅ 货币政策报告 | ⭐⭐⭐⭐⭐ | 🔴 最高 |
| 国新办发布会 | 政策解读 | ✅✅ 官员问答 | ⭐⭐⭐⭐ | 🔴 最高 |
| 财新/S&P PMI | PMI | ✅ 定性评述 | ⭐⭐⭐⭐ | 🟠 高 |
| 海关总署 | 贸易 | ✅ 分析说明 | ⭐⭐⭐⭐ | 🟡 中高 |
| 密歇根大学调查 | 消费者信心 | ✅ 调查解读 | ⭐⭐⭐ | 🟡 中高 |

"""
One-time migration: insert 4 hardcoded articles from old index.html into blog.db.
Run from /root/aicdn/blog_admin/:  python3 migrate_articles.py
Safe to re-run: skips articles whose slug already exists.
"""
import sqlite3, os, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, '..', 'blog.db')

ARTICLES = [
    {
        'slug': 'what-is-ai-crawler',
        'title': '什麼是 AI 爬蟲？你的網站被 OpenAI、Gemini、Claude 看見了嗎？',
        'excerpt': 'AI 搜尋時代來臨，GPTBot、Google-Extended、ClaudeBot 正在大量爬取網路內容。了解它們的運作原理，搶先佈局。',
        'cover_image': '/images/article-image/aicrawler.png',
        'keywords': 'AI爬蟲,GPTBot,Google-Extended,ClaudeBot,AI搜尋',
        'category': 'AI 爬蟲',
        'publish_at': '2026-05-01 00:00:00',
        'content': '''<p>在 AI 驅動搜尋的新時代，讓你的網站被 ChatGPT、Gemini 和 Claude 看見，已成為品牌數位曝光的關鍵戰場。</p>

<h2>什麼是 AI 爬蟲？</h2>
<p>AI 爬蟲（AI Crawler）是大型語言模型（LLM）訓練與即時資料更新的核心工具。主要的 AI 爬蟲包括：</p>
<ul>
  <li><strong>GPTBot</strong>：OpenAI 用於訓練 GPT 系列模型的爬蟲</li>
  <li><strong>Google-Extended</strong>：Google 用於 Gemini 模型訓練的爬蟲</li>
  <li><strong>ClaudeBot</strong>：Anthropic 用於 Claude 模型訓練的爬蟲</li>
  <li><strong>Applebot-Extended</strong>：Apple 用於 Apple Intelligence 的爬蟲</li>
  <li><strong>PerplexityBot</strong>：Perplexity AI 用於即時搜尋的爬蟲</li>
</ul>

<h2>AI 爬蟲與傳統搜尋爬蟲的差異</h2>
<p>傳統 SEO 著重讓 Google Bot 讀取頁面建立索引，目的是在搜尋結果排名靠前。AI 爬蟲則不同——它們蒐集的內容，直接影響 AI 模型對你品牌的「認知」。</p>
<p>當消費者問 ChatGPT「台灣最好的 CDN 服務商是哪家？」，AI 的回答取決於它爬取過哪些網站、讀到哪些內容。這就是 AEO（Answer Engine Optimization）的核心概念。</p>

<h2>為什麼你的網站需要 AI 爬蟲曝光？</h2>
<p>根據業界觀察，AI 搜尋已開始蠶食傳統搜尋流量。Z 世代消費者直接用 ChatGPT 詢問產品建議，而非點開 Google 搜尋結果頁。如果你的品牌沒有被 AI 爬蟲「看見」，等於在 AI 時代的搜尋市場中缺席。</p>

<h2>如何讓 AI 爬蟲更容易讀取你的網站？</h2>
<ul>
  <li>確認 robots.txt 不封鎖 GPTBot、Google-Extended、ClaudeBot</li>
  <li>採用 SSR（伺服器端渲染）確保 AI 爬蟲可讀取完整內容</li>
  <li>加入結構化資料（Schema.org）提升內容可解析性</li>
  <li>建立高品質、原創的專業內容（E-E-A-T 原則）</li>
  <li>透過 AICDN 平台直接提升 AI 爬蟲造訪頻率與深度</li>
</ul>

<p>AICDN 是台灣首個專為 AI 爬蟲優化設計的 CDN 平台，透過與主流 AI 爬蟲的直接合作，幫助品牌在 AI 搜尋時代搶佔先機。</p>'''
    },
    {
        'slug': 'ecommerce-ai-crawler',
        'title': '在 AEO 的時代，如蝦皮和夏普的電商更需要佈局 AI 爬蟲增量！？',
        'excerpt': '電商網站是金雞，在人人用 AI 的時代，促銷活動要被 AI 看見才有效。了解 AICDN 如何直接提升電商品牌的爬蟲曝光量。',
        'cover_image': '/images/article-image/ecommerce.png',
        'keywords': 'AEO,電商,AI爬蟲,蝦皮,夏普,品牌曝光',
        'category': '電商策略',
        'publish_at': '2026-06-01 00:00:00',
        'content': '''<p>在 AI 驅動消費決策的時代，電商品牌的促銷活動不再只需要 Google 廣告和社群媒體——更需要讓 AI 爬蟲「看見」你的優惠。</p>

<h2>AEO 是什麼？為何電商品牌要重視？</h2>
<p>AEO（Answer Engine Optimization，答案引擎優化）是 SEO 的進化版。當消費者問 ChatGPT「雙 11 蝦皮有什麼好折扣？」或「夏普空氣清淨機值得買嗎？」，AI 的回答直接影響購買決策。</p>
<p>傳統電商 SEO 是讓 Google 搜尋結果頁排名靠前；AEO 則是讓你的品牌資訊直接出現在 AI 的回答中。</p>

<h2>電商網站的 AI 爬蟲挑戰</h2>
<p>電商網站面臨獨特的 AI 爬蟲挑戰：</p>
<ul>
  <li><strong>JavaScript 渲染問題</strong>：大多數電商平台依賴 React/Vue 渲染，AI 爬蟲可能讀不到完整商品資訊</li>
  <li><strong>促銷資訊時效性</strong>：限時折扣、庫存狀態需要 AI 爬蟲頻繁更新</li>
  <li><strong>商品評論未被爬取</strong>：真實用戶評價是 AI 建立品牌認知的重要依據</li>
  <li><strong>競爭者先行佈局</strong>：若競爭對手品牌被 AI 更頻繁爬取，在 AI 推薦中就佔優勢</li>
</ul>

<h2>AICDN 如何幫電商品牌解決 AI 爬蟲問題？</h2>
<p>AICDN 平台透過以下機制，直接提升電商品牌的 AI 爬蟲曝光量：</p>
<ul>
  <li>與 GPTBot、Google-Extended、ClaudeBot 等主流 AI 爬蟲建立直接合作關係</li>
  <li>優先推薦你的品牌頁面讓 AI 爬蟲造訪</li>
  <li>SSR 技術確保商品資訊完整可讀</li>
  <li>結構化資料標記商品、評論、促銷活動</li>
</ul>

<h2>實際案例：品牌在 AICDN 上的成效</h2>
<p>加入 AICDN 的電商品牌，平均在 7 天內觀察到 AI 爬蟲造訪頻率提升 3-5 倍。在 ChatGPT、Gemini 的產品推薦中出現頻率顯著增加。</p>
<p>在 AI 搜尋成為主流的今天，電商品牌的 AI 可見度，就是下一個競爭護城河。</p>'''
    },
    {
        'slug': 'what-is-ai-cdn',
        'title': 'AI CDN 是什麼？2026 年電商品牌必懂的智能流量加速技術',
        'excerpt': '消費者已經開始問 ChatGPT、Gemini、Claude 該買什麼牌子。AI CDN 如何讓 AI 爬蟲看得到、看得懂、常常來，電商品牌不可不知。',
        'cover_image': '/images/article-image/google_gemini.jpeg',
        'keywords': 'AI CDN,CDN,AI爬蟲,智能流量,電商品牌',
        'category': 'AI CDN',
        'publish_at': '2026-07-01 00:00:00',
        'content': '''<p>CDN（內容傳遞網路）技術已有 20 年歷史，但 AI CDN 是全新的概念——專為 AI 爬蟲時代設計的智能流量加速技術。</p>

<h2>傳統 CDN vs AI CDN：核心差異</h2>
<p>傳統 CDN 的目的是加速靜態資源傳遞，讓用戶從最近的節點取得圖片、CSS、JS 等資源，降低延遲、提升載入速度。</p>
<p>AI CDN 則專注於一個完全不同的目標：<strong>讓 AI 爬蟲更有效率地讀取、理解並記憶你的品牌內容</strong>。</p>

<h2>AI CDN 的核心功能</h2>
<ul>
  <li><strong>AI 爬蟲流量優化</strong>：識別並優先服務 GPTBot、ClaudeBot 等 AI 爬蟲的請求</li>
  <li><strong>SSR 即時渲染</strong>：確保 JavaScript 渲染的內容也能被 AI 爬蟲完整讀取</li>
  <li><strong>結構化資料注入</strong>：自動為頁面加入 Schema.org 標記，讓 AI 更容易解析內容</li>
  <li><strong>爬取頻率管理</strong>：主動與 AI 爬蟲溝通，提高品牌頁面的爬取優先級</li>
  <li><strong>內容新鮮度維護</strong>：確保 AI 爬蟲取得最新的品牌資訊和促銷活動</li>
</ul>

<h2>為什麼 2026 年電商品牌必須了解 AI CDN？</h2>
<p>根據 Gartner 預測，2026 年將有超過 30% 的消費者使用 AI 助手進行產品研究和購買決策。當消費者問「哪個品牌的筆電最適合設計師？」，AI 的回答直接影響轉換率。</p>
<p>AI CDN 不是選配——在競爭對手都在佈局 AI 可見度的時代，它是電商品牌的數位生存工具。</p>

<h2>AICDN 平台：台灣首個 AI CDN 服務</h2>
<p>AICDN 由騰雲運算（股票代號 7405）開發，是台灣首個專為 AI 爬蟲優化的 CDN 平台。透過雙邊市場機制，連結想被 AI 看見的品牌（Buyer）與提供內容流量的網站（Seller）。</p>
<p>加入 AICDN，7 天免費體驗 AI 爬蟲曝光成效，數據說話。</p>'''
    },
    {
        'slug': 'ai-crawler-optimization-guide',
        'title': 'AI 爬蟲優化完整指南：讓 ChatGPT、Gemini、Claude 主動爬你的網站',
        'excerpt': '從 robots.txt、SSR 技術到結構化資料、E-E-A-T，完整拆解讓 AI 爬蟲找到你、讀懂你、持續回訪的全方位優化策略。',
        'cover_image': '/images/article-image/AI_bot_1.webp',
        'keywords': 'AI爬蟲優化,robots.txt,SSR,結構化資料,E-E-A-T,ChatGPT,Gemini,Claude',
        'category': 'AI 爬蟲優化',
        'publish_at': '2026-07-15 00:00:00',
        'content': '''<p>要讓 AI 爬蟲（GPTBot、ClaudeBot、Google-Extended）主動爬取你的網站並在 AI 推薦中被提及，需要從技術、內容、權威度三個維度全面優化。</p>

<h2>第一步：確認你的 robots.txt 沒有封鎖 AI 爬蟲</h2>
<p>許多網站管理員出於保護意圖，在 robots.txt 中封鎖了所有未知爬蟲，卻意外阻擋了 AI 爬蟲。請確認你的 robots.txt 允許以下爬蟲：</p>
<pre>User-agent: GPTBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /</pre>
<p>只封鎖你明確不希望被爬取的路徑（如管理後台、個人資料頁）。</p>

<h2>第二步：採用 SSR 確保內容可讀性</h2>
<p>大多數 AI 爬蟲不執行 JavaScript。如果你的網站是 React SPA 或 Vue 應用，爬蟲看到的可能只是空白頁面。解決方案：</p>
<ul>
  <li>使用 Next.js、Nuxt.js 等 SSR 框架</li>
  <li>導入 Prerendering 服務（如 Prerender.io）</li>
  <li>關鍵落地頁採用靜態 HTML</li>
</ul>

<h2>第三步：加入結構化資料（Schema.org）</h2>
<p>結構化資料幫助 AI 理解頁面的語義。根據你的頁面類型加入相應 Schema：</p>
<ul>
  <li>企業介紹頁：<code>Organization</code></li>
  <li>商品頁：<code>Product</code> + <code>Offer</code> + <code>Review</code></li>
  <li>文章頁：<code>Article</code> + <code>Author</code></li>
  <li>FAQ 頁：<code>FAQPage</code></li>
</ul>

<h2>第四步：建立 E-E-A-T 內容</h2>
<p>Google 的 E-E-A-T（Experience, Expertise, Authoritativeness, Trustworthiness）原則同樣適用於 AI 爬蟲的內容評估：</p>
<ul>
  <li><strong>Experience（經驗）</strong>：分享實際案例、第一手數據</li>
  <li><strong>Expertise（專業）</strong>：由領域專家撰寫或審核內容</li>
  <li><strong>Authoritativeness（權威）</strong>：獲得媒體報導、業界引用</li>
  <li><strong>Trustworthiness（可信度）</strong>：明確的聯絡資訊、隱私政策、安全連線</li>
</ul>

<h2>第五步：透過 AICDN 加速 AI 爬蟲造訪</h2>
<p>上述優化需要時間積累效果。AICDN 提供更直接的方法：透過與主流 AI 爬蟲的合作關係，主動提升你品牌頁面的爬取頻率和深度。</p>
<p>7 天免費試用，觀察 AI 爬蟲造訪頻率的實際改變，數據說話。</p>

<h2>常見問題 FAQ</h2>
<p><strong>Q：AI 爬蟲多久爬一次我的網站？</strong><br>
A：未優化的網站可能數週才被爬一次；透過 AICDN 優化後，可縮短至數天甚至每日爬取。</p>

<p><strong>Q：AI 爬蟲優化會影響傳統 SEO 嗎？</strong><br>
A：不會衝突，反而互補。AI 爬蟲優化的技術基礎（SSR、結構化資料）同樣有助於傳統 SEO。</p>

<p><strong>Q：多快能看到效果？</strong><br>
A：robots.txt 和 SSR 調整後，AI 爬蟲通常在 1-2 週內開始更頻繁爬取。透過 AICDN 可加速至 7 天內見到明顯成效。</p>'''
    },
]

def get_or_create_category(db, name):
    row = db.execute('SELECT id FROM blog_categories WHERE name=?', (name,)).fetchone()
    if row:
        return row[0]
    slug = name.lower().replace(' ', '-').replace('爬蟲', 'crawler').replace('策略', 'strategy').replace('優化', 'optimization')
    db.execute('INSERT INTO blog_categories (name, slug) VALUES (?,?)', (name, slug))
    db.commit()
    row = db.execute('SELECT id FROM blog_categories WHERE name=?', (name,)).fetchone()
    return row[0]

def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    inserted = 0
    skipped  = 0
    for a in ARTICLES:
        existing = conn.execute('SELECT id FROM blog_posts WHERE slug=?', (a['slug'],)).fetchone()
        if existing:
            print(f'  skip (exists): {a["slug"]}')
            skipped += 1
            continue
        cat_id = get_or_create_category(conn, a['category'])
        conn.execute('''
            INSERT INTO blog_posts
              (slug, title, excerpt, content, cover_image, keywords, category_id,
               status, publish_at, created_by)
            VALUES (?,?,?,?,?,?,?,'published',?,1)
        ''', (a['slug'], a['title'], a['excerpt'], a['content'],
              a['cover_image'], a['keywords'], cat_id, a['publish_at']))
        conn.commit()
        print(f'  inserted: {a["slug"]}')
        inserted += 1
    conn.close()
    print(f'\nDone: {inserted} inserted, {skipped} skipped.')

if __name__ == '__main__':
    migrate()

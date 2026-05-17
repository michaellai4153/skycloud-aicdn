# AICDN — Claude Code 專案備忘

> 給下一個 Claude 接手 session 的快速 context。User 是 cliff@skycloud.com.tw。

## 一句話介紹

AICDN 是 SkyCloud 騰雲運算（股票 7405）的 AI 爬蟲變現平台。雙邊市場：
**Buyer** 付費讓品牌被 AI 爬蟲看到 / **Seller** 內容站把流量導給 AI 賺分潤。

實際爬蟲推薦機制在 CDN 平台（外部），這個 repo 範圍：行銷站、名單收集、CRM、金流。

---

## 線上環境

| | URL | 用途 |
|---|---|---|
| Buyer 端 | https://www.aicdn.ai | landing + admin + AI 助手 |
| Seller 端 | https://referral.aicdn.ai | landing + CRM |

**SSH：** `ssh -p 57422 root@www.aicdn.ai`（HK，Rocky Linux 9）

**Repo：** https://github.com/michaellai4153/skycloud-aicdn

**ClickUp parent task：** https://app.clickup.com/t/86exmfp51

---

## 架構

```
                 nginx 1.26 (HTTPS, HTTP/2, gzip, fail2ban)
                     │
        ┌────────────┴───────────────┐
        │                            │
  port 8765 (buyer)            port 8766 (seller)
  server.py                    seller_server.py
  systemd: aicdn               systemd: aicdn-seller
        │                            │
        └─────────────┬──────────────┘
                      │ shared SQLite
                  /root/aicdn/aicdn.db

  port 18888 (localhost) — autossh tunnel
  systemd: aicdn-tunnel.service
       │
       ▼
  probejp.metage.xyz:13367  →  HTTP CONNECT proxy 127.0.0.1:8888
                            →  api.openai.com（JP 出口繞 HK 封鎖）
```

### HK → OpenAI 重點

Production 在 **HK**，OpenAI 直接擋。所有對 OpenAI / Google API 的呼叫**必須走 proxy**：

- `openai_client.py` 讀 `config.openai_proxy` → 用 urllib `ProxyHandler` 透過 CONNECT proxy 走
- `oauth.py` 同樣用這個 proxy 去抓 Google token
- autossh tunnel 由 `/etc/systemd/system/aicdn-tunnel.service` 維護
- SSH key in `/root/.ssh/id_ed25519`（已加到 probejp 的 authorized_keys）

---

## Config（皆 gitignored）

| 檔 | 範本 |
|---|---|
| `config.json` | `config.example.json` |
| `seller_config.json` | `seller_config.example.json` |

部署時：
```bash
cp config.example.json config.json
# 編輯 config.json 填實際 keys（OpenAI key、Google OAuth client/secret、ECPay）
```

關鍵 keys（不能進 git）：
- `openai_api_key` — OpenAI Platform 後台拿
- `google_client_id` / `google_client_secret` — GCP Console → APIs & Services → Credentials
- `ecpay.merchant_id` / `hash_key` / `hash_iv` — 正式特店申請後拿到（目前是公開 sandbox 預設值）

---

## 重要 conventions（請遵守）

1. **任何變更走 PR 流程**：
   - `git checkout main && git pull && git checkout -b <type>/<name>`
   - commit + push
   - `gh pr create ...`
   - 等 user merge
   - 然後我 ssh 部署

2. **不直接 SSH 寫 production 檔案**（程式碼），除非：
   - 是 nginx 設定（不在 repo 裡）
   - 是 systemd unit 檔
   - 是 config.json（裡面是 secrets）
   - 或 user 明說 OK

3. **nginx 改設定前一定 `nginx -t` 通過再 reload**

4. **不 commit secrets**：API keys、密碼、token 永遠在 gitignored 檔案

5. **OpenAI / Google API 一定要透過 `config.openai_proxy`**（HK 封鎖）

6. **User 的 GitHub 帳號：** `cliff-staff`（collaborator on michaellai4153's repo）

---

## 服務 & 路徑

### systemd units
- `aicdn.service` — buyer server (port 8765)
- `aicdn-seller.service` — seller server (port 8766)
- `aicdn-tunnel.service` — autossh OpenAI proxy tunnel
- `nginx.service`
- `fail2ban.service`

### 重要 paths（production）
```
/root/aicdn/                  # app dir, git repo
  ├── server.py               # buyer
  ├── seller_server.py        # seller
  ├── db.py / oauth.py / ecpay.py / openai_client.py / qa_render.py
  ├── knowledge_base.py / gen_questions.py
  ├── *.html
  ├── images/                 # WebP + PNG/JPEG sources
  ├── config.json             # GITIGNORED — secrets
  ├── seller_config.json      # GITIGNORED
  └── aicdn.db                # SQLite — GITIGNORED

/var/www/aicdn/images → /root/aicdn/images  # symlink for nginx-direct serving

/etc/nginx/conf.d/aicdn.conf       # www.aicdn.ai vhost
/etc/nginx/conf.d/referral.conf    # referral.aicdn.ai vhost
/etc/nginx/conf.d/00-gzip.conf     # global gzip

/etc/letsencrypt/live/{www.aicdn.ai,referral.aicdn.ai}/  # certs
/etc/fail2ban/jail.d/nginx-scanner.local
```

### 還有什麼跑在 server 上
- fail2ban：監聽 nginx error log，60 秒內 5 次掃描自動 ban 5 分鐘 DROP
- Swap：2 GB（防 OOM）

---

## 待辦（剩 3 個非工程任務）

| Task | 性質 | URL |
|---|---|---|
| P3-9 申請綠界正式特店帳號 | 業務 | [86exmfquc](https://app.clickup.com/t/86exmfquc) |
| P3-10 切換 ECPay sandbox → production | 工程 5min | [86exmfqur](https://app.clickup.com/t/86exmfqur) — 等 P3-9 拿到 keys |
| SEO-1 製作 og:image 1200×630 | 設計 | [86exmp1xq](https://app.clickup.com/t/86exmp1xq) |

---

## API 列表（給接手 Claude 快速理解）

### Buyer (www.aicdn.ai)
| Method | Path | Auth |
|---|---|---|
| GET | `/` | — |
| GET | `/admin.html` | — (Google OAuth required for API) |
| GET | `/qa/<slug>` | — (SSR + cache) |
| GET | `/api/qa` | — (returns 10 questions + 5 random) |
| GET | `/api/leads` | session cookie |
| POST | `/api/leads` | session cookie (addRow / updateRow) |
| GET | `/api/oauth/login?return=...` | — |
| GET | `/api/oauth/callback` | — (sets cookie with `Domain=.aicdn.ai`) |
| GET | `/api/me` | — |
| POST | `/api/logout` | — |
| POST | `/api/create-payment` | session cookie |
| GET | `/pay/<order_id>` | — (renders ECPay form) |
| POST | `/api/ecpay-return` | ECPay signature |
| GET | `/api/ecpay-result` | — |
| GET | `/sitemap.xml` `/robots.txt` | — |

### Seller (referral.aicdn.ai) — 平行的 API，前綴 `/api/seller-leads*`、`/api/create-payment`

---

## 已做過的重大決策（避免重做）

1. **HTTPS 必開** — Let's Encrypt 自動續約
2. **HTTP/2 開了**（nginx 1.26 後）
3. **gzip on** + Cache-Control `/images/` 30 天 immutable
4. **WebP 加 `<picture>` fallback**
5. **CDN images：nginx-direct（不再 proxy Python）**
6. **GitHub Pages 已關**（避免 source code 從 github.io 洩漏）
7. **fail2ban**：60s 5 次掃描封 5 min DROP
8. **POST 白名單**：非 API 路徑 POST 一律 403
9. **__pycache__ / *.pyc / README.md / .git / .claude 全 block**

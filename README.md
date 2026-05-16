# AICDN — 騰雲運算 AI 爬蟲變現平台

雙邊市場行銷網站：招募 **Buyer**（內容主，付費讓內容被 AI 爬蟲看到）與 **Seller**（內容站，幫忙曝光 Buyer 內容並抽分潤）。

> 實際的爬蟲推薦機制在 CDN 平台，本 repo 範圍：行銷網站、名單收集、後台管理、金流串接。

- 🌐 **線上**：[https://www.aicdn.ai](https://www.aicdn.ai)
- 📋 **專案任務**：[ClickUp - AICDN](https://app.clickup.com/t/86exmfp51)

---

## 系統架構

```
                      ┌──────────────────────────┐
                      │   www.aicdn.ai (nginx)   │
                      │   HTTPS, fail2ban, swap  │
                      └────────────┬─────────────┘
                                   │ reverse proxy
                  ┌────────────────┴────────────────┐
                  │                                  │
         ┌────────▼─────────┐              ┌─────────▼──────────┐
         │ server.py :8765  │              │ seller_server.py   │
         │  (Buyer 端)      │              │  :8766 (Seller 端) │
         │                  │              │                    │
         │ - index.html     │              │ - seller_index.html│
         │ - admin.html     │              │ - seller_crm.html  │
         │ - leads.json     │              │ - seller_leads.json│
         └──────────────────┘              └────────────────────┘

業務流程：
   Buyer            付費          AICDN          分潤        Seller
   內容主  ───────────▶  仲介平台 ───────────▶  內容站
                                 │
                                 ▼
                          CDN 推薦機制（外部）
                                 │
                                 ▼
                              AI 爬蟲
```

---

## 技術 Stack

| 層級 | 技術 |
|------|------|
| Web Server | nginx（reverse proxy + HTTPS）|
| Backend | Python 3 內建 `http.server` + `ThreadingMixIn` |
| Storage | JSON 檔案（規劃遷移 SQLite）|
| Auth | Bearer token（規劃遷移 Google OAuth）|
| HTTPS | Let's Encrypt（certbot 自動續約）|
| 進程管理 | systemd |
| 防護 | fail2ban（動態封鎖掃描行為）|

---

## 檔案結構

```
.
├── index.html          # Buyer 端 landing page
├── admin.html          # Buyer 端後台 CRM
├── server.py           # Buyer 端 server (port 8765)
├── leads.json          # Buyer 名單 (gitignored)
├── config.json         # Buyer 設定，含密碼 (gitignored)
│
├── seller_index.html   # Seller 端 landing page
├── seller_crm.html     # Seller 端後台 CRM
├── seller_server.py    # Seller 端 server (port 8766)
├── seller_leads.json   # Seller 名單 (gitignored)
├── seller_config.json  # Seller 設定 (gitignored)
│
└── data/               # AI 助手知識庫文件（規劃中）
```

---

## API 列表

### Buyer Server (port 8765)

| Method | Path | 認證 | 說明 |
|--------|------|------|------|
| GET | `/` | — | 首頁 |
| GET | `/admin.html` | — | 後台頁面 |
| POST | `/api/login` | — | 密碼驗證，回傳 token |
| GET | `/api/leads` | Bearer | 取得名單 |
| POST | `/api/leads` | Bearer | 新增 / 更新名單 |
| GET | `/config.json` | — | **403 Forbidden** |
| GET | `/leads.json` | — | **403 Forbidden** |
| GET | `/server.py` | — | **403 Forbidden** |

### Seller Server (port 8766)

結構同上，路徑前綴一樣，獨立 token、獨立資料表。

### POST 白名單

POST 只允許 `/api/login`、`/api/leads`、`/api/chat`，其他路徑一律 403（防止 Next.js 漏洞掃描）。

---

## 本地開發

```bash
# clone
git clone git@github.com:michaellai4153/skycloud-aicdn.git
cd skycloud-aicdn

# 建立 config.json
cat > config.json << EOF
{
  "username": "admin",
  "password": "你的密碼"
}
EOF

# 啟動 buyer server
python3 server.py
# → http://localhost:8765

# 啟動 seller server（另一個 terminal）
python3 seller_server.py
# → http://localhost:8766
```

---

## 部署

正式環境：`www.aicdn.ai`（Rocky Linux 9.4 + nginx + systemd）

### 第一次部署

```bash
# SSH 進主機
ssh -p 57422 root@www.aicdn.ai

# clone
cd /root && git clone https://github.com/michaellai4153/skycloud-aicdn.git aicdn
cd aicdn

# 建立 config.json（內容自填）
vi config.json

# systemd service
cat > /etc/systemd/system/aicdn.service << EOF
[Unit]
Description=AiCDN SkyCloud Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/aicdn
ExecStart=/usr/bin/python3 /root/aicdn/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aicdn
```

### 後續更新

```bash
cd /root/aicdn
git pull origin main
systemctl restart aicdn
# 若改 nginx 設定：nginx -t && systemctl reload nginx
```

---

## 安全防護

| 防護 | 設定位置 | 說明 |
|------|---------|------|
| HTTPS | nginx + Let's Encrypt | 自動續約 |
| Firewall | firewalld | 只開 80/443/57422 |
| SSH | sshd_config | 禁密碼登入、root 限 pubkey |
| fail2ban | `/etc/fail2ban/jail.d/nginx-scanner.local` | 30秒8次觸發封鎖 5 分鐘（DROP）|
| Sensitive files | server.py 內 | `config.json` / `leads.json` / `.git` / `.claude` 對外 403 |
| POST whitelist | server.py 內 | 非 API 路徑 POST 一律 403 |
| Swap | `/swapfile` 2GB | 防 OOM |

---

## config.json 範例

```json
{
  "username": "admin",
  "password": "your-secret-password"
}
```

（規劃中：未來會新增 `oauth_client_id`、`ecpay_merchant_id` 等欄位）

---

## Roadmap

詳見 [ClickUp parent task](https://app.clickup.com/t/86exmfp51)：

- **Phase 1** 基礎建設：README、SQLite 遷移
- **Phase 2** 後台 Google OAuth 登入（限 @skycloud.com.tw）
- **Phase 3** 綠界金流（信用卡、半自動流程）
- **Phase 4** AI 助手（10 題隨機問、動態回答頁 + SEO）

---

## License

Private / 騰雲運算 SkyCloud

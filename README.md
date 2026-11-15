# 球場帳本 Gridiron Ledger — v1

用投資人與領隊的眼睛看 NFL。這個資料夾是藍圖的第一個可執行版本，分成兩部分：

- **工作室（studio）**：在你的 Mac 上跑的指令 `ledger`。管稿件、來源、兩道人工閘門、待貼稿、預測紀錄、工時與每週總表。只用 Python 3 標準函式庫與 SQLite，不需要安裝任何套件，也不需要網路。
- **公開網站（site）**：`ledger build` 從已核准的稿件產生的靜態網站，沒有框架，可以直接丟到 Vercel、Netlify 或 GitHub Pages。

## v1 做得到的事

| 事情 | 指令 |
|---|---|
| 建資料夾與資料庫 | `init` |
| 每個數字建檔，附來源與日期；更正時列出所有要改的稿件與已發布紀錄 | `fact add / list / check / usage / correct` |
| 新稿骨架（開場、判讀、證據、什麼情況下我會改口、CTA） | `new` |
| 閘門 A 數字核對，加上去 AI 化檢查，附行號 | `check` |
| 閘門 B，由你本人核准 | `approve` |
| 產生網站 | `build`、`serve` |
| 產生各平台待貼稿，同篇同平台同版本只做一次 | `publish`、`posted` |
| 追蹤連結 `?src=平台&c=內容編號` | `link` |
| 公開預測紀錄 | `predict add / resolve / list / export` |
| 會員名單（只存雜湊）與每週備份 | `member import / export` |
| 工時、收入、企業詢問 | `cost add`、`cost platform`、`revenue add`、`inquiry add` |
| 每週總表：漏斗、收入來源、每工時營業利潤、月度決策規則 | `import-events`、`report` |
| 變現試算（保守／基準／進取） | `calc` |
| 球團資料表 | `team set / list` |

## v1 沒有串接的東西（NOT CONNECTED）

這四件事 v1 都**不會**替你做，指令輸出裡也會寫明：

1. **社群發文**：`publish` 只會在 `30-published/<內容編號>/` 寫出待貼稿，不呼叫 Threads、IG、FB、YouTube、LinkedIn、Medium、方格子的任何 API。你手動貼上，再用 `posted` 把網址填回來。
2. **收款**：網站只有「mailto 候補名單」這一種可用模式。方格子模式是一個外連按鈕（填了網址才出現）；綠界 ECPay 與藍新 NewebPay 只有占位，設定成它們時網站會退回候補名單，不會出現任何結帳畫面。
3. **寄信**：電子報內容是待貼稿，請貼到你自己的電子報服務寄出。
4. **分析後台**：網站不含任何追蹤程式，也沒有後端。點擊數要從主機的分析功能匯出（見下方「事件怎麼收」）。

## 十分鐘上手（macOS）

macOS 需要 Python 3.9 以上。打開「終端機」：

```bash
python3 --version                 # 沒有的話，先執行 xcode-select --install
cd ~/gridiron-ledger-v1           # 換成你解壓縮的位置

python3 ledger.py init            # 建資料夾與 40-data/ledger.sqlite
python3 ledger.py seed-sample     # 載入範例文章、十筆來源、32 隊名單
python3 ledger.py check SAMPLE-pe # 看一次檢查報告長什麼樣子
python3 ledger.py build           # 產生 site/
python3 ledger.py serve           # 打開 http://localhost:8000 預覽，Ctrl+C 結束
python3 ledger.py publish SAMPLE-pe            # 產生待貼稿（不會真的發文）
python3 ledger.py link SAMPLE-pe --platform threads
python3 ledger.py report          # 產生 reports/weekly.html
python3 ledger.py calc            # 變現試算
python3 -m unittest discover -s tests          # 跑測試
```

想少打幾個字，把 `bin/` 加進 PATH 之後可以直接打 `ledger check SAMPLE-pe`。

上線前一定要改 `ledger.config.json` 的兩個占位值：

- `base_url`：你的網址。sitemap、OG 與追蹤連結都用它。
- `contact_email`：訂閱信會寄到這個信箱。

## 寫一篇稿的流程

```bash
# 1 每個要引用的數字先建檔
python3 ledger.py fact add "私募基金在單一球隊的持股上限" --number 10 --unit "%" \
    --source https://frontofficesports.com/article/nfl-private-equity-mlb-nba/ \
    --source-name "Front Office Sports" --retrieved 2026-11-15

# 2 開新稿（--week 是 NFL 週次；不給就用 ISO 週數）
python3 ledger.py new tech --pillar reading --game 2026-W12-MIN-SF --week 12
#   → 20-drafts/W12-tech.md，用任何編輯器寫

# 3 檢查、核准、發布
python3 ledger.py check W12-tech
python3 ledger.py approve W12-tech
python3 ledger.py publish W12-tech
```

稿件裡的三種標記：

| 寫法 | 意思 |
|---|---|
| `[[fact:3\|單一球隊最多出讓 10%]]` | 引用 fact 3，顯示你寫的文字。文末來源列表會自動產生 |
| `[[fact:3]]` | 引用 fact 3，直接顯示資料庫裡的數字與單位。數字更正後會自動跟著變 |
| `{own:我算了一下，約 17 億美元}` | 你自己算的。看過的用 `{watched:…}`，走過的用 `{visited:…}`。標記本身不會出現在網站上 |

閘門 A 的規則：內文裡每個阿拉伯數字都要在 `[[fact:…]]` 或 `{own:…}` 之內，否則不通過。隊名如 49ers 列在 `50-prompts/lint.json` 的 `number_allowlist`。

去 AI 化檢查的規則都在 `50-prompts/lint.json`，可以自己加禁用詞或調門檻。

數字被來源更正時：

```bash
python3 ledger.py fact correct 3 --number 12
```

它會列出每一份引用這個數字的稿件（含行號，並標出哪些是手寫文字、要人工改）以及每一筆已發布紀錄。改完把檔頭 `version` 加 1，重新 check、approve、publish。

## 每週流程對照指令

| 時間（台灣） | 做什麼 | 指令 |
|---|---|---|
| 週一 08:00 | 三點速報 | 手動發 Threads；數字先 `fact add` |
| 週一至週二 | 看全場、錄語音、整理證據 | 逐字稿放 `10-notes/`；用 `50-prompts/01`、`02` |
| 週二 20:00 | 《一檔看懂》主文 | `new` → 寫 → `check` → `approve` → `publish` |
| 週三 08:30 | 《球場帳本》商業專欄 | 同上，`--pillar ledger`，平台加 `linkedin` |
| 週四 | 短影音 | `publish … --platform yt` 產生腳本骨架 |
| 週五 12:00 | 電子報 | `publish … --platform email`，貼到電子報服務 |
| 每篇寫完 | 記工時，30 秒 | `cost add W12-tech --research 1 --write 3 --edit 0.5 --dist 0.5` |
| 週五 | 30 分鐘複盤 | `import-events events.csv` → `member export` → `report` |
| 賽前與賽後 | 預判留底 | `predict add`、`predict resolve` |
| 每月第一個週日 | 月度決策 | `report --days 28`，看「每月決策規則」那張表 |
| 每週 | 更新觀賽單 | 改 `40-data/watchlist.json` → `build` |

排程範本在 `scripts/launchd/com.gridiron.weekly.plist.template` 與 `scripts/cron.example`。它們是範本，不會自動安裝；安裝方式寫在檔案開頭。

## 事件怎麼收（沒有後端）

網站是純靜態檔案，不會自己記錄點擊。做法是：

1. 每則貼文用 `ledger link` 產生的連結，例如 `https://你的網址/go/threads-W12-tech/?src=threads&c=W12-tech`。每個來源與內容有自己的落地頁路徑 `/go/<來源>-<內容編號>/`，第一屏直接顯示貼文承諾的內容。
2. 每週從主機的分析功能（Vercel Web Analytics、Netlify Analytics、Cloudflare Web Analytics 等）看 `/go/…` 各路徑的瀏覽數，整理成 `events.csv`：

   ```csv
   date,src,c,event,amount
   2026-11-17,threads,W12-tech,click,0
   2026-11-18,threads,W12-tech,signup,0
   2026-11-20,linkedin,W12-biz,paid,199
   ```

   一列代表一次事件。`event` 可以是 `click`、`signup`、`paid`、`cancel`，另外接受 `open`（電子報開信，選填）。
3. `python3 ledger.py import-events events.csv`。同一個檔案重複匯入會被擋下。

**註冊與付費的來源**：落地頁會把第一次的來源記在訪客自己的瀏覽器裡（localStorage），訂閱信的內文會帶上 `src` 與 `c`。你收到信之後，把那個人記進名單 CSV（`first_source` 欄），並在 `events.csv` 加一列 `signup`。歸因只認首次來源，之後不改。

**想自動收**：`ledger.config.json` 的 `events_endpoint` 填一個你自己架的收件網址，落地頁就會用 `navigator.sendBeacon` 送出一筆 JSON（`date, src, c, event, amount`）。v1 不附這個收件端，留空就完全不送。

## 部署網站

`site/` 是完整的靜態網站，沒有建置步驟。

- **Vercel**：`npx vercel deploy site --prod`，或在後台匯入 repo 時 Framework 選 Other、Output Directory 填 `site`、Build Command 留空。
- **Netlify**：把 `site/` 資料夾拖進 app.netlify.com 的 Deploys 頁，或 `npx netlify deploy --dir=site --prod`。
- **GitHub Pages**：把 `site/` 的內容推到 `gh-pages` 分支。頁面之間都用相對路徑，放在子路徑下也能用。

`.gitignore` 預設不把 `site/` 與資料庫放進版本控制。要讓主機從 repo 自動部署，就把 `.gitignore` 裡的 `site/` 那一行拿掉；資料庫與 `40-data/.salt` 不要公開。

每次有新文章核准，重跑 `build` 再部署一次。

## 資料夾

```
gridiron-ledger-v1/
├─ ledger.py、bin/ledger   指令入口
├─ ledger.config.json      init 後產生：網址、信箱、時薪基準、規則門檻
├─ 00-inbox/               抓回來的原始資料，檔名含日期
├─ 10-notes/               看球筆記與語音逐字稿
├─ 20-drafts/              稿件（Markdown）
├─ 30-published/           各平台待貼稿、預測紀錄匯出
├─ 40-data/                ledger.sqlite、watchlist.json、backups/
├─ 50-prompts/             提示詞三件套、各平台改寫模板、lint.json
├─ 60-assets/              自繪圖卡與站位圖
├─ site/                   build 產生的網站
├─ reports/weekly.html     report 產生的每週總表
├─ studio/                 程式
├─ scripts/                launchd 與 cron 範本、weekly.sh
├─ examples/               虛構的示範 CSV
└─ tests/                  單元測試
```

資料表：藍圖的六張（`teams`、`facts`、`posts`、`predictions`、`members`、`costs`），另外加了 `links`、`events`、`imports`、`revenue`、`platform_hours`、`inquiries` 六張輔助表。

## 限制，老實說

- **範例文章的事實沒有在這個環境裡重新上網查證。** 十筆 facts 是照你給的內容與網址建檔的，擷取日期記為 2026-11-15。正式引用前請自己點開來源再核一次。
- **閘門 A 只看阿拉伯數字。** 中文數字（「六年」「三成」）不會被檢查。人名、引述、比分是否正確，腳本也看不出來。
- **`{own}` 是誠信標記。** 腳本無法驗證那真的是你自己的觀察。
- **去 AI 化檢查是樣式比對。** 查得到禁用詞、排比骨架、開頭重複、句長太整齊；查不到翻譯腔與空話。過了檢查不代表寫得好。
- **待貼稿是機械剪裁。** 程式依句子邊界從「我的判讀」一節剪到字數上限，不經 AI，讀起來可能生硬。`threads` 500 字與 `linkedin` 400 字來自藍圖，其他平台的上限是我設的預設值，在 `50-prompts/platforms/limits.json`，請依各平台現行規定調整。
- **決策規則的門檻是起始假設。** 六條規則來自藍圖 8.2，但藍圖沒有給數字門檻，`ledger.config.json` 裡 `rules` 的數值是我設的，不是量測值。樣本數低於 30 一律顯示「樣本太小，再等」。企業詢問那一條也套用同一個 30，實務上很久才會達到，可自行調低。
- **每工時營業利潤**只扣工具成本（預設每月 NT$1,500，按天數攤），不含稅、退款、廣告費。
- **會員名單只存加鹽雜湊。** 備份檔無法還原成 email，真正的名單要在你的電子報服務另外匯出保存。`40-data/.salt` 遺失後，舊雜湊就對不起來。
- **訂閱表單靠訪客的郵件程式。** 沒設定郵件程式的訪客按了不會有反應，頁面上有寫備用做法（直接寄信）。這是驗證需求用的做法，不適合長期使用。
- **PWA**：manifest、圖示與離線 service worker 都有，本機用 Chrome 截圖看過版面；實際「加入主畫面」與離線行為沒有在 iPhone 或 Android 實機上測過。service worker 需要 HTTPS 或 localhost。
- **content_id 的週次**預設用 ISO 週數，不是 NFL 週次，請用 `--week` 指定。
- **沒有 MCP、Connector、n8n、自動抓資料。** 藍圖第 7 節的這些元件 v1 都沒做。
- **只在 Linux 的 Python 3.13 上跑過測試**，沒有在 macOS 實機上跑過。程式只用標準函式庫，應該沒有平台差異，但請以你的機器為準。

法規與版權的注意事項見 `COMPLIANCE.md`。

---

## English summary

**Gridiron Ledger v1** is the first working version of the blueprint: a local, offline "studio" CLI (Python 3 standard library + SQLite, zero dependencies) and a static public site generated from approved Markdown drafts.

**It does:** fact registry with sources and dates, one-pass correction listing every affected draft and post, a draft scaffold, a fact gate plus de-AI lint with line numbers, a human approval gate, idempotent per-platform staging, tracked links, a public prediction ledger, a hashed member list with backups, hours and revenue logging, a weekly HTML report (funnel, revenue by stream, operating profit per hour against NT$400, monthly decision rules with a sample-size guard of 30), and the three-scenario revenue calculator.

**NOT connected in v1:** real social posting (ready-to-paste files only), payments (mailto waitlist only; vocus is an outbound link; ECPay and NewebPay are placeholders that never render a checkout), email sending, and any analytics backend (you import an `events.csv` exported from your host's analytics).

**Quickstart**

```bash
python3 ledger.py init
python3 ledger.py seed-sample
python3 ledger.py check SAMPLE-pe
python3 ledger.py build && python3 ledger.py serve
python3 -m unittest discover -s tests
```

Deploy by uploading the `site/` folder to Vercel, Netlify or GitHub Pages; there is no build step on the host. Set `base_url` and `contact_email` in `ledger.config.json` first.

**Known limits:** the sample facts were entered from the brief and not re-verified online here; the fact gate checks Arabic numerals only; lint is pattern matching; platform rewrites are mechanical cuts; decision-rule thresholds are starting assumptions; tested on Linux/Python 3.13 only, not yet on a Mac or on a phone.

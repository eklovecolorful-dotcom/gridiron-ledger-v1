# Gridiron Ledger 專案自動化寫稿與發布規範

當我要求你建立、撰寫或修改文章時，你必須嚴格遵守以下規則與執行順序：

## 1. 檔案與命名規則
- **存放路徑**：所有新文章草稿一律建立在 `20-drafts/` 目錄下，副檔名為 `.md`。
- **ID 嚴格一致**：檔案名稱（不含 `.md`）與檔案開頭的 `content_id:` 欄位必須完全相同（與程式規則 `[A-Za-z0-9_-]{1,40}` 一致：僅限大小寫英文字母、數字、半形連字號 `-` 與底線 `_`，最長 40 字元，嚴禁空格、中文或其他符號）。直接沿用 `ledger new` 預設產生的 `W<週次>-<slug>` 格式即可（例如 `W12-pe-rule`）。
- **範本參考**：每次建立新文章前，必須先讀取 `20-drafts/SAMPLE-pe.md` 的完整結構與 Frontmatter 欄位，確保所有必填欄位皆存在且格式完全相符。
- **建議起手式**：可先用 `python3 ledger.py new <slug> --pillar <pillar> --game <game> --week <NFL週次>` 產生骨架（content_id 會自動設為 `W<週次>-<slug>`；不加 `--week` 會用 ISO 週數而非 NFL 週次）（會自動帶入正確檔頭與五個段落），再填內容。

### 1.1 Frontmatter 欄位（依 `studio/draft.py` 的 `META_ORDER` 順序）
檔頭必須以單獨一行 `---` 開始、以單獨一行 `---` 結束（缺結尾 `---` 會直接報錯）。每行一個 `key: value`，字串不需加引號。

| 欄位 | 必填 | 格式 / 允許值 |
|---|---|---|
| `content_id` | 是 | 與檔名相同；大小寫英數、`-`、`_`，最長 40 字元（預設格式 `W12-slug`） |
| `title` | 是 | 文章標題（純文字） |
| `summary` | 是 | 一句話摘要，用於首頁、社群與 OG |
| `pillar` | 是 | 只能是 `reading`（一檔看懂）、`ledger`（球團資產）、`travel`（朝聖手冊） |
| `game` | 是 | 場次編號，例如 `2026-W12-MIN-SF`；非單場主題用 `LEAGUE` |
| `date` | 是 | `YYYY-MM-DD` |
| `status` | 是 | 新稿一律 `draft`（`approved`／`published` 由 `ledger approve`／`publish` 寫入，不可手動改） |
| `approved` | 是 | 新稿一律 `false` |
| `version` | 是 | 整數，新稿 `1`；改已發布的稿要加 1 |
| `platforms` | 是 | 方括號清單，例如 `[site, threads, email]`；可用值：`site, threads, ig, fb, yt, linkedin, email, medium, vocus` |
| `approved_sha` | 否 | 由 `ledger approve` 自動寫入，**不可手動填寫** |
| `sample` | 否 | 只有範例稿使用，新稿不要加 |

### 1.2 內文必備段落（照 SAMPLE-pe.md 結構）
`## 開場畫面`（或具體的開場小標）→ `## 我的判讀` → `## 證據` → `## 什麼情況下我會改口` → `## 接下來`。

## 2. 寫作語氣與內容風格
- **領域聚焦**：專注於美式職業運動（NFL 為主）的賽事分析、球員數據拆解、球隊動態與觀賽洞察。
- **語氣與排版**：專業、客觀、數據導向且具可讀性；使用繁體中文撰寫（專有名詞、球隊名稱與球員姓名保留英文或採「中文（英文）」標註），善用 Markdown `##` 小標題、條列重點與數據對比，避免空泛套話。
- **字元安全**：YAML / Frontmatter 區塊一律使用標準半形雙引號 `"` 或純文字，絕對不可出現全形引號（`“` `”`）。

## 2.1 `ledger check` 驗證規則（`studio/lint.py`，規則設定在 `50-prompts/lint.json`）
注意：`check` **不會**檢查 Frontmatter 欄位是否齊全，欄位正確性要靠第 1.1 節自行確認；`check` 檢查的是內文。

**閘門 A：數字核對（任何一項不過即 FAIL）**
- `unsourced-number`：內文中所有阿拉伯數字（含 `%`）都必須有來源，二選一：
  - 用 `[[fact:ID|顯示文字]]` 包起來，ID 必須先以 `python3 ledger.py fact add "敘述" --number N --unit 單位 --source 網址` 建檔（`python3 ledger.py fact list` 可查既有 ID）。
  - 自己算的、親自數的，用 `{own:…}` 包起來。
  - 例外（不需標註）：行內程式碼、連結網址、有序清單編號、`49ers`／`76ers` 這類名稱、`【待填…】` 占位。
- `fact-missing`：引用的 fact ID 必須存在於資料庫，**嚴禁捏造 ID**。
- `fact-incomplete`：該 fact 必須有來源網址 `source_url` 與抓取日期 `retrieved_at`。
- 中文數字（如「六年」）腳本不檢查，但同樣必須有來源。
- **預設抓取日期**：我提供數據或參考網址但沒註明抓取日期時，直接用執行當天的日期（`date +%F`，格式 `YYYY-MM-DD`）作為 `retrieved_at`，不需另外問我。`fact add` 不加 `--retrieved` 時本來就預設今天；要明寫可加 `--retrieved "$(date +%F)"`。
- **自動拆解網址數據**：我直接貼新聞或數據網址、但沒列出個別數字時，主動讀取該網頁，提取文章需要的關鍵數據，逐條用 `fact add` 建檔（`--source` 填該網址、`--source-name` 填媒體名稱、抓取日期用當天）。每個數字都必須在網頁原文中找得到，不可推估或補數字。只有網頁無法讀取，或頁面上找不到所需數據時，才停下來問我。

**去 AI 化檢查（預設任一項不過即 FAIL；3 項以上要退回重寫）**
- `banned-phrase`：禁用「值得注意的是、總而言之、深入探討、全面解析、賦能、無縫、引領、綜上所述、讓我們一起、不可或缺、眾所周知、無限機遇」及英文 delve、in conclusion、game-changer、seamless、let's dive in 等；禁用句型「不僅……更……」、「在……的時代」。完整清單以 `50-prompts/lint.json` 為準。
- `scaffolding`：不可有兩個以上句子以「首先／其次／再者／最後」（或 firstly/secondly…）開頭。
- `same-opening`：不可連續三段用相同的前 2 個字開頭。
- `flat-rhythm`：句長變異係數須 ≥ 0.35，長短句要交錯。
- `no-first-hand`：至少一處一手證據標記 `{own:…}`、`{watched:…}` 或 `{visited:…}`。
- `no-change-my-mind`：必須有標題含「改口」的段落（如 `## 什麼情況下我會改口`），且內容至少 12 字。
- `placeholder`：不可殘留 `【待填…】` 占位文字。

## 3. 強制執行與自我檢查流程（完成寫檔後必做）
0. 寫稿前，若我貼了網址但沒列數字，先依 2.1「自動拆解網址數據」讀取網頁並建好 fact（抓取日期預設當天），再用取得的 fact ID 撰寫內文。
1. 將文章存檔至 `20-drafts/<content_id>.md`。
2. 立即在終端機執行 `python3 ledger.py check <content_id>` 驗證格式。
3. 若 `check` 出現任何錯誤或缺少欄位警告，必須自動修正檔案並重新執行 `check`，直到最後一行顯示 `結果 RESULT: PASS` 為止（指令結束代碼為 0）。
   - 數字缺來源時，只能改用真實來源建 fact，或改成 `{own:…}`／刪掉該數字；**不可為了過關捏造來源或 fact ID**。若找不到可靠來源，停下來問我。
4. 確認通過後，向我回報文章摘要、儲存路徑，並詢問是否需要接著執行 `python3 ledger.py build` 編譯網站。

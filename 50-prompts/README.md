# 50-prompts 提示詞與設定

| 檔案 | 用途 |
|---|---|
| `01-organize-evidence.md`（整理證據） | 把官方戰報與逐檔紀錄整理成表，不下結論 |
| `02-find-holes.md`（找漏洞） | 針對你的語音判讀找反方解釋與缺來源的句子 |
| `03-de-ai-edit.md`（去 AI 味編修） | 定稿後只標問題、不重寫 |
| `platforms/*.md` | 稿件**核准後**，請 AI 改寫成各平台版本的模板 |
| `platforms/limits.json` | `ledger publish` 產生待貼稿時用的字數上限 |
| `lint.json` | `ledger check` 的去 AI 化規則（禁用詞、門檻），可自行增減 |

原則：主張由你寫，AI 負責整理、反駁與排版。方括號 `[ ]` 是你要填的內容。

`ledger publish` 產生的待貼稿是程式依句子邊界剪出來的機械版本，不經 AI。想要更順的版本，把待貼稿與 `platforms/` 裡對應的模板一起貼給 AI，改完自己再讀一遍。

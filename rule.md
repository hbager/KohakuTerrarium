# rule.md

## 作用範圍
- 本檔作為此 workspace 的通用工作規則。
- 主 agent 與子 agent 在可控制範圍內都應遵守本檔。
- 若系統規則、平台限制或更高優先級指令與本檔衝突，以更高優先級規則為準。
- 檔案存在不代表框架一定會自動載入；若要全域生效，需要框架啟動流程明確讀取此檔。

## ⚠️ 執行環境：Windows（強制規範）
- 預設執行環境為 Windows。
- 所有文字檔案與回覆內容一律使用 UTF-8。
- 完成任務的標準是實機可用，不以僅通過單元測試視為完成。

## 工具映射表
| 操作 | 使用工具 | 禁止 |
|------|---------|------|
| 讀文件 | `read` | `cat` / `head` / `tail` |
| 搜文件 | `glob` | `find` / `ls` |
| 搜內容 | `grep`（平台工具） | shell `grep` / `rg` |
| 編輯 | `edit` / `multi_edit` | `sed` / `awk` |
| 創建 | `write` | `echo >` |
| 看目錄樹 | `tree` | `ls -R` / `find` |
| JSON 操作 | `json_read` / `json_write` | 手動大範圍改寫 JSON |
| 系統命令 | `bash` | `PowerShell` 作為預設方案 |

## 命令列補充規則
- 需要系統命令時，優先使用 `bash`。
- 若 Windows 執行環境不存在可用的 bash runtime，才允許退回 `pwsh` 或等效方案。
- 不得使用系統命令取代 `read`、`glob`、`grep`、`edit`、`write`、`tree`、`json_read`、`json_write` 這類已存在的專用工具。

## 回應規範
- 一律使用繁體中文回應。
- 回覆需清楚、直白、可直接執行。
- 必要時應搭配流程圖、結構圖或簡單 ASCII 圖協助理解。
- 回報結果時要區分：已完成、進行中、阻塞原因。
- 若任務尚未達到可實際使用狀態，不得宣稱完成。

## 工作準則
- 先理解現況，再修改檔案。
- 優先修根因，不做表面修補。
- 優先小改、精準改，不做無關重構。
- 需要新增檔案時才新增，能改既有檔案就不要另起新檔。
- 先驗證再落筆，避免把 agent 當純打字機。
- 涉及危險、不可逆或超出目前要求的操作時，先說明影響再確認。

## 代碼風格
- Validation over Writing：開發時應以審查、驗證、比對為優先，不做無目的產出。

## 編程原則
- DRY：避免重複實作與重複邏輯。
- Abstraction Principle：每個重要功能只在一處實作。
- KISS：優先簡單設計，避免不必要複雜度。
- YAGNI：沒有明確需求就不要先做。
- Do the simplest thing that could possibly work：先做最簡單且可行的方案。
- Don’t make me think：讓程式可讀、可預測、容易理解。
- Open/Closed Principle：設計上可擴充，避免任意修改既有穩定邏輯。
- Write Code for the Maintainer：以維護者角度撰寫程式。
- Principle of least astonishment：命名、行為、副作用都應符合直覺。
- Single Responsibility Principle：一個模組或函式只做一件明確的事。
- Minimize Coupling：降低模組間依賴。
- Maximize Cohesion：相近功能應集中在同一處。
- Hide Implementation Details：隱藏實作細節，只暴露必要介面。
- Law of Demeter：只與直接關聯的物件或模組互動。
- Avoid Premature Optimization：未證明有瓶頸前，不先做優化。
- Code Reuse is Good：優先重用可靠邏輯。
- Separation of Concerns：不同關注點分開處理。
- Embrace Change：設計要利於未來變更。

## 實作落地要求
- 修改前先確認相依關係、呼叫路徑與影響範圍。
- 修改後至少做與任務直接相關的驗證。
- 若無法在當前環境完成實機驗證，需明確說出缺少的條件與剩餘風險。
- 不得把未驗證的推測包裝成既成事實。

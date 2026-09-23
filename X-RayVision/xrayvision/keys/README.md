# 公開金鑰

- `diagnostics_public.pem`：問題回報包加密用的原廠公鑰。

目前為**開發用金鑰**，對應的私鑰在 `tools/keys/diagnostics_private_DEV.pem`（不納入版本控制）。
正式發布前須由原廠指定人員於離線環境產生正式金鑰組，並替換此公鑰（規劃書第 11.9 節）。
- `license_public.pem`：驗證授權檔簽章的原廠公鑰（Ed25519）。

同樣為**開發用金鑰**，私鑰在 `tools/keys/license_private_DEV.pem`。正式發布前須替換為正式金鑰；
替換後，以開發金鑰簽發的授權檔將全部失效。
- `update_public.pem`：驗證更新檔簽章的原廠公鑰（Ed25519）。開發用私鑰在 `tools/keys/update_private_DEV.pem`。

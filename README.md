# Python 工作區

這個 repo 是多專案工作區；**主要專案是 [`VisionSequence/`](VisionSequence/README.md)**——工業機器視覺流程平台（Django + React，含 AI 助手與深度學習教導）。

| 目錄 | 內容 |
|---|---|
| `VisionSequence/` | 機器視覺流程平台（主專案）。全貌見 `VisionSequence/README.md`，開發須知見 `VisionSequence/CLAUDE.md`，文件在 `VisionSequence/docs/`（HTML） |
| `VisionStereo/` | 立體視覺／標記工具（YOLO 資料集格式與 VisionSequence 互通） |
| `TrainingCenter/`、`ZQS-Cloud/`、`ExpAnalysis/`、`BrightenOptix/`、`Patchcore/`、`TestCode/` | 其他獨立專案與實驗 |
| `weights/` | 模型權重（不進版控） |

Git 根目錄在這一層；提交時只加明確路徑。

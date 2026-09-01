# 自動化設備教育訓練中心網站 (Automation Training Hub) — 規格需求書 (PRD)

本文件旨在為開發團隊與 AI Agent / 開發代理提供明確的系統架構、頁面結構、資料模型與功能需求，以便進行自動化設備教育訓練中心網站的開發。

---

## 1. 專案目標與定位 (Project Vision & Goal)

- **目標：** 建立專屬自動化設備工程師（軟體、硬體、機構、視覺）的線上教育訓練與知識庫平台。
- **定位：** 結合**課程學習 (LMS)**、**技術文檔庫 (Documentation Hub)**、**實戰專案演練 (Mini Projects)** 與 **知識庫檢索 (Knowledge Base)**。
- **目標用戶：**
  - **新人學員：** 依循學習地圖進行系統化學習、提交作業與進行測驗。
  - **資深導師 / 講師：** 發布課程、維護技術文檔、批改作業與解答疑難。
  - **系統管理員：** 管理人員權限、審核學習進度與統計分析。

---

## 2. 系統資訊架構 (Information Architecture)

```
Automation Training Hub
├── 1. 首頁 (Home / Dashboard)
│   ├── 學習地圖與推薦進度
│   ├── 最新公告與熱門技術文檔
│   └── 個人學習進度摘要
├── 2. 課程中心 (Course Center)
│   ├── 階段性課程 (Level 1 ~ Level 3)
│   ├── 單元影音 / 圖文教材
│   └── 課後測驗與 Mini Project 專案提交
├── 3. 技術知識庫 (Knowledge Base / Docs)
│   ├── 硬體與通訊 (PLC, PCIe, EtherCAT, Modbus)
│   ├── 視覺與 AI (LabVIEW NGEN, Python, OpenCV, Anomaly Detection)
│   ├── 運動控制 (DENSO, FANUC, Delta Servo)
│   └── 除錯與 Log 分析案例 (Troubleshooting)
├── 4. 實戰演練與評測 (Projects & Assessment)
│   ├── Mini Project 題目庫
│   └── 作業提交與 Code Review 紀錄
└── 5. 個人中心 (User Profile & Assessment)
    ├── 學習歷程與證書
    └── 專案審核狀態與導師評語
```

---

## 3. 核心功能規格 (Core Functional Specifications)

### 3.1 權限與身份驗證 (Auth & Roles)
- **Role 1: Student (學員/新人)**
  - 瀏覽授權課程與文檔。
  - 檢視學習進度、提交專案與測驗。
- **Role 2: Mentor / Instructor (導師/講師)**
  - 上架/編輯課程與 Markdown 技術文檔。
  - 批改學員專案、提供 Code Review 與建議。
- **Role 3: Admin (管理員)**
  - 帳號與權限管理、學習數據統計分析 dashboard。

### 3.2 課程與學習地圖 (Learning Paths)
- 支持階段性關卡鎖定（需完成 Level 1 才能解鎖 Level 2）。
- 支持多媒體內容：Markdown 圖文、嵌入影片、PDF 下載、範例程式碼下載 (.zip, .vi, .py)。

### 3.3 技術知識庫 (Technical Documentation)
- **分類標籤：** 支持多重 Tag（如 `LabVIEW`, `Python`, `EtherCAT`, `Vision`, `DENSO`）。
- **強大搜尋引擎：** 支持全文檢索、標籤篩選、錯誤碼 (Error Code) 快速搜尋。
- **程式碼高亮與渲染：** 支持 Python, C++, C#, LabVIEW block diagram 截圖與標準 Markdown 語法。

### 3.4 實戰 Mini Project 評測系統
- 提供詳細的專案需求規格 (Spec)、輸入輸出定義與驗收標準 (Acceptance Criteria)。
- 學員上傳專案檔案（程式碼 GitHub 連結或 .zip），導師於後台給予評分與意見反饋。

---

## 4. 資料庫架構設計 (Database Schema Design)

```sql
-- 用戶資料表 (Users)
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    role ENUM('student', 'mentor', 'admin') DEFAULT 'student',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 學習地圖與課程表 (Courses)
CREATE TABLE courses (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    level INT DEFAULT 1, -- 1: 觀念與全貌, 2: 模組工具, 3: 專案實戰
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 課程章節表 (Lessons)
CREATE TABLE lessons (
    id INT PRIMARY KEY AUTO_INCREMENT,
    course_id INT FOREIGN KEY REFERENCES courses(id),
    title VARCHAR(255) NOT NULL,
    content_markdown LONGTEXT,
    video_url VARCHAR(500),
    sort_order INT DEFAULT 0
);

-- 知識庫/技術文章 (Knowledge_Articles)
CREATE TABLE knowledge_articles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(100), -- Hardware, Software, Vision, Motion, Troubleshooting
    tags VARCHAR(255), -- e.g. "LabVIEW, EtherCAT, Error-1073807339"
    content_markdown LONGTEXT,
    author_id INT FOREIGN KEY REFERENCES users(id),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Mini Project 提交紀錄 (Project_Submissions)
CREATE TABLE project_submissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    student_id INT FOREIGN KEY REFERENCES users(id),
    repo_url VARCHAR(500),
    file_path VARCHAR(500),
    status ENUM('submitted', 'under_review', 'passed', 'rejected') DEFAULT 'submitted',
    mentor_feedback TEXT,
    score INT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. 技術堆棧建議 (Tech Stack Recommendations)

- **Frontend (前端):** Next.js (React) / Vue3 (Nuxt.js) + Tailwind CSS + Shadcn UI
- **Backend (後端):** Node.js (NestJS) / Python (FastAPI)
- **Database (資料庫):** PostgreSQL / MySQL
- **ORM:** Prisma / SQLAlchemy
- **Search Engine (搜尋引擎):** Meilisearch / Elasticsearch (用於知識庫快速全文檢索)
- **Markdown Processing:** MDX / `react-markdown` + `prismjs` (語法高亮)

---

## 6. 開發里程碑 (Development Roadmap)

- [ ] **Phase 1: MVP 核心基礎 (2 週)**
  - 用戶 Auth、角色分權。
  - Markdown 技術文檔庫 (Knowledge Base) 與全文檢索。
- [ ] **Phase 2: 課程系統與學習地圖 (2 週)**
  - 課程章節瀏覽、學習進度追蹤。
  - 範例程式碼/教材下載區。
- [ ] **Phase 3: 評測與 Mini Project 管理 (2 週)**
  - 學員專案提交系統。
  - 導師 Code Review 與評分介面。
  - 數據 Dashboard。

---

*文件版本：v1.0*  
*建立日期：2026-08-30*  
*適用對象：全棧開發工程師 / AI 開發代理 (Coding Agents)*

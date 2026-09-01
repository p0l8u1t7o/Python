import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import '@siemens/ix/dist/siemens-ix/siemens-ix.css';
import './index.css';
import App from './App';
import Home from './pages/Home';
import EquipmentPage from './pages/EquipmentPage';
import GlossaryPage from './pages/GlossaryPage';
import CadStudioPage from './pages/CadStudioPage';
import LearningPathPage from './pages/LearningPathPage';
import LessonPage from './pages/LessonPage';
import KnowledgePage from './pages/KnowledgePage';
import IdentificationPage from './pages/IdentificationPage';
import QuizPage from './pages/QuizPage';
import ProjectsPage from './pages/ProjectsPage';
import ProfilePage from './pages/ProfilePage';
import SearchPage from './pages/SearchPage';
import DocsPage from './pages/DocsPage';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Home />} />
          <Route path="equipment/:slug" element={<EquipmentPage />} />
          <Route path="learn" element={<LearningPathPage />} />
          <Route path="learn/:course/:lesson" element={<LessonPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="docs/:slug" element={<DocsPage />} />
          <Route path="identify" element={<IdentificationPage />} />
          <Route path="quiz" element={<QuizPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="me" element={<ProfilePage />} />
          <Route path="glossary" element={<GlossaryPage />} />
          <Route path="cad-studio" element={<CadStudioPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);

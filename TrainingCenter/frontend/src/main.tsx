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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<Home />} />
          <Route path="equipment/:slug" element={<EquipmentPage />} />
          <Route path="glossary" element={<GlossaryPage />} />
          <Route path="cad-studio" element={<CadStudioPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);

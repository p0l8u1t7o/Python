import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { Viewer } from "./components/Viewer";
import "./styles.css";

const query = new URLSearchParams(location.search);
const scene = query.get("scene");
const content = scene ? (
  <div className="snapshot-viewer">
    <Viewer
      sceneUrl={scene}
      timelineUrl={query.get("timeline") ?? "/build/timeline.json"}
      initialTime={Number(query.get("t") ?? 0)}
      initialCamera={query.get("cam") ?? "iso"}
      snapshotMode
    />
  </div>
) : (
  <App />
);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{content}</React.StrictMode>,
);

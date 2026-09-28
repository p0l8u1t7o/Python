import { useEffect, useState } from "react";
import { api } from "./api";
import { MainWorkspace } from "./components/MainWorkspace";
import { ProjectList } from "./components/ProjectList";
import { Wizard } from "./components/Wizard";
import type { ProjectSummary, TrashItem } from "./types";

type Screen = { kind: "list" } | { kind: "wizard" } | { kind: "project"; id: string };

export function App() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [screen, setScreen] = useState<Screen>({ kind: "list" });

  const refresh = async () => {
    const [list, deleted] = await Promise.all([
      api<ProjectSummary[]>("/projects"),
      api<TrashItem[]>("/trash").catch(() => []),
    ]);
    setTrash(deleted);
    setProjects(list);
  };
  useEffect(() => {
    void refresh();
  }, []);

  if (screen.kind === "project") {
    return (
      <MainWorkspace
        projectId={screen.id}
        onBack={() => {
          setScreen({ kind: "list" });
          void refresh();
        }}
      />
    );
  }
  if (screen.kind === "wizard") {
    return (
      <Wizard
        onCancel={() => setScreen({ kind: "list" })}
        onComplete={(id) => setScreen({ kind: "project", id })}
      />
    );
  }
  if (!projects) return <div className="center-message">正在載入 CellForge…</div>;
  if (projects.length === 0 && trash.length === 0)
    return <Wizard onComplete={(id) => setScreen({ kind: "project", id })} />;
  return (
    <ProjectList
      projects={projects}
      trash={trash}
      onNew={() => setScreen({ kind: "wizard" })}
      onOpen={(id) => setScreen({ kind: "project", id })}
      onChanged={refresh}
    />
  );
}

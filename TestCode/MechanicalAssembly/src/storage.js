let database;
async function db() {
  if (database) return database;
  database = await new Promise((resolve, reject) => {
    const r = indexedDB.open("assembly-studio", 1);
    r.onupgradeneeded = () =>
      r.result.createObjectStore("projects", { keyPath: "id" });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
  return database;
}
async function action(mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction("projects", mode);
    let r = fn(tx.objectStore("projects"));
    tx.oncomplete = () => resolve(r.result);
    tx.onerror = () => reject(tx.error);
  });
}
export const saveProject = (p) => action("readwrite", (s) => s.put(p));
export const listProjects = () => action("readonly", (s) => s.getAll());
export const getProject = (id) => action("readonly", (s) => s.get(id));

export function overviewEntries(project, manifest) {
  return project.stations.map((station) => {
    const asset = manifest[station.sample];
    const counts = asset?.counts || {};
    const available = !!(station.model || asset?.url || station.parts.length);
    const partial = !!(
      counts.missing ||
      counts.unsupported ||
      counts.rejectedFaces
    );
    return {
      station,
      asset,
      available,
      status: !available ? "無可顯示幾何" : partial ? "部分還原" : "可顯示模型",
    };
  });
}

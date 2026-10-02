const key = "assembly-studio-theme";
export function initializeTheme(onChange) {
  let theme = "light";
  try {
    theme = localStorage.getItem(key) || "light";
  } catch {}
  if (!["light", "dark"].includes(theme)) theme = "light";
  const button = document.createElement("button");
  button.id = "theme-toggle";
  button.className = "button ghost theme-toggle";
  document.querySelector(".header-actions").prepend(button);
  function apply() {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    button.textContent = theme === "dark" ? "☀ 亮色" : "☾ 暗色";
    button.setAttribute(
      "aria-label",
      theme === "dark" ? "切換為亮色主題" : "切換為暗色主題",
    );
    button.setAttribute("aria-pressed", String(theme === "dark"));
    try {
      localStorage.setItem(key, theme);
    } catch {}
    onChange(theme);
  }
  button.onclick = () => {
    theme = theme === "dark" ? "light" : "dark";
    apply();
  };
  apply();
  return () => theme;
}

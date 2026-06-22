// js/tabs.js
const Tabs = (() => {
  let currentTab = "all";
  let onChange = () => {};

  function init(onChangeCallback) {
    onChange = onChangeCallback || (() => {});
    const tabs = document.querySelectorAll(".tab");
    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        tabs.forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        currentTab = tab.dataset.tab;
        onChange(currentTab);
      });
    });
  }

  function getCurrentTab() {
    return currentTab;
  }

  return { init, getCurrentTab };
})();

// js/pagination.js
const Pagination = (() => {
  const perPage = 20;
  let currentPage = 1;
  let onChange = () => {};

  let prevBtn, nextBtn, pageInfo;

  function init(onChangeCallback) {
    onChange = onChangeCallback || (() => {});
    prevBtn = document.getElementById("prevBtn");
    nextBtn = document.getElementById("nextBtn");
    pageInfo = document.getElementById("pageInfo");

    prevBtn?.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage--;
        onChange(currentPage);
      }
    });

    nextBtn?.addEventListener("click", () => {
      onChange(currentPage + 1, true); // request next, clamp handled by update()
    });
  }

  function reset() {
    currentPage = 1;
  }

  function getCurrentPage() {
    return currentPage;
  }

  function getPerPage() {
    return perPage;
  }

  // recompute currentPage against a total item count, update UI, return page slice bounds
  function update(totalItems) {
    const totalPages = Math.max(1, Math.ceil(totalItems / perPage));
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    if (pageInfo) pageInfo.textContent = `${currentPage} / ${totalPages}`;
    if (prevBtn) prevBtn.disabled = currentPage === 1;
    if (nextBtn) nextBtn.disabled = currentPage === totalPages;

    const start = (currentPage - 1) * perPage;
    return { start, end: start + perPage, totalPages };
  }

  // for next button: bump page then let caller re-render/update
  function goToPage(page) {
    currentPage = page;
  }

  return { init, reset, getCurrentPage, getPerPage, update, goToPage };
})();
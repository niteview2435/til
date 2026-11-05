/* Scroll-triggered reveal. Each .reveal group (a record label or a block)
   fades in as a whole when it enters the viewport. */
(function () {
  // Auto-typeset is disabled in the page config; trigger it once up front.
  if (window.MathJax && window.MathJax.startup) {
    window.MathJax.startup.promise.then(function () {
      return window.MathJax.typesetPromise();
    });
  }

  var observer = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in-view");
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.1 }
  );

  document.querySelectorAll(".reveal").forEach(function (el) {
    observer.observe(el);
  });
})();

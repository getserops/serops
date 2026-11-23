import { useEffect } from "react";

/**
 * Says where a sideways-scrolling element stands, as data-scroll on the
 * element: "none" (everything fits), "start", "middle" or "end". The
 * stylesheet (.ds-scroll-cue) shows a soft edge on the side where more
 * columns are. It also publishes the width of the first column as
 * --sticky-offset, for a second column kept in place beside it.
 */
export const scrollPosition = ({ scrollLeft, scrollWidth, clientWidth }) => {
  if (scrollWidth <= clientWidth + 1) return "none";
  if (scrollLeft <= 1) return "start";
  if (scrollLeft + clientWidth >= scrollWidth - 1) return "end";
  return "middle";
};

export default function useScrollCue(ref) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => {
      el.dataset.scroll = scrollPosition(el);
      // Where a second sticky column starts: the real width of the first.
      const first = el.querySelector("thead th");
      if (first) el.style.setProperty("--sticky-offset", `${first.offsetWidth}px`);
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    if (observer) { observer.observe(el); if (el.firstElementChild) observer.observe(el.firstElementChild); }
    return () => { el.removeEventListener("scroll", update); if (observer) observer.disconnect(); };
  });
}

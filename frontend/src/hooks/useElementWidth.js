import { useLayoutEffect, useRef, useState } from "react";

/**
 * Width of an element, kept up to date. A layout that depends on the room
 * a table really has (the menu open or closed, a panel beside it) reads it
 * from here, not from the window.
 * Returns null until measured, and where the browser cannot observe sizes.
 */
export default function useElementWidth(ref) {
  const [width, setWidth] = useState(null);
  const watched = useRef({ el: null, observer: null });
  // No dependency list: the element appears after the first data arrives,
  // and a ref change does not render. The observer is only rebuilt when the
  // element itself changed.
  useLayoutEffect(() => {
    const el = ref.current;
    if (el === watched.current.el) return;
    watched.current.observer?.disconnect();
    watched.current = { el, observer: null };
    if (!el) return;
    const read = () => {
      const w = Math.round(el.getBoundingClientRect().width);
      if (w > 0) setWidth(w);
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    watched.current.observer = new ResizeObserver(read);
    watched.current.observer.observe(el);
  });
  useLayoutEffect(() => () => watched.current.observer?.disconnect(), []);
  return width;
}

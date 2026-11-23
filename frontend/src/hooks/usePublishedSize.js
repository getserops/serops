import { useLayoutEffect } from "react";

/**
 * Publishes the real height of an element as a CSS variable on <html>, and
 * keeps it up to date. Layouts that fill the screen (the chat) subtract the
 * measured height of the top bar instead of assuming one: on a phone the
 * bar can be taller than on a desktop.
 * The variable is removed when the element goes away, so the CSS falls back
 * to its token.
 */
export function usePublishedHeight(ref, variable) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const el = ref.current;
    if (!el) return undefined;
    const publish = () => root.style.setProperty(variable, `${el.offsetHeight}px`);
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    if (observer) observer.observe(el);
    return () => {
      if (observer) observer.disconnect();
      root.style.removeProperty(variable);
    };
  }, [ref, variable]);
}

/**
 * Publishes the height of the part of the screen a person really sees as
 * --visual-vh: on a phone it shrinks when the on-screen keyboard opens,
 * which 100vh and 100dvh do not do everywhere. Absent where the browser
 * has no visualViewport; the CSS then uses 100dvh.
 */
export function useVisualViewportHeight() {
  useLayoutEffect(() => {
    const view = window.visualViewport;
    if (!view) return undefined;
    const root = document.documentElement;
    const publish = () => root.style.setProperty("--visual-vh", `${Math.round(view.height)}px`);
    publish();
    view.addEventListener("resize", publish);
    return () => {
      view.removeEventListener("resize", publish);
      root.style.removeProperty("--visual-vh");
    };
  }, []);
}

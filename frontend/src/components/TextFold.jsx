import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { FaChevronRight } from "react-icons/fa";
import { splitSentences, splitSteps } from "../utils/sentences";
import "./TextFold.css";

// Long texts written by the AI, shown in part with "Show more" (Overview card
// and issue panel). Nothing is removed: the folded part stays in the page,
// only its display is limited, and a cut never lands inside a sentence.

const MoreButton = ({ open, onClick, controls, t }) => (
  <button type="button" className="attention-more" aria-expanded={open} aria-controls={controls} onClick={onClick}>
    {t(open ? "dashboard.attention.showLess" : "dashboard.attention.showMore")}
  </button>
);

// A paragraph held to three lines (CSS line clamp), with "Show more" when
// the text does not fit.
export const Clamped = ({ text, t }) => {
  const ref = useRef(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return undefined;
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, open]);
  return (
    <>
      <p ref={ref} id={id} className={open ? undefined : "attention-clamp-3"}>{text}</p>
      {(overflows || open) && <MoreButton open={open} controls={id} onClick={() => setOpen(!open)} t={t} />}
    </>
  );
};

// The first `shown` sentences, with "Show more" for the rest, which stays in
// the paragraph, hidden.
export const SentenceFold = ({ text, shown = 2, t }) => {
  const id = useId();
  const [open, setOpen] = useState(false);
  const sentences = splitSentences(text);
  if (sentences.length <= shown) return <p>{text}</p>;
  return (
    <>
      <p>
        {sentences.slice(0, shown).join(" ")}
        <span id={id} hidden={!open}>{` ${sentences.slice(shown).join(" ")}`}</span>
      </p>
      <MoreButton open={open} controls={id} onClick={() => setOpen(!open)} t={t} />
    </>
  );
};

// "What to do" as numbered steps, one sentence each: the first `limit`
// show, the rest after "Show more". A single step stays a paragraph.
export const Steps = ({ text, t, limit = Infinity }) => {
  const id = useId();
  const [open, setOpen] = useState(false);
  const steps = splitSteps(text);
  if (steps.length < 2) return <p>{text}</p>;
  const shown = open ? steps : steps.slice(0, limit);
  return (
    <>
      <ol id={id} className="attention-steps">
        {shown.map((step, i) => <li key={i}>{step}</li>)}
      </ol>
      {steps.length > limit && <MoreButton open={open} controls={id} onClick={() => setOpen(!open)} t={t} />}
    </>
  );
};

// A section folded behind its title, closed by default. `extra` sits on the
// title line (the confidence beside "Why the AI thinks so"). The folded
// content stays in the page, hidden.
export const Fold = ({ title, extra, className, children }) => {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <section className={className}>
      <h3 className="text-fold-title">
        <button type="button" className="text-fold-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          <FaChevronRight className="text-fold-icon" aria-hidden="true" />
          <span>{title}</span>
          {extra}
        </button>
      </h3>
      <div id={id} className="text-fold-body" hidden={!open}>{children}</div>
    </section>
  );
};

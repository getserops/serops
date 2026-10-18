import React, { useId, useRef } from 'react';

/**
 * One way to pick one value in settings.
 *
 * variant="segmented" — short ordinal values (30m · 1h · 4h, 7 · 14 · 30 days).
 * variant="cards"     — options that differ in kind (AI providers), each
 *                       with an optional second line.
 *
 * It is a radio group: Tab lands on the selected option, arrow keys move
 * the selection, and screen readers announce "radio, 2 of 5, checked".
 *
 * options: [{ value, label, description?, disabled?, badge? }]
 */
const ChoiceGroup = ({ label, hint, options, value, onChange, variant = 'segmented', className = '' }) => {
    const labelId = useId();
    const hintId = useId();
    const refs = useRef([]);
    const enabled = options.filter((o) => !o.disabled);
    const selectedIndex = options.findIndex((o) => o.value === value);
    // Roving tabindex: the selected option, or the first enabled one.
    const tabIndexOf = (i) => {
        if (selectedIndex >= 0) return i === selectedIndex ? 0 : -1;
        return options[i] === enabled[0] ? 0 : -1;
    };

    const move = (from, step) => {
        const n = options.length;
        for (let k = 1; k <= n; k += 1) {
            const i = (from + step * k + n) % n;
            if (!options[i].disabled) {
                onChange(options[i].value);
                refs.current[i]?.focus();
                return;
            }
        }
    };

    const onKeyDown = (e, i) => {
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); move(i, 1); }
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); move(i, -1); }
        else if (e.key === 'Home') { e.preventDefault(); move(-1, 1); }
        else if (e.key === 'End') { e.preventDefault(); move(options.length, -1); }
    };

    return (
        <div className={`ds-choice ${className}`}>
            {label && <div className="ds-choice-label" id={labelId}>{label}</div>}
            <div
                role="radiogroup"
                aria-labelledby={label ? labelId : undefined}
                aria-describedby={hint ? hintId : undefined}
                className={variant === 'cards' ? 'ds-choice-cards' : 'ds-segmented'}
            >
                {options.map((o, i) => {
                    const checked = o.value === value;
                    return (
                        <button
                            key={String(o.value)}
                            ref={(el) => { refs.current[i] = el; }}
                            type="button"
                            role="radio"
                            aria-checked={checked}
                            disabled={o.disabled}
                            tabIndex={tabIndexOf(i)}
                            className={`ds-choice-option ${checked ? 'is-checked' : ''}`}
                            onClick={() => onChange(o.value)}
                            onKeyDown={(e) => onKeyDown(e, i)}
                        >
                            {variant === 'cards' ? (
                                <>
                                    <span className="ds-choice-radio" aria-hidden="true" />
                                    <span className="ds-choice-text">
                                        <span className="ds-choice-title">{o.label}</span>
                                        {o.description && <span className="ds-choice-desc">{o.description}</span>}
                                    </span>
                                    {o.badge}
                                </>
                            ) : o.label}
                        </button>
                    );
                })}
            </div>
            {hint && <div className="ds-choice-hint" id={hintId}>{hint}</div>}
        </div>
    );
};

export default ChoiceGroup;

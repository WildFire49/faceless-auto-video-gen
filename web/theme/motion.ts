/**
 * Motion tokens (SPEC.md 8.1).
 *
 * Springs, never linear easing. A spring is interruptible and has momentum, so
 * a transition that is reversed mid-flight continues from where it actually is
 * rather than snapping. That physicality is most of what makes an interface
 * feel Apple-like.
 */

/** Spring configurations, by the kind of thing being moved. */
export const spring = {
  /** Buttons and small controls: fast, barely any overshoot. */
  press: { type: 'spring', stiffness: 400, damping: 30, mass: 0.6 },
  /** Gate transitions and sheets: substantial but not sluggish. */
  sheet: { type: 'spring', stiffness: 280, damping: 32, mass: 0.9 },
  /** Lists reflowing after an approve: soft, so the eye can follow. */
  settle: { type: 'spring', stiffness: 180, damping: 26, mass: 1 },
} as const;

/**
 * Spatial consistency (SPEC.md 8.1): gates A->F always advance to the right,
 * and "send back to gate X" moves left. The direction tells you which way you
 * travelled without reading anything.
 */
export const direction = {
  forward: 24,
  backward: -24,
} as const;

/**
 * The reduced-motion fallback. Every animated component routes through this
 * rather than deciding for itself, so honouring the preference is automatic
 * instead of something to remember (SPEC.md 8.1, non-negotiable).
 */
export const reducedFallback = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  transition: { duration: 0.12 },
} as const;

/**
 * Build enter/exit props for a panel, respecting the user's motion preference.
 *
 * @param reduced - whether prefers-reduced-motion is set
 * @param dx - horizontal offset to travel from; use `direction`
 */
export function slideIn(reduced: boolean, dx: number = direction.forward) {
  if (reduced) return reducedFallback;
  return {
    initial: { opacity: 0, x: dx },
    animate: { opacity: 1, x: 0 },
    transition: spring.sheet,
  };
}

/**
 * Reads prefers-reduced-motion.
 *
 * Every animated component routes through this hook, so honouring the
 * preference is automatic rather than something each component must remember
 * (SPEC.md 8.1, non-negotiable).
 */

'use client';

import { useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

export function useReducedMotion(): boolean {
  // Defaults to false, then corrects after mount. Server-side there is no
  // media query to read, and guessing `true` would make the first paint
  // animate differently from every subsequent one.
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    setReduced(mq.matches);

    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return reduced;
}

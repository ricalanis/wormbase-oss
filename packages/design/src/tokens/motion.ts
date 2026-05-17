/**
 * Field Notebook motion.
 *
 * One orchestrated page-load reveal with staggered entry. Gauges breathe
 * (±0.5% pulse every 3s — "the worm is alive but controlled"). No scattered
 * micro-interactions, no cursor blinks, no hover-glitter.
 */
export const motion = {
  easing: {
    /** Slow, organic breathing — used for gauge pulse only. */
    breathing: "cubic-bezier(0.45, 0.05, 0.55, 0.95)",
    /** Decisive entry for staggered reveals — page load only. */
    entry: "cubic-bezier(0.2, 0.8, 0.2, 1)",
    /** Default UI transition — near-linear, institutional. */
    standard: "cubic-bezier(0.4, 0.0, 0.2, 1)",
  },
  duration: {
    /** Stagger offset between sibling reveal entries. */
    staggerEntry: 80,
    entry: 420,
    standard: 180,
    /** Full breathing cycle — inhale + exhale. */
    breathing: 3000,
  },
  /** Breathing amplitude: ±0.5% scale pulse. */
  breathingAmplitude: 0.005,
} as const;

export type EasingToken = keyof typeof motion.easing;
export type DurationToken = keyof typeof motion.duration;

import { cx } from './utils'

const VARIANTS = {
  pending: 'bg-surface-container-high text-on-surface-variant',
  running: 'bg-primary-fixed text-on-primary-fixed-variant',
  done: 'bg-secondary-container text-on-secondary-container',
  warn: 'bg-tertiary-container text-on-tertiary-container',
  error: 'bg-error/10 text-error',
  info: 'bg-ai-accent-light text-on-tertiary-container',
  amber: 'bg-amber-100 text-amber-800',
  purple: 'bg-violet-100 text-violet-700',
  cyan: 'bg-cyan-100 text-cyan-700',
  muted: 'bg-surface-container-high text-outline',
}

const SHAPES = {
  pill: 'rounded-full',
  square: 'rounded-md',
}

const SIZES = {
  xs: 'px-2 py-0.5 text-[11px]',
  sm: 'px-2.5 py-1 text-xs',
}

export default function Badge({
  children,
  className = '',
  shape = 'pill',
  size = 'sm',
  variant = 'pending',
}) {
  return (
    <span className={cx('inline-flex items-center whitespace-nowrap font-semibold', VARIANTS[variant] || VARIANTS.pending, SHAPES[shape] || SHAPES.pill, SIZES[size] || SIZES.sm, className)}>
      {children}
    </span>
  )
}

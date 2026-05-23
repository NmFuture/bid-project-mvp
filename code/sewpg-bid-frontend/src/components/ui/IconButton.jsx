import { cx } from './utils'

const VARIANTS = {
  quiet: 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim',
  ghost: 'bg-transparent text-on-surface-variant hover:bg-surface-container-low hover:text-primary',
  primary: 'bg-primary text-on-primary hover:bg-primary-container hover:text-on-primary-container',
  danger: 'bg-error/10 text-error hover:bg-error/15',
}

const SIZES = {
  xs: 'h-6 w-6 text-[15px]',
  sm: 'h-8 w-8 text-[16px]',
  md: 'h-9 w-9 text-[18px]',
}

export default function IconButton({
  'aria-label': ariaLabel,
  className = '',
  icon,
  size = 'md',
  type = 'button',
  variant = 'ghost',
  ...props
}) {
  return (
    <button
      type={type}
      aria-label={ariaLabel}
      title={props.title || ariaLabel}
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        VARIANTS[variant] || VARIANTS.ghost,
        SIZES[size] || SIZES.md,
        className,
      )}
      {...props}
    >
      <span aria-hidden="true" className="material-symbols-outlined text-[inherit]">
        {icon}
      </span>
    </button>
  )
}

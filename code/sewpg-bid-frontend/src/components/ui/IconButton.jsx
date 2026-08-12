import { cx } from './utils'

const VARIANTS = {
  quiet: 'border border-transparent bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high',
  ghost: 'border border-transparent bg-transparent text-on-surface-variant hover:bg-surface-container-low hover:text-primary',
  primary: 'border border-primary bg-primary text-on-primary hover:border-on-primary-fixed-variant hover:bg-on-primary-fixed-variant',
  danger: 'border border-error/20 bg-error/10 text-error hover:bg-error/15',
}

const SIZES = {
  xs: 'h-8 w-8 text-[16px]',
  sm: 'h-8 w-8 text-[16px]',
  md: 'h-11 w-11 text-[18px] sm:h-10 sm:w-10',
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
        'ui-icon-control inline-flex shrink-0 items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:bg-surface-container-low disabled:text-outline',
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

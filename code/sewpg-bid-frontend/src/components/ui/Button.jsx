import { cx } from './utils'

const VARIANTS = {
  primary: 'border border-primary bg-primary text-on-primary hover:border-on-primary-fixed-variant hover:bg-on-primary-fixed-variant',
  success: 'border border-on-secondary-fixed bg-on-secondary-fixed text-white hover:border-on-secondary-container hover:bg-on-secondary-container',
  secondary: 'border border-outline-variant bg-surface text-on-surface hover:border-primary/45 hover:bg-primary-fixed',
  quiet: 'border border-transparent bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high',
  ghost: 'border border-transparent bg-transparent text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface',
  danger: 'border border-error bg-error text-on-error hover:border-on-error-container hover:bg-on-error-container',
  dangerQuiet: 'border border-error/20 bg-error/10 text-error hover:bg-error/15',
  text: 'border border-transparent bg-transparent text-primary hover:bg-primary/10',
}

const SIZES = {
  xs: 'h-8 px-2.5 text-xs',
  sm: 'h-8 px-3 text-xs',
  md: 'h-11 px-4 text-sm sm:h-10',
  lg: 'h-11 px-5 text-sm',
  stage: 'h-11 min-w-36 px-4 text-sm sm:h-10',
}

export default function Button({
  as,
  children,
  className = '',
  size = 'md',
  type = 'button',
  variant = 'primary',
  ...props
}) {
  const Component = as || 'button'
  const content = typeof children === 'string' || typeof children === 'number'
    ? <span className="leading-none">{children}</span>
    : children

  return (
    <Component
      type={Component === 'button' ? type : undefined}
      className={cx(
        'ui-control inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-semibold transition-[background-color,color,border-color,box-shadow] disabled:cursor-not-allowed disabled:border-outline-variant disabled:bg-surface-container-low disabled:text-outline',
        'focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-1 focus-visible:ring-offset-surface',
        VARIANTS[variant] || VARIANTS.primary,
        SIZES[size] || SIZES.md,
        className,
      )}
      {...props}
    >
      {content}
    </Component>
  )
}

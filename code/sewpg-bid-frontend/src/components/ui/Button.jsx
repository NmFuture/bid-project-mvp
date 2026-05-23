import { cx } from './utils'

const VARIANTS = {
  primary: 'bg-primary text-on-primary shadow-[0_1px_2px_rgba(0,104,183,0.18)] hover:bg-primary-container hover:text-on-primary-container',
  success: 'bg-secondary text-on-secondary shadow-[0_1px_2px_rgba(20,168,59,0.18)] hover:bg-secondary/90 hover:text-on-secondary',
  secondary: 'bg-secondary-container text-on-secondary-container hover:bg-secondary-fixed',
  quiet: 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim',
  ghost: 'bg-transparent text-on-surface-variant hover:bg-surface-container-low',
  danger: 'bg-error text-on-error shadow-[0_1px_2px_rgba(197,64,64,0.16)] hover:bg-error/90',
  dangerQuiet: 'bg-error/10 text-error hover:bg-error/15',
  text: 'bg-transparent text-primary hover:bg-primary/10',
}

const SIZES = {
  xs: 'h-7 px-2 text-xs',
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
  lg: 'h-10 px-5 text-sm',
  stage: 'h-[30px] min-w-[112px] px-3.5 text-sm',
}

export default function Button({
  as,
  children,
  className = '',
  icon,
  iconPosition = 'left',
  size = 'md',
  type = 'button',
  variant = 'primary',
  ...props
}) {
  const Component = as || 'button'
  const content = typeof children === 'string' || typeof children === 'number'
    ? <span className="leading-none">{children}</span>
    : children
  const iconNode = icon ? (
    <span aria-hidden="true" className={cx('material-symbols-outlined', size === 'xs' || size === 'sm' ? 'text-[16px]' : 'text-[18px]')}>
      {icon}
    </span>
  ) : null

  return (
    <Component
      type={Component === 'button' ? type : undefined}
      className={cx(
        'inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-semibold transition-[background-color,color,box-shadow,border-color,transform] disabled:cursor-not-allowed disabled:opacity-50',
        'focus-visible:ring-2 focus-visible:ring-primary/35 focus-visible:ring-offset-1 focus-visible:ring-offset-surface',
        VARIANTS[variant] || VARIANTS.primary,
        SIZES[size] || SIZES.md,
        className,
      )}
      {...props}
    >
      {iconPosition === 'left' ? iconNode : null}
      {content}
      {iconPosition === 'right' ? iconNode : null}
    </Component>
  )
}

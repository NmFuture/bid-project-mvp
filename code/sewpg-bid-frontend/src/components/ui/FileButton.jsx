import { cx } from './utils'

const VARIANTS = {
  primary: 'border border-primary bg-primary text-on-primary hover:border-on-primary-fixed-variant hover:bg-on-primary-fixed-variant',
  success: 'border border-on-secondary-fixed bg-on-secondary-fixed text-white hover:border-on-secondary-container hover:bg-on-secondary-container',
  secondary: 'border border-outline-variant bg-surface text-on-surface hover:border-primary/45 hover:bg-primary-fixed',
  quiet: 'border border-transparent bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high',
  ghost: 'border border-transparent bg-transparent text-on-surface-variant hover:bg-surface-container-low',
  danger: 'border border-error bg-error text-on-error hover:border-on-error-container hover:bg-on-error-container',
}

const SIZES = {
  xs: 'h-8 px-2.5 text-xs',
  sm: 'h-8 px-3 text-xs',
  md: 'h-11 px-4 text-sm sm:h-10',
  lg: 'h-11 px-5 text-sm',
  stage: 'h-11 min-w-36 px-4 text-sm sm:h-10',
}

export default function FileButton({
  accept,
  children,
  className = '',
  disabled = false,
  icon = 'upload_file',
  multiple = false,
  onChange,
  size = 'md',
  variant = 'quiet',
}) {
  return (
    <label
      className={cx(
        'ui-control inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-md font-semibold transition-[background-color,color,border-color,box-shadow]',
        'focus-within:ring-2 focus-within:ring-primary/35 focus-within:ring-offset-1 focus-within:ring-offset-surface',
        'has-[:disabled]:pointer-events-none has-[:disabled]:border-outline-variant has-[:disabled]:bg-surface-container-low has-[:disabled]:text-outline',
        VARIANTS[variant] || VARIANTS.quiet,
        SIZES[size] || SIZES.md,
        disabled ? 'pointer-events-none border-outline-variant bg-surface-container-low text-outline' : '',
        className,
      )}
    >
      {icon ? (
        <span aria-hidden="true" className={cx('material-symbols-outlined', size === 'xs' || size === 'sm' ? 'text-[16px]' : 'text-[18px]')}>
          {icon}
        </span>
      ) : null}
      <span className="leading-none">{children}</span>
      <input
        type="file"
        multiple={multiple}
        accept={accept}
        className="sr-only"
        onChange={onChange}
        disabled={disabled}
      />
    </label>
  )
}

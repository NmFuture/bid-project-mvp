import { cx } from './utils'

const VARIANTS = {
  primary: 'bg-primary text-on-primary shadow-[0_1px_2px_rgba(0,104,183,0.18)] hover:bg-primary-container hover:text-on-primary-container',
  success: 'bg-secondary text-on-secondary shadow-[0_1px_2px_rgba(20,168,59,0.18)] hover:bg-secondary/90 hover:text-on-secondary',
  secondary: 'bg-secondary-container text-on-secondary-container hover:bg-secondary-fixed',
  quiet: 'bg-surface-container-high text-on-surface-variant hover:bg-surface-dim',
  ghost: 'bg-transparent text-on-surface-variant hover:bg-surface-container-low',
  danger: 'bg-error text-on-error shadow-[0_1px_2px_rgba(197,64,64,0.16)] hover:bg-error/90',
}

const SIZES = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
  lg: 'h-10 px-5 text-sm',
  stage: 'h-[30px] min-w-[112px] px-3.5 text-sm',
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
        'inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-md font-semibold transition-[background-color,color,box-shadow,border-color,transform]',
        'focus-within:ring-2 focus-within:ring-primary/35 focus-within:ring-offset-1 focus-within:ring-offset-surface',
        'has-[:disabled]:pointer-events-none has-[:disabled]:opacity-50',
        VARIANTS[variant] || VARIANTS.quiet,
        SIZES[size] || SIZES.md,
        disabled ? 'pointer-events-none opacity-50' : '',
        className,
      )}
    >
      {icon ? (
        <span aria-hidden="true" className={cx('material-symbols-outlined', size === 'sm' ? 'text-[16px]' : 'text-[18px]')}>
          {icon}
        </span>
      ) : null}
      <span className="leading-none">{children}</span>
      <input
        type="file"
        multiple={multiple}
        accept={accept}
        className="hidden"
        onChange={onChange}
        disabled={disabled}
      />
    </label>
  )
}

import { cx } from './utils'

export default function Toolbar({
  children,
  className = '',
  justify = 'end',
}) {
  const justifyClass = justify === 'between' ? 'justify-between' : justify === 'start' ? 'justify-start' : 'justify-end'
  return (
    <div className={cx('flex flex-wrap items-center gap-2', justifyClass, className)}>
      {children}
    </div>
  )
}
